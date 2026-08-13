"""Deterministic citation validation for retrieved research evidence."""

import re
from typing import Any


CITATION_PATTERN = re.compile(r"\[(\d{1,3})\]")
LATIN_TERM_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.+-]{1,}", re.IGNORECASE)
CHINESE_SEQUENCE_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}")


def _terms(value: str) -> set[str]:
    normalized = value.lower()
    terms = {match.group(0) for match in LATIN_TERM_PATTERN.finditer(normalized)}
    for match in CHINESE_SEQUENCE_PATTERN.finditer(normalized):
        sequence = match.group(0)
        terms.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return terms


def _evidence_text(citation: dict[str, Any]) -> str:
    return " ".join(
        str(citation.get(key) or "")
        for key in ("title", "file_name", "excerpt", "content")
    ).strip()


def validate_citation_grounding(
    reply: str,
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check citation syntax, paragraph coverage and lexical evidence overlap."""

    indexed: dict[int, dict[str, Any]] = {}
    for position, citation in enumerate(citations, start=1):
        if not isinstance(citation, dict):
            continue
        try:
            index = int(citation.get("index") or position)
        except (TypeError, ValueError):
            index = position
        indexed[index] = citation

    paragraphs = [
        item.strip()
        for item in re.split(r"\n+|(?<=[。！？!?])", reply)
        if len(item.strip()) >= 12
    ]
    cited_indices = sorted({int(value) for value in CITATION_PATTERN.findall(reply)})
    valid_indices = [index for index in cited_indices if index in indexed]
    invalid_indices = [index for index in cited_indices if index not in indexed]

    covered = 0
    overlaps: list[float] = []
    for paragraph in paragraphs:
        paragraph_indices = {
            int(value) for value in CITATION_PATTERN.findall(paragraph) if int(value) in indexed
        }
        if not paragraph_indices:
            continue
        covered += 1
        claim_terms = _terms(CITATION_PATTERN.sub("", paragraph))
        evidence_terms: set[str] = set()
        for index in paragraph_indices:
            evidence_terms.update(_terms(_evidence_text(indexed[index])))
        if claim_terms:
            overlaps.append(len(claim_terms & evidence_terms) / len(claim_terms))

    coverage_score = covered / len(paragraphs) if paragraphs else 0.0
    overlap_score = sum(overlaps) / len(overlaps) if overlaps else 0.0
    if not indexed:
        status = "not_applicable"
    elif invalid_indices:
        status = "invalid"
    elif not valid_indices:
        status = "unsupported"
    elif coverage_score >= 0.6 and overlap_score >= 0.03:
        status = "supported"
    else:
        status = "partial"

    return {
        "status": status,
        "method": "deterministic-v1",
        "cited_indices": cited_indices,
        "valid_indices": valid_indices,
        "invalid_indices": invalid_indices,
        "coverage_score": round(coverage_score, 3),
        "evidence_overlap_score": round(overlap_score, 3),
    }
