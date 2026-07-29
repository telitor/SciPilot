import hashlib
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from openai import OpenAI


SUPPORTED_KB_SUFFIXES = {".pdf", ".txt", ".md", ".markdown"}


def safe_filename(filename: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name).strip(".-")
    return value[:160] or "knowledge-document"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def extract_knowledge_text(content: bytes, filename: str) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_KB_SUFFIXES:
        raise ValueError("仅支持 PDF、TXT、MD 和 Markdown 文件")

    if suffix == ".pdf":
        if not content.startswith(b"%PDF"):
            raise ValueError("文件扩展名为 PDF，但内容不是有效 PDF")
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        metadata = reader.metadata or {}
        pages: list[str] = []
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(text)
        title = str(getattr(metadata, "title", "") or Path(filename).stem).strip()
        return {
            "title": title or Path(filename).stem,
            "text": "\n\n".join(pages),
            "page_count": len(reader.pages),
            "source_type": "pdf",
        }

    decoded: str | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            decoded = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ValueError("文本文件编码无法识别，请转换为 UTF-8 后重试")
    return {
        "title": Path(filename).stem,
        "text": decoded,
        "page_count": None,
        "source_type": "markdown" if suffix in {".md", ".markdown"} else "text",
    }


def chunk_knowledge_text(
    text: str,
    *,
    target_chars: int = 1200,
    overlap_chars: int = 180,
) -> list[str]:
    normalized = re.sub(r"\r\n?", "\n", text)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", normalized) if item.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > target_chars * 2:
            pieces = [
                paragraph[index : index + target_chars]
                for index in range(0, len(paragraph), target_chars)
            ]
        else:
            pieces = [paragraph]
        for piece in pieces:
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            if current and len(candidate) > target_chars:
                chunks.append(current)
                overlap = current[-overlap_chars:] if overlap_chars else ""
                current = f"{overlap}\n\n{piece}".strip()
            else:
                current = candidate
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


def estimate_tokens(text: str) -> int:
    # A conservative language-agnostic estimate for storage/usage reporting.
    latin_words = len(re.findall(r"[A-Za-z0-9_]+", text))
    cjk_chars = len(re.findall(r"[\u3400-\u9fff]", text))
    other_chars = max(0, len(text) - latin_words - cjk_chars)
    return max(1, latin_words + cjk_chars + other_chars // 4)


def create_embedding(text: str) -> list[float] | None:
    api_key = os.getenv("EMBEDDING_API_KEY")
    if not api_key:
        return None
    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("EMBEDDING_BASE_URL") or None,
    )
    response = client.embeddings.create(
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        input=text,
    )
    vector = response.data[0].embedding
    if len(vector) != 1536:
        raise RuntimeError(
            f"Embedding 维度为 {len(vector)}，数据库要求 1536；请更换模型或调整迁移"
        )
    return vector
