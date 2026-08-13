"""Normalize and persist paper-derived knowledge graph evidence."""

import hashlib
import re
from typing import Any


MAX_ENTITIES = 30
MAX_RELATIONS = 60
ENTITY_CATEGORIES = {
    "paper",
    "author",
    "method",
    "dataset",
    "metric",
    "concept",
    "finding",
    "section",
}


class KnowledgeGraphUnavailable(RuntimeError):
    """The graph evidence migration is not available yet."""


def _clean_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _entity_key(value: Any, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip()).strip("-")
    return (cleaned or fallback)[:80]


def _relation_name(value: Any) -> str:
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    return (cleaned or "related-to")[:80]


def _positive_page(value: Any) -> int | None:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _page_range(
    item: dict[str, Any],
    fallback: int | None = None,
    valid_pages: set[int] | None = None,
) -> tuple[int | None, int | None]:
    start = _positive_page(item.get("page_start") or item.get("page") or fallback)
    end = _positive_page(item.get("page_end"))
    if valid_pages is not None and start not in valid_pages:
        start = None
    if valid_pages is not None and end not in valid_pages:
        end = None
    if end is not None and (start is None or end < start):
        end = None
    return start, end


def normalize_paper_graph(
    raw_graph: Any,
    *,
    title: str,
    authors: list[str],
    sections: list[dict[str, Any]],
    valid_pages: set[int] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Normalize model graph output and provide a backward-compatible fallback."""

    citation_sections: dict[str, str] = {}
    citation_pages: dict[str, int] = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        heading = _clean_text(section.get("heading") or section.get("title"), 300)
        raw_citations = section.get("citations")
        if not isinstance(raw_citations, list):
            continue
        for citation in raw_citations:
            if isinstance(citation, dict):
                marker = _clean_text(citation.get("text"), 100)
                if marker and heading:
                    citation_sections[marker] = heading
                    page = _positive_page(citation.get("page"))
                    if page:
                        citation_pages[marker] = page

    entities: list[dict[str, Any]] = [
        {
            "key": "paper",
            "label": title,
            "category": "paper",
            "description": "论文",
            "citation": "",
            "section_heading": "",
            "excerpt": "",
            "page_start": None,
            "page_end": None,
        }
    ]
    seen_keys = {"paper"}
    raw_entities = raw_graph.get("entities") if isinstance(raw_graph, dict) else None
    if isinstance(raw_entities, list):
        for index, item in enumerate(raw_entities[: MAX_ENTITIES - 1], start=1):
            if not isinstance(item, dict):
                continue
            label = _clean_text(item.get("label"), 300)
            if not label:
                continue
            key = _entity_key(item.get("id") or item.get("key"), f"entity-{index}")
            if key in seen_keys or label.casefold() == title.casefold():
                continue
            category = _clean_text(item.get("category"), 50).lower()
            citation = _clean_text(item.get("citation"), 100)
            page_start, page_end = _page_range(
                item, citation_pages.get(citation), valid_pages
            )
            entities.append(
                {
                    "key": key,
                    "label": label,
                    "category": category if category in ENTITY_CATEGORIES else "concept",
                    "description": _clean_text(item.get("description"), 1000),
                    "citation": citation,
                    "section_heading": citation_sections.get(citation, ""),
                    "excerpt": _clean_text(item.get("evidence") or item.get("excerpt"), 2000),
                    "page_start": page_start,
                    "page_end": page_end,
                }
            )
            seen_keys.add(key)

    relations: list[dict[str, Any]] = []
    seen_relations: set[tuple[str, str, str]] = set()
    raw_relations = raw_graph.get("relations") if isinstance(raw_graph, dict) else None
    if isinstance(raw_relations, list):
        for item in raw_relations[:MAX_RELATIONS]:
            if not isinstance(item, dict):
                continue
            source = _entity_key(item.get("source"), "")
            target = _entity_key(item.get("target"), "")
            if not source or not target or source == target:
                continue
            if source not in seen_keys or target not in seen_keys:
                continue
            try:
                strength = float(item.get("strength") or 0.8)
            except (TypeError, ValueError):
                strength = 0.8
            relation_name = _relation_name(item.get("relation"))
            relation_key = (source, target, relation_name)
            if relation_key in seen_relations:
                continue
            seen_relations.add(relation_key)
            citation = _clean_text(item.get("citation"), 100)
            page_start, page_end = _page_range(
                item, citation_pages.get(citation), valid_pages
            )
            relations.append(
                {
                    "source": source,
                    "target": target,
                    "relation": relation_name,
                    "strength": max(0.0, min(strength, 1.0)),
                    "citation": citation,
                    "section_heading": citation_sections.get(citation, ""),
                    "evidence": _clean_text(item.get("evidence"), 2000),
                    "page_start": page_start,
                    "page_end": page_end,
                }
            )

    if len(entities) == 1:
        for index, author in enumerate(authors[:12], start=1):
            label = _clean_text(author, 300)
            if not label or label.casefold() == "unknown":
                continue
            key = f"author-{index}"
            entities.append(
                {
                    "key": key,
                    "label": label,
                    "category": "author",
                    "description": "论文作者",
                    "citation": "",
                    "section_heading": "",
                    "excerpt": "",
                    "page_start": None,
                    "page_end": None,
                }
            )
            seen_keys.add(key)
            relations.append(
                {
                    "source": key,
                    "target": "paper",
                    "relation": "authored",
                    "strength": 1.0,
                    "citation": "",
                    "section_heading": "",
                    "evidence": "",
                    "page_start": None,
                    "page_end": None,
                }
            )
        for index, section in enumerate(sections[:4], start=1):
            if not isinstance(section, dict):
                continue
            heading = _clean_text(section.get("heading") or section.get("title"), 300)
            content = _clean_text(section.get("content"), 2000)
            if not heading:
                continue
            key = f"section-{index}"
            citation_value = ""
            raw_citations = section.get("citations")
            if isinstance(raw_citations, list) and raw_citations:
                citation_value = _clean_text(raw_citations[0].get("text"), 100) if isinstance(raw_citations[0], dict) else ""
            citation_page = (
                _positive_page(raw_citations[0].get("page"))
                if isinstance(raw_citations, list)
                and raw_citations
                and isinstance(raw_citations[0], dict)
                else None
            )
            entities.append(
                {
                    "key": key,
                    "label": f"{title} · {heading}",
                    "category": "section",
                    "description": content[:1000],
                    "citation": citation_value,
                    "section_heading": heading,
                    "excerpt": content,
                    "page_start": citation_page,
                    "page_end": None,
                }
            )
            seen_keys.add(key)
            relations.append(
                {
                    "source": "paper",
                    "target": key,
                    "relation": "has-section",
                    "strength": 1.0,
                    "citation": citation_value,
                    "section_heading": heading,
                    "evidence": content,
                    "page_start": citation_page,
                    "page_end": None,
                }
            )

    return {"entities": entities[:MAX_ENTITIES], "relations": relations[:MAX_RELATIONS]}


def _slug(paper_id: str, entity: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        f"{entity['category']}:{entity['key']}:{entity['label'].casefold()}".encode("utf-8")
    ).hexdigest()[:24]
    return f"paper-{paper_id}-{digest}"


def sync_paper_knowledge_graph(
    database: Any,
    *,
    user_id: str,
    paper_id: str,
    project_id: str | None,
    graph: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Replace one paper's generated private graph and persist evidence links."""

    try:
        database.table("knowledge_graph_evidence").select("id").limit(1).execute()
    except Exception as exc:
        raise KnowledgeGraphUnavailable("请先应用知识图谱证据迁移") from exc

    previous = (
        database.table("knowledge_graph_evidence")
        .select("node_id,edge_id")
        .eq("paper_id", paper_id)
        .eq("user_id", user_id)
        .execute()
    ).data or []
    edge_ids = [str(item["edge_id"]) for item in previous if item.get("edge_id")]
    node_ids = [str(item["node_id"]) for item in previous if item.get("node_id")]
    if edge_ids:
        database.table("knowledge_edges").delete().eq("user_id", user_id).in_("id", edge_ids).execute()
    if node_ids:
        database.table("knowledge_nodes").delete().eq("user_id", user_id).in_("id", node_ids).execute()
    database.table("knowledge_graph_evidence").delete().eq("paper_id", paper_id).eq("user_id", user_id).execute()

    node_rows = [
        {
            "user_id": user_id,
            "slug": _slug(paper_id, entity),
            "label": entity["label"],
            "category": entity["category"],
            "description": entity.get("description") or None,
            "metadata": {
                "source": "paper-analysis",
                "paper_id": paper_id,
                "project_id": project_id,
                "entity_key": entity["key"],
            },
            "is_public": False,
        }
        for entity in graph.get("entities", [])
    ]
    inserted_nodes = database.table("knowledge_nodes").insert(node_rows).execute().data or []
    key_to_node = {
        str(row.get("metadata", {}).get("entity_key")): row
        for row in inserted_nodes
        if isinstance(row.get("metadata"), dict)
    }

    edge_rows: list[dict[str, Any]] = []
    edge_sources: list[dict[str, Any]] = []
    for relation in graph.get("relations", []):
        source = key_to_node.get(str(relation.get("source")))
        target = key_to_node.get(str(relation.get("target")))
        if not source or not target:
            continue
        edge_rows.append(
            {
                "user_id": user_id,
                "source_node_id": source["id"],
                "target_node_id": target["id"],
                "relation": relation["relation"],
                "strength": relation["strength"],
                "evidence": relation.get("evidence") or None,
                "metadata": {"source": "paper-analysis", "paper_id": paper_id, "project_id": project_id},
                "is_public": False,
            }
        )
        edge_sources.append(relation)
    inserted_edges = (
        database.table("knowledge_edges").insert(edge_rows).execute().data or []
        if edge_rows
        else []
    )

    evidence_rows: list[dict[str, Any]] = []
    entity_by_key = {str(item["key"]): item for item in graph.get("entities", [])}
    for key, node in key_to_node.items():
        entity = entity_by_key.get(key, {})
        evidence_rows.append(
            {
                "user_id": user_id,
                "project_id": project_id,
                "paper_id": paper_id,
                "node_id": node["id"],
                "citation": entity.get("citation") or None,
                "section_heading": entity.get("section_heading") or None,
                "excerpt": entity.get("excerpt") or entity.get("description") or None,
                "page_start": entity.get("page_start"),
                "page_end": entity.get("page_end"),
            }
        )
    for edge, relation in zip(inserted_edges, edge_sources, strict=False):
        evidence_rows.append(
            {
                "user_id": user_id,
                "project_id": project_id,
                "paper_id": paper_id,
                "edge_id": edge["id"],
                "citation": relation.get("citation") or None,
                "section_heading": relation.get("section_heading") or None,
                "excerpt": relation.get("evidence") or None,
                "page_start": relation.get("page_start"),
                "page_end": relation.get("page_end"),
            }
        )
    if evidence_rows:
        database.table("knowledge_graph_evidence").insert(evidence_rows).execute()
    return {
        "status": "completed",
        "node_count": len(inserted_nodes),
        "edge_count": len(inserted_edges),
    }
