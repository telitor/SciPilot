#!/usr/bin/env python3
"""Build a source-grounded Alpaca dataset for SciPilot's five agents.

Sources:
* CC BY computer-science paper metadata and abstracts from OpenAlex.
* CC BY 3.0 chapters from The Architecture of Open Source Applications.

The generator is deliberately extractive/template-grounded. It does not call an
LLM and does not invent experimental metrics, repositories, commands, or facts
that are absent from the supplied abstract/chapter excerpt.
"""

from __future__ import annotations

import argparse
import math
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from typing import Any, Iterable
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


OPENALEX_API = "https://api.openalex.org/works"
AOSA_ROOT = "https://aosabook.org/en/"
AOSA_LICENSE_URL = "https://aosabook.org/en/license.html"
OPENALEX_LICENSE_URL = "https://openalex.org/licenses/cc-by"

PAPER_QUERIES = (
    "software engineering",
    "software testing",
    "program analysis",
    "distributed systems",
    "machine learning",
    "natural language processing",
    "information retrieval",
    "large language models",
)

AGENT_ORDER = (
    "paper-reading",
    "problem-decomposition",
    "project-planning",
    "code-reproduction",
    "result-interpretation",
)

SYSTEM_PROMPTS = {
    "paper-reading": (
        "你是SciPilot论文阅读Agent。只依据输入中的证据[S1]工作，区分原文事实与推断；"
        "证据未提供的信息必须明确写为“未说明”，并保留来源引用。"
    ),
    "problem-decomposition": (
        "你是SciPilot研究问题拆解Agent。把来源内容转换为可验证的研究问题、变量和证据需求；"
        "不得把建议性的研究步骤写成来源已经证明的事实。"
    ),
    "project-planning": (
        "你是SciPilot项目规划Agent。根据来源证据制定可执行、可验收的研究路线；"
        "对数据、代码、环境和指标缺口设置检查点，不得虚构资源。"
    ),
    "code-reproduction": (
        "你是SciPilot代码复现Agent。只在输入明确给出仓库、环境或命令时才能复述；"
        "缺少实现细节时输出核查清单，禁止臆造仓库地址、依赖版本和运行命令。"
    ),
    "result-interpretation": (
        "你是SciPilot结果解读Agent。只解释证据中实际出现的结果、指标和限制；"
        "没有数值或对照实验时必须指出证据不足，不得补造显著性或性能提升。"
    ),
}

INSTRUCTIONS = {
    "paper-reading": (
        "[AGENT=paper-reading][DOMAIN=computer-science] 阅读真实来源证据，提取研究主题、"
        "可确认的方法/主张、结果与证据边界，并用[S1]引用。"
    ),
    "problem-decomposition": (
        "[AGENT=problem-decomposition][DOMAIN=computer-science] 依据真实来源，把主题拆成"
        "可验证的核心问题、子问题、待观测变量和缺失证据。"
    ),
    "project-planning": (
        "[AGENT=project-planning][DOMAIN=computer-science] 依据真实来源制定研究或复现路线，"
        "列出阶段、输入、产出、验收点和风险控制。"
    ),
    "code-reproduction": (
        "[AGENT=code-reproduction][DOMAIN=computer-science] 评估该来源的代码可复现条件；"
        "仅使用已给出的事实，缺少仓库或环境信息时给出核查清单。"
    ),
    "result-interpretation": (
        "[AGENT=result-interpretation][DOMAIN=computer-science] 解读来源中明确报告的结果，"
        "区分已报告结论、可做的解释与当前无法判断的事项。"
    ),
}

METHOD_WORDS = (
    "propose", "present", "develop", "introduce", "method", "model",
    "framework", "approach", "algorithm", "system", "using", "based on",
)
RESULT_WORDS = (
    "result", "show", "demonstrate", "evaluate", "outperform", "improve",
    "achieve", "accuracy", "performance", "effective", "experiment", "prove",
    "increase", "decrease", "reduce", "higher", "lower", "found", "observe",
)
LIMIT_WORDS = ("limit", "future work", "challenge", "however", "remain")

TITLE_STOPWORDS = {
    "about", "after", "against", "based", "between", "from", "into", "over",
    "through", "toward", "towards", "under", "using", "with", "without",
    "study", "analysis", "approach", "method", "methods", "model", "models",
    "system", "systems", "framework", "frameworks", "application", "applications",
    "the", "and", "for", "that", "this", "are", "our", "via", "new",
}


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


class ChapterTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.capture_tag: str | None = None
        self.buffer: list[str] = []
        self.title_parts: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"h1", "p"}:
            self.capture_tag = tag.lower()
            self.buffer = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.capture_tag != tag:
            return
        text = normalize_space(" ".join(self.buffer))
        if tag == "h1" and text:
            self.title_parts.append(text)
        elif tag == "p" and len(text) >= 80:
            lowered = text.lower()
            excluded_prefixes = (
                "figure ",
                "if you enjoy these books",
                "this work is licensed",
                "copyright ",
                "please see the full description of the license",
            )
            if not lowered.startswith(excluded_prefixes):
                self.paragraphs.append(text)
        self.capture_tag = None
        self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.capture_tag:
            self.buffer.append(data)


def normalize_space(value: str | None) -> str:
    if not value:
        return ""
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def clip(value: str, limit: int = 1500) -> str:
    value = normalize_space(value)
    if len(value) <= limit:
        return value
    cut = value[:limit]
    sentence_end = max(cut.rfind(". "), cut.rfind("。"), cut.rfind("! "), cut.rfind("? "))
    if sentence_end >= int(limit * 0.65):
        cut = cut[: sentence_end + 1]
    return cut.rstrip() + "…"


def fetch_text(url: str, attempts: int = 4) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "SciPilotDatasetBuilder/1.0 (source-grounded academic dataset)",
            "Accept": "application/json,text/html,application/xhtml+xml",
        },
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=60) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def reconstruct_abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    positions: list[tuple[int, str]] = []
    for token, offsets in index.items():
        for offset in offsets:
            positions.append((int(offset), token))
    positions.sort(key=lambda item: item[0])
    return normalize_space(" ".join(token for _, token in positions))


def sentence_list(text: str) -> list[str]:
    sentences = [normalize_space(item) for item in re.split(r"(?<=[.!?。！？])\s+", text)]
    return [item for item in sentences if len(item) >= 30]


def sentence_with(
    text: str,
    keywords: Iterable[str],
    fallback_index: int | None,
    fallback_text: str = "来源证据未明确说明。",
) -> str:
    sentences = sentence_list(text)
    scored: list[tuple[int, int, str]] = []
    for position, sentence in enumerate(sentences):
        lowered = sentence.lower()
        keyword_hits = sum(keyword in lowered for keyword in keywords)
        if keyword_hits:
            numeric_bonus = 2 if re.search(r"\d|%", sentence) else 0
            scored.append((keyword_hits + numeric_bonus, -position, sentence))
    if scored:
        return clip(max(scored, key=lambda item: (item[0], item[1]))[2], 420)
    if not sentences or fallback_index is None:
        return fallback_text
    index = fallback_index if fallback_index >= 0 else len(sentences) + fallback_index
    index = min(max(index, 0), len(sentences) - 1)
    return clip(sentences[index], 420)


def title_abstract_aligned(title: str, abstract: str) -> bool:
    title_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", title.lower())
        if len(token) >= 3 and token not in TITLE_STOPWORDS
    }
    abstract_tokens = set(re.findall(r"[a-z0-9]+", abstract.lower()))
    if not title_tokens:
        return True
    required = 1 if len(title_tokens) <= 3 else max(2, math.ceil(len(title_tokens) * 0.3))
    return len(title_tokens & abstract_tokens) >= required


def author_names(authorships: list[dict[str, Any]] | None) -> list[str]:
    names: list[str] = []
    for row in authorships or []:
        name = normalize_space((row.get("author") or {}).get("display_name"))
        if name and name not in names:
            names.append(name)
    return names[:8]


def fetch_openalex_papers(minimum: int) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    filters = ",".join(
        (
            "has_abstract:true",
            "is_oa:true",
            "language:en",
            "primary_topic.field.id:17",
            "best_oa_location.license:cc-by",
            "from_publication_date:2015-01-01",
        )
    )
    select = ",".join(
        (
            "id", "doi", "display_name", "publication_year", "type",
            "authorships", "best_oa_location", "abstract_inverted_index",
            "primary_topic", "topics", "cited_by_count",
        )
    )
    for page in range(1, 4):
        for query in PAPER_QUERIES:
            params = urlencode(
                {
                    "filter": filters,
                    "search": query,
                    "per-page": 100,
                    "page": page,
                    "sort": "cited_by_count:desc",
                    "select": select,
                }
            )
            payload = json.loads(fetch_text(f"{OPENALEX_API}?{params}"))
            for work in payload.get("results", []):
                source_id = normalize_space(work.get("id"))
                title = normalize_space(work.get("display_name"))
                abstract = clip(reconstruct_abstract(work.get("abstract_inverted_index")))
                location = work.get("best_oa_location") or {}
                license_name = normalize_space(location.get("license")).lower()
                if (
                    not source_id
                    or not title
                    or len(abstract) < 350
                    or license_name != "cc-by"
                    or not title_abstract_aligned(title, abstract)
                ):
                    continue
                topics = [
                    normalize_space(item.get("display_name"))
                    for item in (work.get("topics") or [])[:4]
                    if normalize_space(item.get("display_name"))
                ]
                candidates[source_id] = {
                    "source_id": source_id,
                    "source_type": "paper",
                    "title": title,
                    "authors": author_names(work.get("authorships")),
                    "year": work.get("publication_year"),
                    "doi": normalize_space(work.get("doi")),
                    "source_url": normalize_space(location.get("landing_page_url")) or source_id,
                    "license": "CC BY",
                    "license_url": OPENALEX_LICENSE_URL,
                    "topics": topics,
                    "evidence": abstract,
                    "cited_by_count": int(work.get("cited_by_count") or 0),
                    "origin": "OpenAlex",
                }
            time.sleep(0.2)
        print(f"OpenAlex page {page}: {len(candidates)} unique eligible papers", flush=True)
        if len(candidates) >= minimum:
            break

    ranked = sorted(
        candidates.values(),
        key=lambda row: (-row["cited_by_count"], row["source_id"]),
    )
    if len(ranked) < minimum:
        raise RuntimeError(
            f"Only {len(ranked)} eligible CC BY papers were collected; need {minimum}."
        )
    return ranked[:minimum]


def fetch_aosa_chapters(limit: int = 50) -> list[dict[str, Any]]:
    index_html = fetch_text(AOSA_ROOT)
    collector = LinkCollector()
    collector.feed(index_html)
    excluded = ("intro", "license", "faq", "index", "bibliograph", "acknowledg")
    links: list[str] = []
    for href in collector.links:
        lowered = href.lower()
        if not re.fullmatch(r"v[12]/[a-z0-9_-]+\.html", lowered):
            continue
        if any(token in lowered for token in excluded):
            continue
        absolute = urljoin(AOSA_ROOT, href)
        if absolute not in links:
            links.append(absolute)

    chapters: list[dict[str, Any]] = []
    for url in links[:limit]:
        parser = ChapterTextParser()
        parser.feed(fetch_text(url))
        title = parser.title_parts[0] if parser.title_parts else Path(url).stem
        title = re.sub(r"^The Architecture of Open Source Applications \(Volume \d\)\s*", "", title)
        evidence = clip(" ".join(parser.paragraphs[:12]))
        if len(evidence) < 350:
            continue
        volume_match = re.search(r"/v(\d)/", url)
        volume = volume_match.group(1) if volume_match else ""
        chapters.append(
            {
                "source_id": url,
                "source_type": "book_chapter",
                "title": title,
                "authors": [],
                "year": 2011 if volume == "1" else 2012,
                "doi": "",
                "source_url": url,
                "license": "CC BY 3.0",
                "license_url": AOSA_LICENSE_URL,
                "topics": ["Software Architecture", "Open Source Software"],
                "evidence": evidence,
                "cited_by_count": 0,
                "origin": "The Architecture of Open Source Applications",
            }
        )
        time.sleep(0.1)
    return chapters


def format_input(record_id: str, source: dict[str, Any]) -> str:
    author_text = ", ".join(source["authors"]) if source["authors"] else "来源页面未单列"
    topic_text = ", ".join(source["topics"]) if source["topics"] else "未标注"
    doi_text = source["doi"] or "无"
    source_type = "开放论文" if source["source_type"] == "paper" else "开放许可书籍章节"
    return (
        f"记录ID：{record_id}\n"
        f"来源类型：{source_type}\n"
        f"题名：{source['title']}\n"
        f"作者：{author_text}\n"
        f"年份：{source['year']}\n"
        f"主题：{topic_text}\n"
        f"DOI：{doi_text}\n"
        f"来源URL：{source['source_url']}\n"
        f"许可：{source['license']}（{source['license_url']}）\n"
        f"证据[S1]：{source['evidence']}"
    )


def make_output(agent: str, source: dict[str, Any]) -> str:
    evidence = source["evidence"]
    title = source["title"]
    topic = "、".join(source["topics"][:3]) or title
    opening = sentence_with(evidence, ("aim", "goal", "address", "study", "investigate"), 0)
    method = sentence_with(evidence, METHOD_WORDS, 1)
    result = sentence_with(
        evidence,
        RESULT_WORDS,
        None,
        "来源证据未明确报告可独立提取的实验结果。",
    )
    limitation = sentence_with(
        evidence,
        LIMIT_WORDS,
        None,
        "来源证据未明确说明研究局限。",
    )
    is_book = source["source_type"] == "book_chapter"

    if agent == "paper-reading":
        kind = "书籍章节" if is_book else "论文"
        return (
            f"文献类型：{kind}\n"
            f"研究/讨论主题：{title}；相关主题为{topic}。[S1]\n"
            f"目标或背景证据：{opening} [S1]\n"
            f"方法或设计证据：{method} [S1]\n"
            f"结果或主要论述证据：{result} [S1]\n"
            "证据边界：当前仅提供摘要或章节节选，无法据此确认全文中的数据集规模、完整实验设置、"
            "统计显著性、代码仓库和全部局限；这些信息均应标记为未说明。"
        )

    if agent == "problem-decomposition":
        return (
            f"核心问题：如何验证《{title}》围绕“{topic}”提出或讨论的主张？[S1]\n"
            "子问题1：来源所处理的对象、输入、约束和目标分别是什么？\n"
            f"子问题2：证据中出现的方法线索“{method}”需要哪些可观测变量与基线？[S1]\n"
            f"子问题3：证据中出现的结果线索“{result}”能否由独立数据或复现实验支持？[S1]\n"
            "待观测变量：任务输入、方法配置、比较基线、评价指标、数据划分、随机种子和失败案例。\n"
            "缺失证据：全文方法、实验表格、数据与代码地址未随当前证据完整提供，不能预设其值。"
        )

    if agent == "project-planning":
        return (
            f"项目目标：在不超出[S1]证据的前提下核验《{title}》的核心方法和结果。\n"
            "阶段1—资料冻结：获取许可允许的全文、补充材料、代码与数据；产出来源清单和版本哈希；"
            "验收点是每个文件均可追溯。\n"
            "阶段2—方法规格化：把输入、处理流程、超参数、基线和指标转成实验规格；验收点是未说明项均有标记。\n"
            "阶段3—最小复现：先运行最小样例，再复现主要实验；产出日志、环境锁定文件和原始结果。\n"
            "阶段4—对照验证：使用相同数据划分与指标比较原结果；报告一致、偏差和无法比较项。\n"
            "风险控制：禁止用摘要补造实现细节；数据、仓库或评测协议缺失时暂停相应结论。"
        )

    if agent == "code-reproduction":
        return (
            f"可复现性判断：当前证据能够确认主题《{title}》和部分方法线索，但不足以直接生成可靠运行命令。[S1]\n"
            f"已知线索：{method} [S1]\n"
            "必须核查：官方仓库URL、提交版本、许可证、语言/框架版本、依赖锁文件、硬件要求、"
            "数据下载方式、预处理脚本、入口命令、随机种子和预期输出。\n"
            "执行顺序：验证仓库来源→固定提交→隔离环境→运行最小样例→执行测试→复现实验→保存日志。\n"
            "禁止事项：不得根据题名或摘要臆造GitHub地址、pip/conda命令、依赖版本或性能结果。"
        )

    if is_book:
        return (
            f"来源性质：《{title}》是解释性书籍章节，而不是当前证据下可识别的对照实验。[S1]\n"
            f"可确认论述：{result} [S1]\n"
            "结果边界：不能从章节节选推导准确率、显著性、相对提升或普适因果结论。\n"
            "合理用法：将其作为架构原理、设计权衡和复现检查项的背景来源，并用论文或实验数据验证具体效果。"
        )
    return (
        f"已报告结果线索：{result} [S1]\n"
        f"方法关联：{method} [S1]\n"
        f"限制线索：{limitation} [S1]\n"
        "解释边界：只有摘要证据时，可以陈述作者报告了什么，但不能确认效应量、统计显著性、"
        "可重复性或对其他数据集的泛化。若[S1]没有明确数值，不得补写任何百分比或提升幅度。\n"
        "后续验证：核对全文实验表、基线、样本量、方差/置信区间、消融实验和独立复现。"
    )


def build_records(sources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    for source_index, source in enumerate(sources, start=1):
        source_key = hashlib.sha256(source["source_id"].encode("utf-8")).hexdigest()[:12]
        record_ids: list[str] = []
        for agent_index, agent in enumerate(AGENT_ORDER, start=1):
            record_id = f"scipilot-{source_index:04d}-{agent_index}-{source_key}"
            record_ids.append(record_id)
            records.append(
                {
                    "instruction": INSTRUCTIONS[agent],
                    "input": format_input(record_id, source),
                    "output": make_output(agent, source),
                    "system": SYSTEM_PROMPTS[agent],
                    "history": [],
                }
            )
        manifest.append(
            {
                key: source[key]
                for key in (
                    "source_id", "source_type", "title", "authors", "year", "doi",
                    "source_url", "license", "license_url", "topics", "origin",
                )
            }
            | {
                "evidence_sha256": hashlib.sha256(source["evidence"].encode("utf-8")).hexdigest(),
                "record_ids": record_ids,
            }
        )
    return records, manifest


def validate_dataset(
    train: list[dict[str, Any]], manifest: list[dict[str, Any]], output_file: Path,
) -> dict[str, Any]:
    required = {"instruction", "input", "output", "system", "history"}
    invalid_schema = [index for index, row in enumerate(train) if set(row) != required]
    empty_required = [
        index for index, row in enumerate(train)
        if any(not row[field] for field in ("instruction", "input", "output", "system"))
        or not isinstance(row["history"], list)
    ]
    fingerprints = [
        hashlib.sha256(
            (row["instruction"] + "\n" + row["input"] + "\n" + row["output"]).encode("utf-8")
        ).hexdigest()
        for row in train
    ]
    duplicate_count = len(fingerprints) - len(set(fingerprints))
    task_counts: dict[str, int] = {}
    for agent in AGENT_ORDER:
        marker = f"[AGENT={agent}]"
        task_counts[agent] = sum(marker in row["instruction"] for row in train)
    combined_lengths = [len(row["input"]) + len(row["output"]) for row in train]
    file_size = output_file.stat().st_size if output_file.exists() else 0
    report = {
        "status": "passed",
        "grain": "one Alpaca instruction per source per agent",
        "records": {"train": len(train)},
        "sources": {
            "total": len(manifest),
            "papers": sum(row["source_type"] == "paper" for row in manifest),
            "book_chapters": sum(row["source_type"] == "book_chapter" for row in manifest),
        },
        "task_counts": task_counts,
        "schema_errors": len(invalid_schema),
        "empty_required_errors": len(empty_required),
        "exact_duplicate_records": duplicate_count,
        "input_output_chars": {
            "min": min(combined_lengths),
            "max": max(combined_lengths),
            "mean": round(sum(combined_lengths) / len(combined_lengths), 2),
            "over_4000": sum(length > 4000 for length in combined_lengths),
        },
        "file_size_bytes": file_size,
        "file_under_500_mb": file_size < 500 * 1024 * 1024,
        "limitations": [
            "Outputs are deterministic source-grounded templates, not expert human annotations.",
            "Paper evidence is limited to OpenAlex abstracts; full-method and full-result claims are intentionally refused.",
            "AOSA evidence uses chapter excerpts under CC BY 3.0 and requires retained attribution.",
            "A human subject-matter review is required before production fine-tuning.",
        ],
    }
    if any(
        (
            invalid_schema,
            empty_required,
            duplicate_count,
            file_size >= 500 * 1024 * 1024,
        )
    ):
        report["status"] = "failed"
    return report


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("datasets"))
    parser.add_argument("--source-count", type=int, default=500)
    args = parser.parse_args()
    if args.source_count <= 0:
        raise SystemExit("source-count must be positive")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    books = fetch_aosa_chapters(limit=min(50, args.source_count))
    print(f"AOSA: {len(books)} eligible book chapters", flush=True)
    paper_count = args.source_count - len(books)
    papers = fetch_openalex_papers(paper_count)
    sources = papers + books

    train, manifest = build_records(sources)
    train_path = args.output_dir / "scipilot_alpaca_train.json"
    write_json(train_path, train)
    report = validate_dataset(train, manifest, train_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
