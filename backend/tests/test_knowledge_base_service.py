import unittest

from services.knowledge_base_service import (
    chunk_knowledge_text,
    estimate_tokens,
    extract_knowledge_text,
    safe_filename,
    sha256_bytes,
)


class KnowledgeBaseServiceTests(unittest.TestCase):
    def test_text_ingestion_and_chunking(self):
        extracted = extract_knowledge_text(
            "第一段科研笔记。\n\n第二段包含实验结论。".encode("utf-8"),
            "notes.md",
        )
        self.assertEqual(extracted["source_type"], "markdown")
        chunks = chunk_knowledge_text(
            extracted["text"], target_chars=12, overlap_chars=3
        )
        self.assertGreaterEqual(len(chunks), 2)
        self.assertIn("科研", "".join(chunks))

    def test_rejects_unsupported_extension(self):
        with self.assertRaises(ValueError):
            extract_knowledge_text(b"data", "notes.exe")

    def test_helpers_are_deterministic(self):
        self.assertEqual(
            sha256_bytes(b"SciPilot"),
            "2b1e916b4781feebecd740b22cd6c228433163013796e791d3a8876ef56fd0b6",
        )
        self.assertEqual(safe_filename("../../paper 01.md"), "paper-01.md")
        self.assertGreater(estimate_tokens("知识库 knowledge base"), 0)


if __name__ == "__main__":
    unittest.main()
