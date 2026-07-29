"""Disposable two-user end-to-end verification for the SciPilot knowledge base.

The script reads backend/.env, creates two confirmed QA users, exercises the
local FastAPI server plus direct RLS/Storage access, and removes all test users,
rows, and files in a finally block. It never prints credentials.
"""

from pathlib import Path
import os
import secrets
import sys
from typing import Any

import httpx
from supabase import ClientOptions, create_client


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.supabase_service import get_supabase_client  # noqa: E402


API_BASE_URL = os.getenv("SCIPILOT_E2E_API", "http://127.0.0.1:8000/api/v1")


def require(response: httpx.Response, expected: int) -> dict[str, Any]:
    if response.status_code != expected:
        raise AssertionError(
            f"{response.request.method} {response.request.url.path}: "
            f"expected {expected}, got {response.status_code}: {response.text[:500]}"
        )
    if expected == 204:
        return {}
    return response.json()


def count_rows(table: str, user_id: str) -> int:
    result = (
        get_supabase_client()
        .table(table)
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )
    return result.count if result.count is not None else len(result.data or [])


def main() -> int:
    service = get_supabase_client()
    url = os.getenv("SUPABASE_URL")
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv(
        "SUPABASE_ANON_KEY"
    )
    if not url or not publishable_key:
        raise RuntimeError("SUPABASE_URL / publishable key is not configured")

    suffix = secrets.token_hex(10)
    password_a = f"SciPilotA{secrets.token_hex(8)}9!"
    password_b = f"SciPilotB{secrets.token_hex(8)}9!"
    emails = [
        f"scipilot.e2e.a.{suffix}@gmail.com",
        f"scipilot.e2e.b.{suffix}@gmail.com",
    ]
    user_ids: list[str] = []
    storage_paths: list[str] = []
    collection_id: str | None = None
    report: dict[str, Any] = {}

    try:
        created_a = service.auth.admin.create_user(
            {
                "email": emails[0],
                "password": password_a,
                "email_confirm": True,
                "user_metadata": {"username": "知识库验收用户A", "role": "user"},
            }
        )
        created_b = service.auth.admin.create_user(
            {
                "email": emails[1],
                "password": password_b,
                "email_confirm": True,
                "user_metadata": {"username": "知识库验收用户B", "role": "user"},
            }
        )
        user_ids = [str(created_a.user.id), str(created_b.user.id)]

        with httpx.Client(base_url=API_BASE_URL, timeout=60) as api:
            login_a = require(
                api.post("/auth/login", json={"email": emails[0], "password": password_a}),
                200,
            )
            login_b = require(
                api.post("/auth/login", json={"email": emails[1], "password": password_b}),
                200,
            )
            headers_a = {"Authorization": f"Bearer {login_a['token']}"}
            headers_b = {"Authorization": f"Bearer {login_b['token']}"}
            report["login"] = [200, 200]

            status = require(api.get("/knowledge/status", headers=headers_a), 200)
            assert status["ready"] is True
            assert status["retrieval"] == "full-text"
            report["knowledge_status"] = status["retrieval"]

            collection = require(
                api.post(
                    "/knowledge/collections",
                    headers=headers_a,
                    json={
                        "name": f"端到端验收-{suffix}",
                        "description": "自动化测试后删除",
                    },
                ),
                201,
            )
            collection_id = collection["id"]

            note_payload = {
                "collection_id": collection_id,
                "title": "SciPilot 中文检索验收笔记",
                "content": (
                    "SciPilot 知识库支持 PDF、TXT 和 Markdown 文档。"
                    "未配置向量模型时，系统使用 PostgreSQL 全文检索与中文模糊检索。"
                    "每个回答都应返回能够映射到文档片段的来源引用。"
                ),
                "source_url": "https://github.com/telitor/SciPilot",
            }
            note = require(
                api.post("/knowledge/documents/text", headers=headers_a, json=note_payload),
                201,
            )
            assert note["status"] == "ready" and note["chunk_count"] > 0
            repeated = require(
                api.post("/knowledge/documents/text", headers=headers_a, json=note_payload),
                201,
            )
            assert repeated.get("duplicate") is True
            report["text_ingestion"] = {
                "status": note["status"],
                "chunks": note["chunk_count"],
                "deduplicated": True,
            }

            markdown = (
                "# SciPilot 文件入库验收\n\n"
                "知识库文件会保存到私有 Storage，并切分为可检索片段。\n\n"
                "跨账号用户不能读取该私有原文件。"
            ).encode("utf-8")
            uploaded = require(
                api.post(
                    "/knowledge/documents/upload",
                    headers=headers_a,
                    data={"collection_id": collection_id},
                    files={
                        "file": (
                            "scipilot-e2e.md",
                            markdown,
                            "text/markdown",
                        )
                    },
                ),
                201,
            )
            assert uploaded["status"] == "ready" and uploaded["chunk_count"] > 0
            if uploaded.get("storage_path"):
                storage_paths.append(uploaded["storage_path"])
            report["file_ingestion"] = {
                "status": uploaded["status"],
                "chunks": uploaded["chunk_count"],
            }

            documents = require(
                api.get(
                    "/knowledge/documents",
                    headers=headers_a,
                    params={"collection_id": collection_id},
                ),
                200,
            )
            assert documents["total"] == 2

            search = require(
                api.post(
                    "/knowledge/search",
                    headers=headers_a,
                    json={
                        "query": "中文模糊检索",
                        "collection_id": collection_id,
                        "top_k": 8,
                    },
                ),
                200,
            )
            assert search["total"] >= 1
            assert search["items"][0]["document_id"] == note["id"]
            report["search"] = {
                "mode": search["retrieval"],
                "hits": search["total"],
            }

            answer = require(
                api.post(
                    "/knowledge/answer",
                    headers=headers_a,
                    json={
                        "query": "没有向量密钥时还能使用什么检索？",
                        "collection_id": collection_id,
                        "top_k": 8,
                        "include_answer": True,
                    },
                ),
                200,
            )
            assert answer["answer"] and len(answer["citations"]) >= 1
            assert answer["citations"][0]["document_id"]
            report["grounded_answer"] = {
                "citations": len(answer["citations"]),
                "retrieval_audited": bool(answer.get("retrieval_id")),
            }

            graph = require(api.get("/kg/explore", headers=headers_a), 200)
            assert len(graph["nodes"]) == 15 and len(graph["edges"]) == 14
            report["knowledge_graph"] = {
                "nodes": len(graph["nodes"]),
                "edges": len(graph["edges"]),
            }

            forbidden_document = api.get(
                f"/knowledge/documents/{note['id']}", headers=headers_b
            )
            assert forbidden_document.status_code == 404
            private_search = require(
                api.post(
                    "/knowledge/search",
                    headers=headers_b,
                    json={"query": "中文模糊检索", "top_k": 8},
                ),
                200,
            )
            # Public system knowledge is intentionally visible to both users.
            # The isolation invariant is that B never receives A's private note.
            assert all(
                item.get("document_id") != note["id"]
                for item in private_search["items"]
            )

            anon_options = ClientOptions(
                auto_refresh_token=False,
                persist_session=False,
            )
            direct_a = create_client(url, publishable_key, options=anon_options)
            direct_b = create_client(
                url,
                publishable_key,
                options=ClientOptions(
                    auto_refresh_token=False,
                    persist_session=False,
                ),
            )
            direct_a.auth.sign_in_with_password(
                {"email": emails[0], "password": password_a}
            )
            direct_b.auth.sign_in_with_password(
                {"email": emails[1], "password": password_b}
            )
            visible_a = (
                direct_a.table("kb_collections")
                .select("id")
                .eq("id", collection_id)
                .execute()
                .data
                or []
            )
            visible_b = (
                direct_b.table("kb_collections")
                .select("id")
                .eq("id", collection_id)
                .execute()
                .data
                or []
            )
            assert len(visible_a) == 1 and len(visible_b) == 0

            storage_denied = False
            if storage_paths:
                direct_a.storage.from_("knowledge-base").download(storage_paths[0])
                try:
                    direct_b.storage.from_("knowledge-base").download(storage_paths[0])
                except Exception:
                    storage_denied = True
                assert storage_denied

            direct_rpc_denied = False
            try:
                direct_b.rpc(
                    "search_knowledge_base",
                    {
                        "query_text": "中文",
                        "query_embedding": None,
                        "match_count": 5,
                        "filter_collection_id": None,
                        "requesting_user_id": user_ids[0],
                    },
                ).execute()
            except Exception:
                direct_rpc_denied = True
            assert direct_rpc_denied
            report["isolation"] = {
                "api_private_document": "hidden",
                "private_search_result": "hidden",
                "public_knowledge": "allowed",
                "rls_collection": "hidden",
                "storage": "denied",
                "direct_rpc": "denied",
            }

            retrieval_count = count_rows("kb_retrievals", user_ids[0])
            citation_count = count_rows("kb_citations", user_ids[0])
            assert retrieval_count >= 2 and citation_count >= 1
            report["audit_trail"] = {
                "retrievals": retrieval_count,
                "citations": citation_count,
            }

            require(
                api.delete(
                    f"/knowledge/documents/{uploaded['id']}", headers=headers_a
                ),
                204,
            )
            require(
                api.delete(f"/knowledge/documents/{note['id']}", headers=headers_a),
                204,
            )
            require(
                api.delete(
                    f"/knowledge/collections/{collection_id}", headers=headers_a
                ),
                204,
            )
            assert count_rows("kb_documents", user_ids[0]) == 0
            assert count_rows("kb_chunks", user_ids[0]) == 0
            report["deletion_cleanup"] = "passed"

        print(report)
        return 0
    finally:
        if user_ids:
            try:
                remaining = (
                    service.table("kb_documents")
                    .select("storage_path")
                    .in_("user_id", user_ids)
                    .execute()
                    .data
                    or []
                )
                paths = [
                    row["storage_path"]
                    for row in remaining
                    if row.get("storage_path")
                ]
                if paths:
                    service.storage.from_("knowledge-base").remove(paths)
            except Exception:
                pass
        for user_id in user_ids:
            try:
                service.auth.admin.delete_user(user_id)
            except Exception:
                pass
        if user_ids:
            print({"disposable_users_removed": len(user_ids)})


if __name__ == "__main__":
    raise SystemExit(main())
