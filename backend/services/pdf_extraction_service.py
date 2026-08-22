"""Bounded PDF text, OCR and page-layout evidence extraction."""

from __future__ import annotations

import csv
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
from collections import defaultdict
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any


_TRUE_VALUES = {"1", "true", "yes", "on"}
_OCR_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")
_MAX_LAYOUT_SEGMENTS_PER_PAGE = 300
_MAX_OCR_LONG_EDGE_PIXELS = 4096
_MAX_OCR_TOTAL_PIXELS = 12_000_000
_MAX_OCR_PNG_BYTES = 64 * 1024 * 1024


class PdfExtractionError(ValueError):
    """A permanent PDF input error that is safe to show to the user."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _OcrUnavailableError(RuntimeError):
    """Raised when the configured local OCR runtime is incomplete."""


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _clamp(value: float) -> float:
    if not math.isfinite(value):
        return 1.0 if value > 0 else 0.0
    return round(max(0.0, min(1.0, value)), 5)


def _page_geometry(page: Any) -> tuple[float, float, int]:
    try:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
    except Exception:
        width, height = 612.0, 792.0
    try:
        rotation = int(getattr(page, "rotation", 0) or 0) % 360
    except Exception:
        rotation = 0
    return max(width, 1.0), max(height, 1.0), rotation


def _affine_values(matrix: Any) -> tuple[float, float, float, float, float, float]:
    """Return a finite PDF affine matrix, falling back to the identity."""

    try:
        values = tuple(float(matrix[index]) for index in range(6))
    except (IndexError, KeyError, TypeError, ValueError):
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not all(math.isfinite(value) for value in values):
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    return values


def _combined_text_matrix(
    cm: Any,
    tm: Any,
) -> tuple[float, float, float, float, float, float]:
    """Compose the text matrix with the current transformation matrix.

    PDF matrices use ``[a, b, c, d, e, f]`` and row-vector application.
    Text coordinates therefore pass through ``tm`` first and then ``cm``.
    Keeping the full linear component is important for scaled, mirrored and
    rotated text; using only the transformed origin understates its bounds.
    """

    ta, tb, tc, td, te, tf = _affine_values(tm)
    ca, cb, cc, cd, ce, cf = _affine_values(cm)
    return (
        ta * ca + tb * cc,
        ta * cb + tb * cd,
        tc * ca + td * cc,
        tc * cb + td * cd,
        te * ca + tf * cc + ce,
        te * cb + tf * cd + cf,
    )


def _transformed_text_bbox(
    cm: Any,
    tm: Any,
    *,
    font_size: float,
    estimated_width: float,
    page_width: float,
    page_height: float,
) -> list[float]:
    """Return a normalized top-left bbox enclosing a transformed text span."""

    a, b, c, d, e, f = _combined_text_matrix(cm, tm)
    # Include a small descender below the baseline, matching the prior 1.25x
    # line-height estimate while allowing the full affine transform to act.
    local_corners = (
        (0.0, -font_size * 0.25),
        (estimated_width, -font_size * 0.25),
        (0.0, font_size),
        (estimated_width, font_size),
    )
    transformed = [
        (x * a + y * c + e, x * b + y * d + f)
        for x, y in local_corners
    ]
    x_values = [point[0] for point in transformed]
    y_values = [point[1] for point in transformed]
    left = _clamp(min(x_values) / page_width)
    right = _clamp(max(x_values) / page_width)
    top = _clamp((page_height - max(y_values)) / page_height)
    bottom = _clamp((page_height - min(y_values)) / page_height)
    # min/max above already normalizes mirrored and rotated matrices; sorting
    # after clamping also protects against extreme out-of-page coordinates.
    return [min(left, right), min(top, bottom), max(left, right), max(top, bottom)]


def _extract_digital_page(page: Any) -> dict[str, Any]:
    """Extract text plus lightweight normalized spans from a digital PDF page."""

    width, height, rotation = _page_geometry(page)
    segments: list[dict[str, Any]] = []

    def visitor(
        text: str,
        cm: Any,
        tm: Any,
        _font: Any,
        font_size: Any,
    ) -> None:
        if len(segments) >= _MAX_LAYOUT_SEGMENTS_PER_PAGE:
            return
        clean_text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not clean_text:
            return
        try:
            size = max(1.0, min(float(font_size or 10.0), 96.0))
        except (TypeError, ValueError):
            size = 10.0
        estimated_width = max(size * 0.45, size * 0.52 * len(clean_text))
        segments.append(
            {
                "text": clean_text[:500],
                "bbox": _transformed_text_bbox(
                    cm,
                    tm,
                    font_size=size,
                    estimated_width=estimated_width,
                    page_width=width,
                    page_height=height,
                ),
                "confidence": None,
            }
        )

    try:
        text = page.extract_text(visitor_text=visitor)
    except TypeError:
        # Test doubles and older pypdf releases may not expose visitor_text.
        text = page.extract_text()
    return {
        "text": str(text or "").strip(),
        "source": "digital",
        "coordinate_space": "normalized-top-left",
        "width": round(width, 3),
        "height": round(height, 3),
        "rotation": rotation,
        "segments": segments,
    }


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("OCR 页面渲染结果不是有效 PNG")
    width, height = struct.unpack(">II", header[16:24])
    if width < 1 or height < 1:
        raise RuntimeError("OCR 页面渲染尺寸无效")
    return width, height


def _bounded_ocr_long_edge(
    page_width_points: float,
    page_height_points: float,
    dpi: int,
) -> int:
    """Return a Poppler scale bound that caps both edge length and pixels."""

    width_pixels = page_width_points * dpi / 72.0
    height_pixels = page_height_points * dpi / 72.0
    if (
        not math.isfinite(width_pixels)
        or not math.isfinite(height_pixels)
        or width_pixels <= 0
        or height_pixels <= 0
    ):
        raise RuntimeError("PDF 页面尺寸无效，无法安全执行 OCR")
    long_edge = max(width_pixels, height_pixels)
    edge_scale = min(1.0, _MAX_OCR_LONG_EDGE_PIXELS / long_edge)
    bounded_width = width_pixels * edge_scale
    bounded_height = height_pixels * edge_scale
    total_pixels = bounded_width * bounded_height
    if total_pixels > _MAX_OCR_TOTAL_PIXELS:
        pixel_scale = math.sqrt(_MAX_OCR_TOTAL_PIXELS / total_pixels)
        bounded_width *= pixel_scale
        bounded_height *= pixel_scale
    return max(1, min(_MAX_OCR_LONG_EDGE_PIXELS, math.floor(max(bounded_width, bounded_height))))


def _validated_ocr_png_dimensions(path: Path) -> tuple[int, int]:
    try:
        size_bytes = path.stat().st_size
    except OSError as exc:
        raise RuntimeError("OCR 页面渲染结果无法读取") from exc
    if size_bytes > _MAX_OCR_PNG_BYTES:
        raise RuntimeError("OCR 页面渲染结果超过安全大小限制")
    width, height = _png_dimensions(path)
    if (
        width > _MAX_OCR_LONG_EDGE_PIXELS
        or height > _MAX_OCR_LONG_EDGE_PIXELS
        or width * height > _MAX_OCR_TOTAL_PIXELS
    ):
        raise RuntimeError("OCR 页面渲染尺寸超过安全像素限制")
    return width, height


def _parse_tesseract_tsv(
    output: str,
    *,
    image_width: int,
    image_height: int,
    minimum_confidence: int,
) -> tuple[str, list[dict[str, Any]]]:
    lines: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    reader = csv.DictReader(StringIO(output), delimiter="\t")
    required = {"block_num", "par_num", "line_num", "left", "top", "width", "height", "conf", "text"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise RuntimeError("Tesseract 没有返回可解析的 TSV 结果")

    for row in reader:
        word = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
        if not word:
            continue
        try:
            confidence = float(row.get("conf") or -1)
            left = int(row.get("left") or 0)
            top = int(row.get("top") or 0)
            word_width = int(row.get("width") or 0)
            word_height = int(row.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if confidence < minimum_confidence or word_width < 1 or word_height < 1:
            continue
        key = (
            str(row.get("block_num") or "0"),
            str(row.get("par_num") or "0"),
            str(row.get("line_num") or "0"),
        )
        lines[key].append(
            {
                "text": word,
                "confidence": confidence,
                "left": left,
                "top": top,
                "right": left + word_width,
                "bottom": top + word_height,
            }
        )

    text_lines: list[str] = []
    segments: list[dict[str, Any]] = []
    for words in lines.values():
        if not words or len(segments) >= _MAX_LAYOUT_SEGMENTS_PER_PAGE:
            continue
        text = " ".join(word["text"] for word in words).strip()
        if not text:
            continue
        left = min(word["left"] for word in words)
        top = min(word["top"] for word in words)
        right = max(word["right"] for word in words)
        bottom = max(word["bottom"] for word in words)
        confidence = sum(word["confidence"] for word in words) / len(words)
        text_lines.append(text)
        segments.append(
            {
                "text": text[:500],
                "bbox": [
                    _clamp(left / image_width),
                    _clamp(top / image_height),
                    _clamp(right / image_width),
                    _clamp(bottom / image_height),
                ],
                "confidence": round(confidence, 2),
            }
        )
    return "\n".join(text_lines).strip(), segments


def _ocr_page_from_pdf(
    content: bytes,
    page_number: int,
    *,
    dpi: int,
    page_width_points: float,
    page_height_points: float,
    languages: str,
    timeout_seconds: int,
    minimum_confidence: int,
) -> dict[str, Any]:
    """Render and OCR one page with fixed, non-shell command arguments."""

    pdftoppm = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    missing = [name for name, value in (("pdftoppm", pdftoppm), ("tesseract", tesseract)) if not value]
    if missing:
        raise _OcrUnavailableError("OCR 运行环境缺少：" + "、".join(missing))
    scale_to = _bounded_ocr_long_edge(
        page_width_points,
        page_height_points,
        dpi,
    )

    with tempfile.TemporaryDirectory(prefix="scipilot-pdf-ocr-") as temp_dir:
        temp_path = Path(temp_dir)
        pdf_path = temp_path / "input.pdf"
        output_prefix = temp_path / f"page-{page_number}"
        pdf_path.write_bytes(content)
        render = subprocess.run(
            [
                str(pdftoppm),
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-singlefile",
                "-r",
                str(dpi),
                "-scale-to",
                str(scale_to),
                "-png",
                str(pdf_path),
                str(output_prefix),
            ],
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
        if render.returncode != 0:
            raise RuntimeError("Poppler 无法渲染待 OCR 页面")
        image_path = output_prefix.with_suffix(".png")
        if not image_path.is_file():
            candidates = sorted(temp_path.glob(f"page-{page_number}*.png"))
            if not candidates:
                raise RuntimeError("Poppler 未生成待 OCR 页面")
            image_path = candidates[0]
        image_width, image_height = _validated_ocr_png_dimensions(image_path)
        recognized = subprocess.run(
            [
                str(tesseract),
                str(image_path),
                "stdout",
                "-l",
                languages,
                "--psm",
                "3",
                "tsv",
            ],
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if recognized.returncode != 0:
            raise RuntimeError("Tesseract 无法识别待 OCR 页面")
        text, segments = _parse_tesseract_tsv(
            recognized.stdout,
            image_width=image_width,
            image_height=image_height,
            minimum_confidence=minimum_confidence,
        )
        return {
            "text": text,
            "source": "ocr",
            "coordinate_space": "normalized-top-left",
            "width": image_width,
            "height": image_height,
            "rotation": 0,
            "segments": segments,
        }


def _bounded_segments(segments: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    bounded: list[dict[str, Any]] = []
    remaining = max(0, max_chars)
    for segment in segments[:_MAX_LAYOUT_SEGMENTS_PER_PAGE]:
        if remaining <= 0:
            break
        text = str(segment.get("text") or "")[:remaining]
        if not text:
            continue
        bounded.append({**segment, "text": text})
        remaining -= len(text)
    return bounded


def extract_pdf(
    content: bytes,
    filename: str,
    *,
    max_pages: int = 5,
    max_chars: int = 10_000,
    ocr_enabled: bool | None = None,
) -> dict[str, Any]:
    """Extract bounded text and normalized page evidence, using OCR when enabled."""

    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content), strict=False)
    except Exception as exc:
        raise PdfExtractionError(
            "damaged_pdf",
            "PDF 文件无法读取，可能已损坏或格式不完整。",
        ) from exc

    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception as exc:
            raise PdfExtractionError(
                "encrypted_pdf",
                "PDF 已加密，请先移除密码后重新上传。",
            ) from exc
        if not unlocked:
            raise PdfExtractionError(
                "encrypted_pdf",
                "PDF 已加密，请先移除密码后重新上传。",
            )

    try:
        page_count = len(reader.pages)
    except Exception as exc:
        raise PdfExtractionError(
            "damaged_pdf",
            "PDF 页面结构无法读取，文件可能已损坏。",
        ) from exc
    if page_count < 1:
        raise PdfExtractionError("empty_pdf", "PDF 不包含可解析页面。")

    try:
        metadata = reader.metadata or {}
    except Exception:
        metadata = {}
    fallback_title = Path(filename).stem or "paper"
    title = str(getattr(metadata, "title", "") or fallback_title).strip()
    author_text = str(getattr(metadata, "author", "") or "").strip()
    authors = [
        part.strip()
        for part in re.split(r"[,;，；]", author_text)
        if part.strip()
    ]

    processed_pages = min(page_count, max(1, max_pages))
    page_results: dict[int, dict[str, Any]] = {}
    page_dimensions: dict[int, tuple[float, float]] = {}
    blank_pages: list[int] = []
    extraction_error_pages: set[int] = set()
    for page_index in range(processed_pages):
        page_number = page_index + 1
        page_dimensions[page_number] = (612.0, 792.0)
        try:
            page = reader.pages[page_index]
            page_width, page_height, _rotation = _page_geometry(page)
            page_dimensions[page_number] = (page_width, page_height)
            result = _extract_digital_page(page)
        except Exception:
            extraction_error_pages.add(page_number)
            blank_pages.append(page_number)
            continue
        if result["text"]:
            page_results[page_number] = result
        else:
            blank_pages.append(page_number)

    use_ocr = _env_bool("SCIPILOT_PDF_OCR_ENABLED") if ocr_enabled is None else bool(ocr_enabled)
    ocr_failure_pages: set[int] = set()
    ocr_unavailable: _OcrUnavailableError | None = None
    if use_ocr and blank_pages:
        languages = str(os.getenv("SCIPILOT_PDF_OCR_LANGUAGES", "eng")).strip() or "eng"
        if not _OCR_LANGUAGE_PATTERN.fullmatch(languages):
            raise PdfExtractionError(
                "invalid_ocr_config",
                "OCR 语言配置无效，只允许字母、数字以及 +._-。",
            )
        dpi = _bounded_env_int("SCIPILOT_PDF_OCR_DPI", 180, 96, 300)
        timeout_seconds = _bounded_env_int("SCIPILOT_PDF_OCR_TIMEOUT_SECONDS", 25, 5, 90)
        minimum_confidence = _bounded_env_int("SCIPILOT_PDF_OCR_MIN_CONFIDENCE", 35, 0, 95)
        for page_number in blank_pages:
            page_width, page_height = page_dimensions[page_number]
            try:
                result = _ocr_page_from_pdf(
                    content,
                    page_number,
                    dpi=dpi,
                    page_width_points=page_width,
                    page_height_points=page_height,
                    languages=languages,
                    timeout_seconds=timeout_seconds,
                    minimum_confidence=minimum_confidence,
                )
            except _OcrUnavailableError as exc:
                ocr_unavailable = exc
                break
            except (RuntimeError, subprocess.SubprocessError, OSError):
                ocr_failure_pages.add(page_number)
                continue
            if result["text"]:
                page_results[page_number] = result
            else:
                ocr_failure_pages.add(page_number)

    if not page_results:
        if ocr_unavailable is not None:
            raise PdfExtractionError(
                "ocr_unavailable",
                f"已启用扫描版 PDF OCR，但{ocr_unavailable}。请安装 Poppler 和 Tesseract，或关闭 OCR。",
            )
        if use_ocr and (ocr_failure_pages or blank_pages):
            raise PdfExtractionError(
                "ocr_failed",
                "扫描版 PDF 的 OCR 未识别出可靠文本，请检查清晰度、方向或 OCR 语言配置。",
            )
        if extraction_error_pages:
            raise PdfExtractionError(
                "unreadable_pdf",
                "PDF 页面文本解析失败，文件可能已损坏或使用了不受支持的编码。",
            )
        raise PdfExtractionError(
            "scanned_pdf",
            "无法从 PDF 中提取数字文本，可能是扫描版 PDF；请启用 SCIPILOT_PDF_OCR_ENABLED 后重试。",
        )

    pages: list[dict[str, Any]] = []
    page_evidence: list[dict[str, Any]] = []
    remaining = max(1, max_chars)
    for page_number in sorted(page_results):
        if remaining <= 0:
            break
        result = page_results[page_number]
        bounded_text = str(result["text"])[:remaining]
        if not bounded_text:
            continue
        pages.append(
            {
                "page": page_number,
                "text": bounded_text,
                "source": result["source"],
            }
        )
        page_evidence.append(
            {
                "page": page_number,
                "source": result["source"],
                "coordinate_space": result["coordinate_space"],
                "width": result["width"],
                "height": result["height"],
                "rotation": result["rotation"],
                "segments": _bounded_segments(result["segments"], len(bounded_text)),
            }
        )
        remaining -= len(bounded_text)

    plain_text = "\n\n".join(page["text"] for page in pages)
    prompt_text = "\n\n".join(
        f"【第 {page['page']} 页{' · OCR' if page['source'] == 'ocr' else ''}】\n{page['text']}"
        for page in pages
    )
    digital_page_count = sum(page["source"] == "digital" for page in pages)
    ocr_page_count = sum(page["source"] == "ocr" for page in pages)
    if digital_page_count and ocr_page_count:
        extraction_method = "hybrid"
    elif ocr_page_count:
        extraction_method = "ocr"
    else:
        extraction_method = "digital"
    unresolved_pages = set(range(1, processed_pages + 1)).difference(page_results)
    warning_pages = extraction_error_pages | ocr_failure_pages | unresolved_pages
    return {
        "title": title or fallback_title,
        "authors": authors or ["Unknown"],
        "text": plain_text,
        "prompt_text": prompt_text,
        "pages": pages,
        "page_evidence": page_evidence,
        "page_count": page_count,
        "processed_page_count": processed_pages,
        "extracted_page_count": len(pages),
        "digital_page_count": digital_page_count,
        "ocr_page_count": ocr_page_count,
        "extraction_method": extraction_method,
        "extraction_warnings": len(warning_pages),
    }
