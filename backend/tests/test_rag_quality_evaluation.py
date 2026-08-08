import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import xunfei_knowledge_base_service as service


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "rag_quality_cases.json"


def _citation(row):
    chunk_id, title, excerpt, score = row
    document_id, chunk_index = chunk_id.split(":", 1)
    return {
        "document_id": document_id,
        "chunk_id": chunk_id,
        "chunk_index": int(chunk_index),
        "title": title,
        "excerpt": excerpt,
        "score": score,
    }


class RagQualityEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_query_rewrite_preserves_domain_terms(self):
        with patch.dict(
            os.environ,
            {
                "XFYUN_KB_QUERY_REWRITE_ENABLED": "true",
                "XFYUN_KB_MAX_QUERY_VARIANTS": "2",
            },
            clear=True,
        ):
            plans = [
                service.build_retrieval_queries(case["query"])
                for case in self.cases
            ]

        self.assertTrue(all(1 <= len(plan) <= 2 for plan in plans))
        self.assertIn("软件缺陷预测", plans[0][-1])
        self.assertIn("算法", plans[1][-1])
        self.assertIn("局限性", plans[2][-1])

    def test_offline_ranking_meets_recall_and_mrr_floor(self):
        reciprocal_ranks = []
        recalled = 0
        for case in self.cases:
            queries = service.build_retrieval_queries(case["query"], max_queries=2)
            rewritten_query = queries[1] if len(queries) > 1 else queries[0]
            ranked, candidate_count = service.rerank_retrieval_candidates(
                [
                    (queries[0], [_citation(row) for row in case["original"]]),
                    (rewritten_query, [_citation(row) for row in case["rewritten"]]),
                ],
                top_n=3,
            )
            ranked_ids = [item["chunk_id"] for item in ranked]
            relevant = set(case["relevant_ids"])
            first_rank = next(
                (index for index, chunk_id in enumerate(ranked_ids, start=1) if chunk_id in relevant),
                None,
            )
            recalled += int(first_rank is not None)
            reciprocal_ranks.append(1.0 / first_rank if first_rank else 0.0)
            self.assertGreaterEqual(candidate_count, len(ranked))

        recall_at_3 = recalled / len(self.cases)
        mean_reciprocal_rank = sum(reciprocal_ranks) / len(reciprocal_ranks)
        self.assertGreaterEqual(recall_at_3, 1.0)
        self.assertGreaterEqual(mean_reciprocal_rank, 0.9)


if __name__ == "__main__":
    unittest.main()
