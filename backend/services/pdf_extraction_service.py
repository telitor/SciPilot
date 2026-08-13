"""Bounded, page-aware text extraction for uploaded research papers."""

import re
from io import BytesIO
from pathlib import Path
from typing import Any


class PdfExtractionError(ValueError):
    """A permanent PDF input error that is safe to show to the user."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def extract_pdf(
    content: bytes,
    filename: str,
    *,
    max_pages: int = 5,
    max_chars: int = 10_000,
) -> dict[str, Any]:
    """Extract bounded digital text while retaining one-based source pages."""

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

    pages: list[dict[str, Any]] = []
    remaining = max(1, max_chars)
    extraction_errors = 0
    for page_index in range(min(page_count, max(1, max_pages))):
        if remaining <= 0:
            break
        try:
            page_text = str(reader.pages[page_index].extract_text() or "").strip()
        except Exception:
            extraction_errors += 1
            continue
        if not page_text:
            continue
        bounded_text = page_text[:remaining]
        pages.append({"page": page_index + 1, "text": bounded_text})
        remaining -= len(bounded_text)

    if not pages:
        if extraction_errors:
            raise PdfExtractionError(
                "unreadable_pdf",
                "PDF 页面文本解析失败，文件可能已损坏或使用了不受支持的编码。",
            )
        raise PdfExtractionError(
            "scanned_pdf",
            "无法从 PDF 中提取文本，可能是扫描版 PDF；当前版本暂不支持 OCR。",
        )

    plain_text = "\n\n".join(page["text"] for page in pages)
    prompt_text = "\n\n".join(
        f"【第 {page['page']} 页】\n{page['text']}" for page in pages
    )
    return {
        "title": title or fallback_title,
        "authors": authors or ["Unknown"],
        "text": plain_text,
        "prompt_text": prompt_text,
        "pages": pages,
        "page_count": page_count,
        "extracted_page_count": len(pages),
        "extraction_warnings": extraction_errors,
    }
