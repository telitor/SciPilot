"""Verify that the public software-engineering corpus serves all five agents.

The script creates one disposable, email-confirmed user, exercises only the
local FastAPI API, verifies public-read/system-write protection and citation
auditing, then deletes the user. It never prints credentials or secrets.
"""

from pathlib import Path
import os
import secrets
import sys
from typing import Any

import httpx


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.supabase_service import get_supabase_client  # noqa: E402


API_BASE_URL = os.getenv("SCIPILOT_E2E_API", "http://127.0.0.1:8000/api/v1")
QUESTIONS = {
    "paper-reading": "论文精读时怎样区分研究问题、研究方法、实验依据和结论局限？",
    "problem-decomposition": "软件工程研究问题如何拆成可验证的子问题、输入输出与验收标准？",
    "project-planning": "软件工程项目怎样规划里程碑、依赖、风险和验收标准？",
    "code-reproduction": "复现论文开源代码时如何固定依赖版本、随机种子、数据和运行环境？",
    "result-interpretation": "实验结果应如何结合效应量、置信区间和统计显著性进行解释？",
}


def require(response: httpx.Response, expected: int) -> Any:
    if response.status_code != expected:
        raise AssertionError(
            f"{response.request.method} {response.request.url.path}: "
            f"expected {expected}, got {response.status_code}: {response.text[:500]}"
        )
    return None if expected == 204 else response.json()


def main() -> int:
    service = get_supabase_client()
    suffix = secrets.token_hex(10)
    email = f"scipilot.agent-kb.{suffix}@gmail.com"
    password = f"SciPilotAgent{secrets.token_hex(8)}9!"
    user_id: str | None = None
    report: dict[str, Any] = {}

    try:
        created = service.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"username": "知识库智能体验收用户", "role": "user"},
            }
        )
        user_id = str(created.user.id)

        with httpx.Client(base_url=API_BASE_URL, timeout=90) as api:
            login = require(
                api.post("/auth/login", json={"email": email, "password": password}),
                200,
            )
            headers = {"Authorization": f"Bearer {login['token']}"}

            collections = require(api.get("/knowledge/collections", headers=headers), 200)
            system_items = [
                item
                for item in collections["items"]
                if item.get("is_public")
                and (item.get("metadata") or {}).get("system_managed")
            ]
            assert len(system_items) == 1, "expected exactly one system-managed collection"
            collection = system_items[0]
            collection_id = collection["id"]

            documents = require(
                api.get(
                    "/knowledge/documents",
                    headers=headers,
                    params={"collection_id": collection_id, "limit": 100},
                ),
                200,
            )
            assert documents["total"] >= 12
            assert all(item.get("status") == "ready" for item in documents["items"])
            first_document = documents["items"][0]
            require(
                api.get(
                    f"/knowledge/documents/{first_document['id']}",
                    headers=headers,
                ),
                200,
            )

            forbidden_write = api.post(
                "/knowledge/documents/text",
                headers=headers,
                json={
                    "collection_id": collection_id,
                    "title": "不应写入",
                    "content": "普通用户不能修改系统知识库。",
                },
            )
            assert forbidden_write.status_code == 403
            forbidden_delete = api.delete(
                f"/knowledge/collections/{collection_id}",
                headers=headers,
            )
            assert forbidden_delete.status_code == 403

            agents = require(api.get("/agents"), 200)
            by_category = {item["category"]: item for item in agents}
            assert set(QUESTIONS).issubset(by_category)

            agent_results: dict[str, Any] = {}
            for category, question in QUESTIONS.items():
                answer = require(
                    api.post(
                        f"/agents/{by_category[category]['id']}/ask",
                        headers=headers,
                        json={
                            "message": question,
                            "collection_id": collection_id,
                            "top_k": 8,
                        },
                    ),
                    200,
                )
                assert answer["knowledge_used"] is True
                assert answer["retrieval_id"]
                assert len(answer["citations"]) >= 1
                assert "[1]" in answer["reply"]
                agent_results[category] = {
                    "status": 200,
                    "citations": len(answer["citations"]),
                    "retrieval_audited": True,
                }

            retrievals = (
                service.table("kb_retrievals")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .execute()
            )
            citations = (
                service.table("kb_citations")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .execute()
            )
            retrieval_count = retrievals.count or len(retrievals.data or [])
            citation_count = citations.count or len(citations.data or [])
            assert retrieval_count >= 5 and citation_count >= 5

            report = {
                "public_system_collection": "visible",
                "documents": documents["total"],
                "system_write_protection": "passed",
                "agents": agent_results,
                "audit": {
                    "retrievals": retrieval_count,
                    "citations": citation_count,
                },
            }

        print(report)
        return 0
    finally:
        if user_id:
            try:
                service.auth.admin.delete_user(user_id)
                print({"disposable_users_removed": 1})
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
