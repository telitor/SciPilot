from __future__ import annotations

from typing import Any

from services.xunfei_knowledge_base_service import (
    build_retrieval_queries,
    rerank_retrieval_candidates,
)


def _citation(row: list[Any]) -> dict[str, Any]:
    chunk_id, title, excerpt, score = row
    document_id, _, chunk_index = str(chunk_id).partition(":")
    return {
        "document_id": document_id,
        "chunk_id": str(chunk_id),
        "chunk_index": int(chunk_index or 0),
        "title": str(title),
        "excerpt": str(excerpt),
        "score": float(score),
    }


def evaluate_rag_retrieval_cases(
    cases: list[dict[str, Any]],
    *,
    top_k: int = 3,
) -> dict[str, Any]:
    """Run deterministic retrieval evaluation without external model calls."""

    results: list[dict[str, Any]] = []
    reciprocal_ranks: list[float] = []
    recalled = 0

    for case in cases:
        case_input = case.get("input") or {}
        expected = case.get("expected") or {}
        query = str(case_input.get("query") or "").strip()
        relevant_ids = {str(item) for item in expected.get("relevant_ids") or []}
        if not query or not relevant_ids:
            results.append(
                {
                    "case_id": str(case.get("id") or ""),
                    "status": "failed",
                    "rank": None,
                    "metrics": {"recall_at_k": 0.0, "reciprocal_rank": 0.0},
                    "diagnostic": "评测用例缺少 query 或 relevant_ids",
                }
            )
            reciprocal_ranks.append(0.0)
            continue

        queries = build_retrieval_queries(query, max_queries=2)
        rewritten_query = queries[1] if len(queries) > 1 else queries[0]
        ranked, candidate_count = rerank_retrieval_candidates(
            [
                (queries[0], [_citation(row) for row in case_input.get("original") or []]),
                (rewritten_query, [_citation(row) for row in case_input.get("rewritten") or []]),
            ],
            top_n=top_k,
        )
        ranked_ids = [str(item.get("chunk_id") or "") for item in ranked]
        first_rank = next(
            (
                index
                for index, chunk_id in enumerate(ranked_ids, start=1)
                if chunk_id in relevant_ids
            ),
            None,
        )
        passed = first_rank is not None
        recalled += int(passed)
        reciprocal_rank = 1.0 / first_rank if first_rank else 0.0
        reciprocal_ranks.append(reciprocal_rank)
        results.append(
            {
                "case_id": str(case.get("id") or ""),
                "status": "passed" if passed else "failed",
                "rank": first_rank,
                "metrics": {
                    "recall_at_k": 1.0 if passed else 0.0,
                    "reciprocal_rank": round(reciprocal_rank, 6),
                    "candidate_count": candidate_count,
                },
                "diagnostic": (
                    f"命中排名 {first_rank}" if passed else f"前 {top_k} 条未命中相关片段"
                ),
            }
        )

    case_count = len(cases)
    passed_count = sum(item["status"] == "passed" for item in results)
    metrics = {
        f"recall_at_{top_k}": round(recalled / case_count, 6) if case_count else 0.0,
        "mrr": (
            round(sum(reciprocal_ranks) / case_count, 6) if case_count else 0.0
        ),
        "pass_rate": round(passed_count / case_count, 6) if case_count else 0.0,
    }
    return {
        "case_count": case_count,
        "passed_count": passed_count,
        "failed_count": case_count - passed_count,
        "metrics": metrics,
        "results": results,
    }
