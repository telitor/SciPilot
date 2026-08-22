import struct
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api import routes
from services.pdf_extraction_service import (
    _MAX_OCR_PNG_BYTES,
    PdfExtractionError,
    _OcrUnavailableError,
    _bounded_ocr_long_edge,
    _extract_digital_page,
    _ocr_page_from_pdf,
    _validated_ocr_png_dimensions,
    extract_pdf,
)


class FakePage:
    def __init__(
        self,
        text: str = "",
        error: Exception | None = None,
        *,
        width: float = 612,
        height: float = 792,
        cm=None,
        tm=None,
        font_size: float = 12,
    ):
        self.text = text
        self.error = error
        self.mediabox = SimpleNamespace(width=width, height=height)
        self.rotation = 0
        self.cm = cm if cm is not None else [1, 0, 0, 1, 0, 0]
        self.tm = tm if tm is not None else [1, 0, 0, 1, 72, 720]
        self.font_size = font_size

    def extract_text(self, visitor_text=None):
        if self.error:
            raise self.error
        if visitor_text and self.text.strip():
            visitor_text(
                self.text,
                self.cm,
                self.tm,
                None,
                self.font_size,
            )
        return self.text


def fake_pypdf(reader):
    return patch.dict(
        sys.modules,
        {"pypdf": SimpleNamespace(PdfReader=lambda *_args, **_kwargs: reader)},
    )


class PdfExtractionServiceTests(unittest.TestCase):
    def test_ocr_render_scale_caps_extreme_page_pixels(self):
        scale_to = _bounded_ocr_long_edge(1_000_000, 1_000_000, 300)

        self.assertLessEqual(scale_to, 4096)
        self.assertLessEqual(scale_to * scale_to, 12_000_000)

    def test_ocr_rejects_oversized_png_bytes_and_dimensions(self):
        with TemporaryDirectory() as temp_dir:
            oversized_bytes = Path(temp_dir) / "oversized-bytes.png"
            with oversized_bytes.open("wb") as handle:
                handle.truncate(_MAX_OCR_PNG_BYTES + 1)
            with self.assertRaises(RuntimeError):
                _validated_ocr_png_dimensions(oversized_bytes)

            oversized_dimensions = Path(temp_dir) / "oversized-dimensions.png"
            oversized_dimensions.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + b"\x00" * 8
                + struct.pack(">II", 4097, 100)
            )
            with self.assertRaises(RuntimeError):
                _validated_ocr_png_dimensions(oversized_dimensions)

    def test_poppler_receives_bounded_scale_before_tesseract(self):
        calls: list[list[str]] = []

        def fake_run(arguments, **_kwargs):
            calls.append(arguments)
            if arguments[0] == "pdftoppm":
                image_path = Path(arguments[-1]).with_suffix(".png")
                image_path.write_bytes(
                    b"\x89PNG\r\n\x1a\n"
                    + b"\x00" * 8
                    + struct.pack(">II", 3464, 3464)
                )
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                    "left\ttop\twidth\theight\tconf\ttext\n"
                    "5\t1\t1\t1\t1\t1\t10\t20\t100\t30\t90\tevidence\n"
                ),
                stderr="",
            )

        with (
            patch(
                "services.pdf_extraction_service.shutil.which",
                side_effect=lambda name: name,
            ),
            patch(
                "services.pdf_extraction_service.subprocess.run",
                side_effect=fake_run,
            ),
        ):
            result = _ocr_page_from_pdf(
                b"%PDF-demo",
                1,
                dpi=300,
                page_width_points=1_000_000,
                page_height_points=1_000_000,
                languages="eng",
                timeout_seconds=10,
                minimum_confidence=35,
            )

        render_arguments = calls[0]
        scale_to = int(render_arguments[render_arguments.index("-scale-to") + 1])
        self.assertLessEqual(scale_to, 4096)
        self.assertEqual(result["text"], "evidence")

    def test_layout_bbox_composes_text_and_current_matrix_scaling(self):
        page = FakePage(
            "AB",
            width=200,
            height=200,
            cm=[1.5, 0, 0, 0.5, 5, 10],
            tm=[2, 0, 0, 3, 10, 20],
            font_size=10,
        )

        bbox = _extract_digital_page(page)["segments"][0]["bbox"]

        expected = [0.1, 0.825, 0.256, 0.91875]
        for actual, target in zip(bbox, expected):
            self.assertAlmostEqual(actual, target, places=5)

    def test_layout_bbox_normalizes_rotated_and_negative_scaling(self):
        page = FakePage(
            "AB",
            width=200,
            height=200,
            tm=[0, -2, -3, 0, 100, 100],
            font_size=10,
        )

        bbox = _extract_digital_page(page)["segments"][0]["bbox"]

        self.assertEqual(bbox, [0.35, 0.5, 0.5375, 0.604])
        self.assertTrue(all(0.0 <= coordinate <= 1.0 for coordinate in bbox))
        self.assertLess(bbox[0], bbox[2])
        self.assertLess(bbox[1], bbox[3])

    def test_extracts_bounded_text_with_one_based_page_labels(self):
        reader = SimpleNamespace(
            is_encrypted=False,
            metadata=SimpleNamespace(title="Demo", author="Alice; Bob"),
            pages=[FakePage("first page"), FakePage("second page")],
        )
        with fake_pypdf(reader):
            result = extract_pdf(b"%PDF-demo", "demo.pdf", max_chars=16)

        self.assertEqual(result["title"], "Demo")
        self.assertEqual(result["authors"], ["Alice", "Bob"])
        self.assertEqual([item["page"] for item in result["pages"]], [1, 2])
        self.assertIn("【第 1 页】", result["prompt_text"])
        self.assertLessEqual(len(result["text"]), 16 + 2)
        self.assertEqual(result["extraction_method"], "digital")
        self.assertEqual(result["digital_page_count"], 2)
        self.assertEqual(result["page_evidence"][0]["coordinate_space"], "normalized-top-left")
        self.assertEqual(result["page_evidence"][0]["segments"][0]["text"], "first page")

    def test_rejects_password_protected_pdf(self):
        reader = SimpleNamespace(
            is_encrypted=True,
            decrypt=lambda _password: 0,
            metadata=None,
            pages=[FakePage("hidden")],
        )
        with fake_pypdf(reader), self.assertRaises(PdfExtractionError) as raised:
            extract_pdf(b"%PDF-demo", "protected.pdf")

        self.assertEqual(raised.exception.code, "encrypted_pdf")
        self.assertIn("加密", str(raised.exception))

    def test_identifies_scanned_pdf_without_digital_text(self):
        reader = SimpleNamespace(
            is_encrypted=False,
            metadata=None,
            pages=[FakePage(""), FakePage("  ")],
        )
        with fake_pypdf(reader), self.assertRaises(PdfExtractionError) as raised:
            extract_pdf(b"%PDF-demo", "scan.pdf")

        self.assertEqual(raised.exception.code, "scanned_pdf")
        self.assertIn("SCIPILOT_PDF_OCR_ENABLED", str(raised.exception))

    def test_identifies_unreadable_page_content(self):
        reader = SimpleNamespace(
            is_encrypted=False,
            metadata=None,
            pages=[FakePage(error=ValueError("broken stream"))],
        )
        with fake_pypdf(reader), self.assertRaises(PdfExtractionError) as raised:
            extract_pdf(b"%PDF-demo", "broken.pdf")

        self.assertEqual(raised.exception.code, "unreadable_pdf")

    @patch("services.pdf_extraction_service._ocr_page_from_pdf")
    def test_uses_bounded_ocr_and_preserves_page_coordinates(self, ocr_page):
        reader = SimpleNamespace(
            is_encrypted=False,
            metadata=None,
            pages=[FakePage("")],
        )
        ocr_page.return_value = {
            "text": "scanned evidence",
            "source": "ocr",
            "coordinate_space": "normalized-top-left",
            "width": 1200,
            "height": 1600,
            "rotation": 0,
            "segments": [
                {
                    "text": "scanned evidence",
                    "bbox": [0.1, 0.2, 0.8, 0.3],
                    "confidence": 91.5,
                }
            ],
        }
        with fake_pypdf(reader):
            result = extract_pdf(b"%PDF-scan", "scan.pdf", ocr_enabled=True)

        self.assertEqual(result["extraction_method"], "ocr")
        self.assertEqual(result["ocr_page_count"], 1)
        self.assertEqual(result["pages"][0]["source"], "ocr")
        self.assertIn("第 1 页 · OCR", result["prompt_text"])
        self.assertEqual(result["page_evidence"][0]["segments"][0]["bbox"], [0.1, 0.2, 0.8, 0.3])

    @patch("services.pdf_extraction_service._ocr_page_from_pdf")
    def test_combines_digital_and_scanned_pages_in_source_order(self, ocr_page):
        reader = SimpleNamespace(
            is_encrypted=False,
            metadata=None,
            pages=[FakePage("digital text"), FakePage("")],
        )
        ocr_page.return_value = {
            "text": "ocr text",
            "source": "ocr",
            "coordinate_space": "normalized-top-left",
            "width": 1200,
            "height": 1600,
            "rotation": 0,
            "segments": [],
        }
        with fake_pypdf(reader):
            result = extract_pdf(b"%PDF-hybrid", "hybrid.pdf", ocr_enabled=True)

        self.assertEqual(result["extraction_method"], "hybrid")
        self.assertEqual([page["page"] for page in result["pages"]], [1, 2])
        self.assertEqual([page["source"] for page in result["pages"]], ["digital", "ocr"])

    @patch("services.pdf_extraction_service._ocr_page_from_pdf")
    def test_counts_sources_only_after_max_chars_page_truncation(self, ocr_page):
        ocr_page.return_value = {
            "text": "ocr text",
            "source": "ocr",
            "coordinate_space": "normalized-top-left",
            "width": 1200,
            "height": 1600,
            "rotation": 0,
            "segments": [],
        }
        digital_first = SimpleNamespace(
            is_encrypted=False,
            metadata=None,
            pages=[FakePage("digital text"), FakePage("")],
        )
        with fake_pypdf(digital_first):
            digital_result = extract_pdf(
                b"%PDF-truncated-digital",
                "digital-first.pdf",
                max_chars=4,
                ocr_enabled=True,
            )

        self.assertEqual(digital_result["digital_page_count"], 1)
        self.assertEqual(digital_result["ocr_page_count"], 0)
        self.assertEqual(digital_result["extraction_method"], "digital")

        ocr_first = SimpleNamespace(
            is_encrypted=False,
            metadata=None,
            pages=[FakePage(""), FakePage("digital text")],
        )
        with fake_pypdf(ocr_first):
            ocr_result = extract_pdf(
                b"%PDF-truncated-ocr",
                "ocr-first.pdf",
                max_chars=4,
                ocr_enabled=True,
            )

        self.assertEqual(ocr_result["digital_page_count"], 0)
        self.assertEqual(ocr_result["ocr_page_count"], 1)
        self.assertEqual(ocr_result["extraction_method"], "ocr")

    @patch("services.pdf_extraction_service._ocr_page_from_pdf")
    def test_extraction_warnings_count_each_failed_page_once(self, ocr_page):
        reader = SimpleNamespace(
            is_encrypted=False,
            metadata=None,
            pages=[
                FakePage("digital text"),
                FakePage(error=ValueError("broken stream")),
            ],
        )
        ocr_page.side_effect = RuntimeError("ocr failed")

        with fake_pypdf(reader):
            result = extract_pdf(
                b"%PDF-warning",
                "warning.pdf",
                ocr_enabled=True,
            )

        self.assertEqual(result["extraction_warnings"], 1)

    @patch("services.pdf_extraction_service._ocr_page_from_pdf")
    def test_reports_missing_local_ocr_runtime(self, ocr_page):
        reader = SimpleNamespace(
            is_encrypted=False,
            metadata=None,
            pages=[FakePage("")],
        )
        ocr_page.side_effect = _OcrUnavailableError("OCR 运行环境缺少：tesseract")
        with fake_pypdf(reader), self.assertRaises(PdfExtractionError) as raised:
            extract_pdf(b"%PDF-scan", "scan.pdf", ocr_enabled=True)

        self.assertEqual(raised.exception.code, "ocr_unavailable")
        self.assertIn("tesseract", str(raised.exception))

    def test_rejects_unsafe_ocr_language_configuration(self):
        reader = SimpleNamespace(
            is_encrypted=False,
            metadata=None,
            pages=[FakePage("")],
        )
        with (
            fake_pypdf(reader),
            patch.dict("os.environ", {"SCIPILOT_PDF_OCR_LANGUAGES": "eng;whoami"}),
            self.assertRaises(PdfExtractionError) as raised,
        ):
            extract_pdf(b"%PDF-scan", "scan.pdf", ocr_enabled=True)

        self.assertEqual(raised.exception.code, "invalid_ocr_config")


class PdfUploadThreadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_pdf_extraction_is_offloaded_from_event_loop(self):
        expected = {"text": "bounded"}
        with patch.object(
            routes.asyncio,
            "to_thread",
            new=AsyncMock(return_value=expected),
        ) as to_thread:
            result = await routes._extract_pdf_metadata_nonblocking(
                b"%PDF-demo",
                "paper",
            )

        self.assertEqual(result, expected)
        to_thread.assert_awaited_once_with(
            routes._extract_pdf_metadata,
            b"%PDF-demo",
            "paper",
        )


if __name__ == "__main__":
    unittest.main()
