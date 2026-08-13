import unittest

from services.rag_grounding_service import validate_citation_grounding


class RagGroundingServiceTests(unittest.TestCase):
    def setUp(self):
        self.citations = [
            {"index": 1, "title": "Transformer", "excerpt": "自注意力机制用于建模长距离依赖。"},
            {"index": 2, "title": "Results", "excerpt": "模型在测试集上的准确率达到 92%。"},
        ]

    def test_supported_answer_has_valid_coverage_and_overlap(self):
        result = validate_citation_grounding(
            "该方法使用自注意力机制建模长距离依赖 [1]。\n测试准确率达到 92% [2]。",
            self.citations,
        )
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["valid_indices"], [1, 2])

    def test_invalid_reference_is_never_marked_supported(self):
        result = validate_citation_grounding("结论来自未知证据 [9]。", self.citations)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["invalid_indices"], [9])

    def test_retrieved_evidence_without_reference_is_unsupported(self):
        result = validate_citation_grounding("这是一个没有标注来源的结论。", self.citations)
        self.assertEqual(result["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
