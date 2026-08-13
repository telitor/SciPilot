import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.pdf_extraction_service import PdfExtractionError, extract_pdf


class FakePage:
    def __init__(self, text: str = "", error: Exception | None = None):
        self.text = text
        self.error = error

    def extract_text(self):
        if self.error:
            raise self.error
        return self.text


def fake_pypdf(reader):
    return patch.dict(
        sys.modules,
        {"pypdf": SimpleNamespace(PdfReader=lambda *_args, **_kwargs: reader)},
    )


class PdfExtractionServiceTests(unittest.TestCase):
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
        self.assertIn("OCR", str(raised.exception))

    def test_identifies_unreadable_page_content(self):
        reader = SimpleNamespace(
            is_encrypted=False,
            metadata=None,
            pages=[FakePage(error=ValueError("broken stream"))],
        )
        with fake_pypdf(reader), self.assertRaises(PdfExtractionError) as raised:
            extract_pdf(b"%PDF-demo", "broken.pdf")

        self.assertEqual(raised.exception.code, "unreadable_pdf")


if __name__ == "__main__":
    unittest.main()
