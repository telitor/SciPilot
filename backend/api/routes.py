import csv
import hashlib
import json
import math
import os
import re
import statistics
import uuid
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)

from api.dependencies import (
    database,
    format_user,
    get_current_user,
    get_or_create_profile,
    record_activity,
    require_owned_row,
)
from api.schemas import (
    AgentKnowledgeAskRequest,
    CreateConversationRequest,
    DiagnoseRequest,
    ExperimentRoadmapRequest,
    KnowledgeAnswerRequest,
    KnowledgeCollectionRequest,
    KnowledgeCollectionUpdateRequest,
    KnowledgeSearchRequest,
    KnowledgeTextDocumentRequest,
    LegacyChatRequest,
    LoginRequest,
    NewMessageRequest,
    RegisterRequest,
    RepoAnalysisRequest,
    ResearchDecomposeRequest,
    UpdateProfileRequest,
)
from services.agent_knowledge_service import build_citations, grounded_agent_reply
from services.knowledge_base_service import (
    chunk_knowledge_text,
    create_embedding,
    estimate_tokens,
    extract_knowledge_text,
    safe_filename as safe_kb_filename,
    sha256_bytes,
)
from services.llm_service import call_default_llm
from services.supabase_service import get_supabase_auth_client

router = APIRouter()

PAPER_COLUMNS = (
    "id,title,authors,abstract,source_url,arxiv_id,doi,file_name,mime_type,"
    "file_size,status,is_favorite,metadata,uploaded_at,created_at,updated_at"
)


def _first(result: Any) -> dict[str, Any] | None:
    return result.data[0] if getattr(result, "data", None) else None


def _safe_data(execute: Any) -> list[dict[str, Any]]:
    """Return query rows, or an empty list while optional migrations are pending."""

    try:
        result = execute()
        return result.data or []
    except Exception:
        return []


def _safe_filename(filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name).strip(".-")
    return safe[:160] or "paper.pdf"


def _auth_error() -> HTTPException:
    return HTTPException(status_code=401, detail="邮箱或密码不正确")


def _extract_pdf_metadata(content: bytes, fallback_title: str) -> dict[str, Any]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        metadata = reader.metadata or {}
        title = str(getattr(metadata, "title", "") or fallback_title).strip()
        author_text = str(getattr(metadata, "author", "") or "").strip()
        authors = [part.strip() for part in re.split(r"[,;]", author_text) if part.strip()]
        text_parts: list[str] = []
        for page in reader.pages[:5]:
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(page_text.strip())
            if sum(map(len, text_parts)) >= 10_000:
                break
        text = "\n\n".join(text_parts)[:10_000]
        return {
            "title": title or fallback_title,
            "authors": authors or ["Unknown"],
            "text": text,
            "page_count": len(reader.pages),
        }
    except Exception:
        return {
            "title": fallback_title,
            "authors": ["Unknown"],
            "text": "",
            "page_count": None,
        }


def _save_artifact(
    user_id: str,
    artifact_type: str,
    title: str,
    input_data: dict[str, Any],
    content: dict[str, Any],
) -> dict[str, Any]:
    result = (
        database()
        .table("research_artifacts")
        .insert(
            {
                "user_id": user_id,
                "artifact_type": artifact_type,
                "title": title[:500],
                "input": input_data,
                "content": content,
                "status": "completed",
            }
        )
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="保存研究结果失败")
    return result.data[0]


def _require_visible_kb_collection(
    collection_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Authorize reads from an owned private or globally public collection."""

    try:
        result = (
            database()
            .table("kb_collections")
            .select("*")
            .eq("id", collection_id)
            .limit(1)
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=409,
            detail="知识库表尚未部署，请先执行迁移 008_knowledge_base.sql",
        ) from None
    collection = _first(result)
    if not collection or (
        str(collection.get("user_id")) != user_id
        and not bool(collection.get("is_public"))
    ):
        # Do not reveal the existence of another user's private collection.
        raise HTTPException(status_code=404, detail="知识库集合不存在或无权访问")
    return collection


def _require_writable_kb_collection(
    collection_id: str,
    user: Any,
) -> dict[str, Any]:
    """
    Authorize collection mutations.

    Private collections remain owner-only. Public/system-managed collections
    are readable by all authenticated users but writable only by administrators.
    """

    user_id = str(user.id)
    collection = _require_visible_kb_collection(collection_id, user_id)
    metadata = collection.get("metadata") or {}
    is_managed = bool(metadata.get("system_managed"))
    if bool(collection.get("is_public")) or is_managed:
        profile = get_or_create_profile(user)
        if profile.get("role") != "admin":
            raise HTTPException(
                status_code=403,
                detail="公共或系统知识库只能由管理员修改",
            )
        return collection
    if str(collection.get("user_id")) != user_id:
        raise HTTPException(status_code=404, detail="知识库集合不存在或无权写入")
    return collection


def _default_kb_collection(user_id: str) -> dict[str, Any]:
    try:
        existing = (
            database()
            .table("kb_collections")
            .select("*")
            .eq("user_id", user_id)
            .eq("name", "我的知识库")
            .limit(1)
            .execute()
        )
        collection = _first(existing)
        if collection:
            return collection
        created = (
            database()
            .table("kb_collections")
            .insert(
                {
                    "user_id": user_id,
                    "name": "我的知识库",
                    "description": "自动创建的个人科研知识库",
                    "is_public": False,
                }
            )
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=409,
            detail="知识库表尚未部署，请先执行迁移 008_knowledge_base.sql",
        ) from None
    collection = _first(created)
    if not collection:
        raise HTTPException(status_code=500, detail="创建默认知识库失败")
    return collection


def _search_knowledge_base(
    *,
    query: str,
    user_id: str,
    collection_id: str | None,
    top_k: int,
) -> list[dict[str, Any]]:
    try:
        query_embedding = create_embedding(query)
    except Exception:
        # Full-text search remains available when the optional embedding
        # provider is unavailable or misconfigured.
        query_embedding = None
    try:
        result = database().rpc(
            "search_knowledge_base",
            {
                "query_text": query,
                "query_embedding": query_embedding,
                "match_count": top_k,
                "filter_collection_id": collection_id,
                "requesting_user_id": user_id,
            },
        ).execute()
    except Exception:
        raise HTTPException(
            status_code=409,
            detail="知识库检索尚未部署，请先执行迁移 008_knowledge_base.sql",
        ) from None
    return result.data or []


def _record_kb_retrieval(
    *,
    user_id: str,
    query: str,
    rows: list[dict[str, Any]],
    collection_id: str | None,
    answer: str | None,
    retrieval_mode: str,
    conversation_id: str | None = None,
    message_id: str | None = None,
    agent: dict[str, Any] | None = None,
    model: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> str | None:
    """Persist an auditable search/citation snapshot without blocking results."""

    try:
        retrieval_result = (
            database()
            .table("kb_retrievals")
            .insert(
                {
                    "user_id": user_id,
                    "collection_id": collection_id,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "query_text": query,
                    "answer_text": answer,
                    "retrieval_mode": retrieval_mode,
                    "model": model,
                    "metadata": {
                        "result_count": len(rows),
                        "agent_id": agent.get("id") if agent else None,
                        "agent_category": agent.get("category") if agent else None,
                        **(extra_metadata or {}),
                    },
                }
            )
            .execute()
        )
        retrieval = _first(retrieval_result)
        if not retrieval:
            return None
        citation_rows = [
            {
                "retrieval_id": retrieval["id"],
                "user_id": user_id,
                "chunk_id": row.get("chunk_id"),
                "document_id": row.get("document_id"),
                "rank": rank,
                "score": row.get("score"),
                "document_title": row.get("document_title"),
                "source_url": row.get("source_url"),
                "file_name": row.get("file_name"),
                "excerpt": (row.get("content") or "")[:1000],
                "metadata": {"chunk_index": row.get("chunk_index")},
            }
            for rank, row in enumerate(rows, start=1)
        ]
        if citation_rows:
            database().table("kb_citations").insert(citation_rows).execute()
        return retrieval["id"]
    except Exception:
        return None


def _store_kb_text_document(
    *,
    user_id: str,
    collection_id: str,
    title: str,
    text: str,
    source_type: str,
    checksum: str,
    source_url: str | None = None,
    storage_path: str | None = None,
    file_name: str | None = None,
    mime_type: str | None = None,
    file_size: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chunks = chunk_knowledge_text(text)
    if not chunks:
        raise HTTPException(status_code=422, detail="文档无法切分为有效知识片段")

    document: dict[str, Any] | None = None
    try:
        created = (
            database()
            .table("kb_documents")
            .insert(
                {
                    "collection_id": collection_id,
                    "user_id": user_id,
                    "title": title[:500],
                    "source_type": source_type,
                    "source_url": source_url,
                    "storage_path": storage_path,
                    "file_name": file_name,
                    "mime_type": mime_type,
                    "file_size": file_size,
                    "checksum": checksum,
                    "status": "processing",
                    "character_count": len(text),
                    "metadata": metadata or {},
                }
            )
            .execute()
        )
        document = _first(created)
        if not document:
            raise RuntimeError("数据库未返回文档记录")

        chunk_rows: list[dict[str, Any]] = []
        embedded_count = 0
        for index, chunk in enumerate(chunks):
            try:
                embedding = create_embedding(chunk)
            except Exception:
                embedding = None
            if embedding is not None:
                embedded_count += 1
            chunk_rows.append(
                {
                    "document_id": document["id"],
                    "collection_id": collection_id,
                    "user_id": user_id,
                    "chunk_index": index,
                    "title": document["title"],
                    "content": chunk,
                    "token_count": estimate_tokens(chunk),
                    "embedding": embedding,
                    "metadata": {},
                }
            )
        for start in range(0, len(chunk_rows), 50):
            database().table("kb_chunks").insert(chunk_rows[start : start + 50]).execute()

        completed_metadata = {
            **(metadata or {}),
            "embedded_chunks": embedded_count,
            "retrieval": "hybrid" if embedded_count else "full-text",
        }
        completed = (
            database()
            .table("kb_documents")
            .update(
                {
                    "status": "ready",
                    "chunk_count": len(chunk_rows),
                    "metadata": completed_metadata,
                }
            )
            .eq("id", document["id"])
            .eq("user_id", user_id)
            .execute()
        )
        return _first(completed) or {
            **document,
            "status": "ready",
            "chunk_count": len(chunk_rows),
            "metadata": completed_metadata,
        }
    except HTTPException:
        raise
    except Exception as exc:
        if document:
            try:
                database().table("kb_documents").update(
                    {"status": "failed", "metadata": {"error": str(exc)[:500]}}
                ).eq("id", document["id"]).eq("user_id", user_id).execute()
            except Exception:
                pass
        raise HTTPException(status_code=500, detail="知识库文档切块或入库失败") from None


def _pick_agent(module: str, agent_id: str | None = None) -> dict[str, Any]:
    query = database().table("agents").select(
        "id,name,description,system_prompt,category,is_public"
    )
    if agent_id:
        result = query.eq("id", agent_id).eq("is_public", True).limit(1).execute()
    else:
        category_map = {
            "paper": "paper-reading",
            "paper-reading": "paper-reading",
            "research": "problem-decomposition",
            "research-decompose": "problem-decomposition",
            "result": "result-interpretation",
            "result-analysis": "result-interpretation",
            "code": "code-reproduction",
            "code-reproduce": "code-reproduction",
            "experiment": "project-planning",
            "project": "project-planning",
        }
        category = category_map.get(module)
        if category:
            result = query.eq("category", category).eq("is_public", True).limit(1).execute()
        else:
            result = query.eq("is_public", True).limit(1).execute()
    agent = _first(result)
    if not agent:
        raise HTTPException(status_code=409, detail="没有可用智能体，请先执行数据库迁移")
    return agent


def _agent_knowledge_answer(
    *,
    agent: dict[str, Any],
    message: str,
    user_id: str,
    collection_id: str | None,
    top_k: int,
) -> dict[str, Any]:
    if collection_id:
        _require_visible_kb_collection(collection_id, user_id)
    rows = _search_knowledge_base(
        query=message,
        user_id=user_id,
        collection_id=collection_id,
        top_k=top_k,
    )
    citations = build_citations(rows)
    reply, response_mode, model = grounded_agent_reply(
        agent=agent,
        message=message,
        citations=citations,
        user_id=user_id,
    )
    return {
        "reply": reply,
        # Store exactly the evidence that was exposed to the model/client.
        "rows": rows[: len(citations)],
        "citations": citations,
        "knowledge_used": bool(citations),
        "retrieval_mode": (
            "hybrid" if os.getenv("EMBEDDING_API_KEY") else "full-text"
        ),
        "response_mode": response_mode,
        "model": model,
    }


def _chat_reply(conversation: dict[str, Any], content: str, user_id: str) -> dict[str, Any]:
    agent = _pick_agent(conversation.get("module", "general"), conversation.get("agent_id"))
    user_message = (
        database()
        .table("messages")
        .insert(
            {
                "conversation_id": conversation["id"],
                "user_id": user_id,
                "agent_id": agent["id"],
                "role": "user",
                "content": content,
            }
        )
        .execute()
    )
    if not user_message.data:
        raise HTTPException(status_code=500, detail="保存消息失败")

    context = conversation.get("context") or {}
    collection_id = (
        context.get("collection_id") if isinstance(context, dict) else None
    )
    answer = _agent_knowledge_answer(
        agent=agent,
        message=content,
        user_id=user_id,
        collection_id=collection_id,
        top_k=8,
    )
    reply = answer["reply"]

    assistant = (
        database()
        .table("messages")
        .insert(
            {
                "conversation_id": conversation["id"],
                "user_id": user_id,
                "agent_id": agent["id"],
                "role": "assistant",
                "content": reply,
                "citations": answer["citations"],
                "model": answer["model"],
                "metadata": {
                    "knowledge_used": answer["knowledge_used"],
                    "retrieval_mode": answer["retrieval_mode"],
                    "response_mode": answer["response_mode"],
                },
            }
        )
        .execute()
    )
    database().table("conversations").update(
        {"title": content[:60] or conversation.get("title") or "新的对话"}
    ).eq("id", conversation["id"]).eq("user_id", user_id).execute()
    record_activity(
        user_id,
        conversation.get("module") or "general",
        "发送消息",
        content[:100],
        entity_type="conversation",
        entity_id=conversation["id"],
    )
    message = _first(assistant)
    if not message:
        raise HTTPException(status_code=500, detail="保存智能体回复失败")
    retrieval_id = _record_kb_retrieval(
        user_id=user_id,
        query=content,
        rows=answer["rows"],
        collection_id=collection_id,
        answer=reply,
        retrieval_mode=answer["retrieval_mode"],
        conversation_id=conversation["id"],
        message_id=message["id"],
        agent=agent,
        model=answer["model"],
        extra_metadata={
            "knowledge_used": answer["knowledge_used"],
            "response_mode": answer["response_mode"],
        },
    )
    if retrieval_id:
        message_metadata = {
            **(message.get("metadata") or {}),
            "retrieval_id": retrieval_id,
        }
        try:
            database().table("messages").update(
                {"metadata": message_metadata}
            ).eq("id", message["id"]).eq("user_id", user_id).execute()
        except Exception:
            pass
        message["metadata"] = message_metadata
    return {
        "reply": reply,
        "message": message,
        "citations": answer["citations"],
        "knowledge_used": answer["knowledge_used"],
        "retrieval_id": retrieval_id,
        "agent": {
            key: agent.get(key)
            for key in ("id", "name", "description", "category", "is_public")
        },
    }


@router.get("/health")
def health():
    return {"status": "ok", "service": "SciPilot API", "version": "1.0.0"}


# ---------------------------------------------------------------------------
# Authentication and profile
# ---------------------------------------------------------------------------


def _auth_auto_confirm_email_enabled() -> bool:
    return os.getenv("AUTH_AUTO_CONFIRM_EMAIL", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _registration_error(exc: Exception) -> HTTPException:
    message = str(exc).lower()
    if any(
        marker in message
        for marker in (
            "already registered",
            "already been registered",
            "already exists",
            "user already registered",
        )
    ):
        return HTTPException(status_code=409, detail="该邮箱已经注册，请直接登录")
    if "rate limit" in message or "too many" in message:
        return HTTPException(status_code=429, detail="注册请求过于频繁，请稍后再试")
    if "password" in message or "weak_password" in message:
        return HTTPException(
            status_code=400,
            detail="密码不符合 Supabase 的安全要求",
        )
    if "email" in message or "invalid" in message:
        return HTTPException(status_code=400, detail="邮箱格式无效或不被接受")
    return HTTPException(status_code=400, detail="注册失败，请稍后再试")


@router.post("/auth/register")
def register(payload: RegisterRequest):
    email = payload.email.strip().lower()
    auth_client = get_supabase_auth_client()
    auto_confirm = _auth_auto_confirm_email_enabled()
    created_user_id: str | None = None

    if auto_confirm:
        try:
            created = database().auth.admin.create_user(
                {
                    "email": email,
                    "password": payload.password,
                    "email_confirm": True,
                    "user_metadata": {
                        "username": payload.username,
                        "role": "user",
                    },
                }
            )
        except Exception as exc:
            raise _registration_error(exc) from None
        if not created.user:
            raise HTTPException(status_code=500, detail="注册服务未返回用户")
        created_user_id = str(created.user.id)
        try:
            response = auth_client.auth.sign_in_with_password(
                {"email": email, "password": payload.password}
            )
        except Exception:
            # Do not leave an unusable account behind if the automatic
            # sign-in step unexpectedly fails immediately after creation.
            try:
                database().auth.admin.delete_user(created_user_id)
            except Exception:
                pass
            raise HTTPException(
                status_code=502,
                detail="账号已创建但自动登录失败，请重新注册",
            ) from None
    else:
        try:
            response = auth_client.auth.sign_up(
                {
                    "email": email,
                    "password": payload.password,
                    "options": {
                        "data": {
                            "username": payload.username,
                            "role": "user",
                        }
                    },
                }
            )
        except Exception as exc:
            raise _registration_error(exc) from None

    if auto_confirm and (not response.user or not response.session):
        try:
            if created_user_id:
                database().auth.admin.delete_user(created_user_id)
        except Exception:
            pass
        raise HTTPException(
            status_code=502,
            detail="账号已创建但自动登录失败，请重新注册",
        )
    if not response.user:
        raise HTTPException(status_code=400, detail="注册失败")

    profile_payload = {
        "id": str(response.user.id),
        "email": response.user.email,
        "username": payload.username,
        "role": "user",
    }
    try:
        database().table("profiles").upsert(profile_payload).execute()
    except Exception:
        database().table("profiles").upsert(
            {
                "id": profile_payload["id"],
                "username": profile_payload["username"],
                "role": "user",
            }
        ).execute()
    token = response.session.access_token if response.session else None
    return {
        "user": format_user(response.user, profile_payload),
        "token": token,
        "requires_email_confirmation": False if auto_confirm else token is None,
    }


@router.post("/auth/login")
def login(payload: LoginRequest):
    try:
        response = get_supabase_auth_client().auth.sign_in_with_password(
            {"email": payload.email.strip().lower(), "password": payload.password}
        )
    except Exception as exc:
        message = str(exc).lower()
        if "email not confirmed" in message:
            raise HTTPException(status_code=403, detail="请先完成邮箱验证后再登录") from None
        raise _auth_error() from None
    if not response.user or not response.session:
        raise _auth_error()
    profile = get_or_create_profile(response.user)
    return {
        "user": format_user(response.user, profile),
        "token": response.session.access_token,
    }


@router.post("/auth/logout", status_code=204)
def logout():
    return Response(status_code=204)


@router.get("/users/me")
def get_me(user=Depends(get_current_user)):
    return format_user(user, get_or_create_profile(user))


@router.patch("/users/me")
def update_me(payload: UpdateProfileRequest, user=Depends(get_current_user)):
    changes = payload.model_dump(exclude_none=True)
    if changes:
        try:
            result = (
                database()
                .table("profiles")
                .update(changes)
                .eq("id", str(user.id))
                .execute()
            )
        except Exception:
            # The original profiles table only has username/avatar_url/role.
            legacy_changes = {
                key: value
                for key, value in changes.items()
                if key in {"username", "avatar_url"}
            }
            if not legacy_changes:
                raise HTTPException(
                    status_code=409,
                    detail="请先执行数据库迁移 006 后再保存简介或偏好设置",
                ) from None
            result = (
                database()
                .table("profiles")
                .update(legacy_changes)
                .eq("id", str(user.id))
                .execute()
            )
        profile = _first(result) or get_or_create_profile(user)
    else:
        profile = get_or_create_profile(user)
    return format_user(user, profile)


@router.get("/users/me/stats")
def profile_stats(user=Depends(get_current_user)):
    user_id = str(user.id)
    profile = get_or_create_profile(user)
    papers = _safe_data(
        lambda: database()
        .table("papers")
        .select("id,is_favorite")
        .eq("user_id", user_id)
        .execute()
    )
    conversations = _safe_data(
        lambda: database()
        .table("conversations")
        .select("id")
        .eq("user_id", user_id)
        .execute()
    )
    artifacts = _safe_data(
        lambda: database()
        .table("research_artifacts")
        .select("id,artifact_type")
        .eq("user_id", user_id)
        .execute()
    )
    activities = _safe_data(
        lambda: database()
        .table("activities")
        .select("module")
        .eq("user_id", user_id)
        .execute()
    )
    created_at = profile.get("created_at")
    try:
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        days_used = max(1, (datetime.now(timezone.utc) - created).days + 1)
    except Exception:
        days_used = 1
    modules = Counter(item.get("module") or "general" for item in activities)
    return {
        "paper_count": len(papers),
        "conversation_count": len(conversations),
        "favorite_count": sum(bool(row.get("is_favorite")) for row in papers),
        "artifact_count": len(artifacts),
        "days_used": days_used,
        "module_usage": [{"module": key, "count": value} for key, value in modules.most_common()],
    }


@router.get("/activities")
def list_activities(
    limit: int = Query(default=20, ge=1, le=100),
    user=Depends(get_current_user),
):
    rows = _safe_data(
        lambda: database()
        .table("activities")
        .select("*")
        .eq("user_id", str(user.id))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"items": rows, "total": len(rows)}


# ---------------------------------------------------------------------------
# Papers and reports
# ---------------------------------------------------------------------------


@router.post("/papers/upload")
async def upload_paper(file: UploadFile = File(...), user=Depends(get_current_user)):
    filename = file.filename or "paper.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="只支持 PDF 文件")
    max_bytes = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if not content or len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="PDF 为空或超过上传大小限制")
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="文件不是有效的 PDF")

    user_id = str(user.id)
    paper_id = str(uuid.uuid4())
    safe_name = _safe_filename(filename)
    file_path = f"{user_id}/{paper_id}/{safe_name}"
    fallback_title = Path(filename).stem
    extracted = _extract_pdf_metadata(content, fallback_title)
    checksum = hashlib.sha256(content).hexdigest()

    try:
        database().storage.from_("papers").upload(
            path=file_path,
            file=content,
            file_options={"content-type": "application/pdf", "upsert": "false"},
        )
        result = (
            database()
            .table("papers")
            .insert(
                {
                    "id": paper_id,
                    "user_id": user_id,
                    "title": extracted["title"],
                    "authors": extracted["authors"],
                    "abstract": extracted["text"][:1500] or None,
                    "file_path": file_path,
                    "file_name": filename,
                    "mime_type": "application/pdf",
                    "file_size": len(content),
                    "checksum_sha256": checksum,
                    "status": "completed",
                    "metadata": {"page_count": extracted["page_count"]},
                }
            )
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"论文保存失败：{exc}") from None

    sections = [
        {
            "heading": "文档信息",
            "content": f"已安全保存 PDF，共 {extracted['page_count'] or '未知'} 页。可继续接入论文精读智能体生成完整报告。",
            "citations": [],
        },
        {
            "heading": "文本预览",
            "content": extracted["text"][:2000] or "该 PDF 暂未提取到可搜索文本，可能是扫描版。",
            "citations": [],
        },
    ]
    database().table("paper_reports").upsert(
        {
            "paper_id": paper_id,
            "user_id": user_id,
            "report_type": "deep-read",
            "status": "completed",
            "summary": extracted["text"][:500] or None,
            "sections": sections,
            "content": {"page_count": extracted["page_count"]},
        },
        on_conflict="paper_id,report_type",
    ).execute()
    record_activity(
        user_id,
        "paper",
        "上传论文",
        extracted["title"],
        entity_type="paper",
        entity_id=paper_id,
    )
    paper = _first(result)
    if not paper:
        paper = require_owned_row("papers", paper_id, user_id, columns=PAPER_COLUMNS)
    return paper


@router.get("/papers")
def list_papers(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200),
    user=Depends(get_current_user),
):
    offset = (page - 1) * limit
    query = (
        database()
        .table("papers")
        .select(PAPER_COLUMNS, count="exact")
        .eq("user_id", str(user.id))
    )
    if search and search.strip():
        query = query.ilike("title", f"%{search.strip()}%")
    try:
        result = (
            query.order("uploaded_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
    except Exception:
        # Keep authentication and the dashboard usable before migration 006
        # creates the optional paper workspace tables.
        return {
            "items": [],
            "page": page,
            "limit": limit,
            "total": 0,
            "migration_required": True,
        }
    return {
        "items": result.data or [],
        "page": page,
        "limit": limit,
        "total": result.count if result.count is not None else len(result.data or []),
    }


@router.get("/papers/{paper_id}")
def get_paper(paper_id: str, user=Depends(get_current_user)):
    return require_owned_row(
        "papers", paper_id, str(user.id), columns=PAPER_COLUMNS
    )


@router.get("/papers/{paper_id}/deep-read")
def get_deep_read(paper_id: str, user=Depends(get_current_user)):
    user_id = str(user.id)
    require_owned_row("papers", paper_id, user_id)
    result = (
        database()
        .table("paper_reports")
        .select("paper_id,summary,sections,content,status,updated_at")
        .eq("paper_id", paper_id)
        .eq("user_id", user_id)
        .eq("report_type", "deep-read")
        .limit(1)
        .execute()
    )
    report = _first(result)
    if not report:
        raise HTTPException(status_code=404, detail="尚未生成精读报告")
    return {"paper_id": paper_id, "sections": report.get("sections") or [], **report}


@router.get("/papers/{paper_id}/download-url")
def get_paper_download_url(paper_id: str, user=Depends(get_current_user)):
    paper = require_owned_row(
        "papers", paper_id, str(user.id), columns="id,file_path"
    )
    if not paper.get("file_path"):
        raise HTTPException(status_code=404, detail="该论文没有上传文件")
    result = database().storage.from_("papers").create_signed_url(
        paper["file_path"], 300
    )
    return {"url": result.get("signedURL") or result.get("signedUrl"), "expires_in": 300}


@router.delete("/papers/{paper_id}", status_code=204)
def delete_paper(paper_id: str, user=Depends(get_current_user)):
    user_id = str(user.id)
    paper = require_owned_row("papers", paper_id, user_id, columns="id,file_path,title")
    if paper.get("file_path"):
        try:
            database().storage.from_("papers").remove([paper["file_path"]])
        except Exception:
            pass
    database().table("papers").delete().eq("id", paper_id).eq("user_id", user_id).execute()
    record_activity(user_id, "paper", "删除论文", paper.get("title") or paper_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Agents and conversations
# ---------------------------------------------------------------------------


@router.get("/agents")
def list_agents():
    result = (
        database()
        .table("agents")
        .select("id,name,description,category,is_public,created_at")
        .eq("is_public", True)
        .order("name")
        .execute()
    )
    return result.data or []


@router.post("/agents/{agent_id}/ask")
def ask_agent_with_knowledge(
    agent_id: str,
    payload: AgentKnowledgeAskRequest,
    user=Depends(get_current_user),
):
    user_id = str(user.id)
    agent = _pick_agent("general", agent_id)
    message = payload.message.strip()
    answer = _agent_knowledge_answer(
        agent=agent,
        message=message,
        user_id=user_id,
        collection_id=payload.collection_id,
        top_k=payload.top_k,
    )
    retrieval_id = _record_kb_retrieval(
        user_id=user_id,
        query=message,
        rows=answer["rows"],
        collection_id=payload.collection_id,
        answer=answer["reply"],
        retrieval_mode=answer["retrieval_mode"],
        agent=agent,
        model=answer["model"],
        extra_metadata={
            "knowledge_used": answer["knowledge_used"],
            "response_mode": answer["response_mode"],
        },
    )
    record_activity(
        user_id,
        agent.get("category") or "agent",
        "智能体知识问答",
        message[:200],
        entity_type="kb_retrieval",
        entity_id=retrieval_id,
        metadata={
            "agent_id": agent["id"],
            "citation_count": len(answer["citations"]),
        },
    )
    return {
        "reply": answer["reply"],
        "citations": answer["citations"],
        "knowledge_used": answer["knowledge_used"],
        "retrieval_id": retrieval_id,
        "agent": {
            key: agent.get(key)
            for key in ("id", "name", "description", "category", "is_public")
        },
    }


@router.post("/conversations")
def create_conversation(payload: CreateConversationRequest, user=Depends(get_current_user)):
    agent = _pick_agent(payload.module, payload.agent_id)
    result = (
        database()
        .table("conversations")
        .insert(
            {
                "user_id": str(user.id),
                "agent_id": agent["id"],
                "title": payload.title,
                "module": payload.module,
            }
        )
        .execute()
    )
    conversation = _first(result)
    if not conversation:
        raise HTTPException(status_code=500, detail="创建对话失败")
    return {**conversation, "messages": []}


@router.get("/conversations")
def list_conversations(
    module: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    user=Depends(get_current_user),
):
    query = (
        database()
        .table("conversations")
        .select("id,agent_id,title,module,status,created_at,updated_at", count="exact")
        .eq("user_id", str(user.id))
    )
    if module:
        query = query.eq("module", module)
    result = query.order("updated_at", desc=True).range(
        (page - 1) * limit, page * limit - 1
    ).execute()
    items = [{**row, "messages": []} for row in (result.data or [])]
    return {"items": items, "page": page, "limit": limit, "total": result.count or len(items)}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user=Depends(get_current_user)):
    user_id = str(user.id)
    conversation = require_owned_row("conversations", conversation_id, user_id)
    messages = (
        database()
        .table("messages")
        .select("id,role,content,citations,metadata,created_at,updated_at")
        .eq("conversation_id", conversation_id)
        .eq("user_id", user_id)
        .order("created_at")
        .execute()
    )
    return {**conversation, "messages": messages.data or []}


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: str,
    payload: NewMessageRequest,
    user=Depends(get_current_user),
):
    user_id = str(user.id)
    conversation = require_owned_row("conversations", conversation_id, user_id)
    return _chat_reply(conversation, payload.content.strip(), user_id)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, user=Depends(get_current_user)):
    user_id = str(user.id)
    require_owned_row("conversations", conversation_id, user_id)
    database().table("conversations").delete().eq("id", conversation_id).eq(
        "user_id", user_id
    ).execute()
    return Response(status_code=204)


@router.post("/chat")
def legacy_chat(payload: LegacyChatRequest, user=Depends(get_current_user)):
    user_id = str(user.id)
    conversation = require_owned_row("conversations", payload.conversation_id, user_id)
    if str(conversation.get("agent_id")) != payload.agent_id:
        raise HTTPException(status_code=400, detail="对话与智能体不匹配")
    return _chat_reply(conversation, payload.message.strip(), user_id)


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


@router.get("/knowledge/status")
def knowledge_status(user=Depends(get_current_user)):
    user_id = str(user.id)
    try:
        collections = (
            database()
            .table("kb_collections")
            .select("id,user_id,is_public", count="exact")
            .or_(f"is_public.eq.true,user_id.eq.{user_id}")
            .execute()
        )
        collection_rows = collections.data or []
        visible_ids = [row["id"] for row in collection_rows]
        if visible_ids:
            documents = (
                database()
                .table("kb_documents")
                .select("id", count="exact")
                .in_("collection_id", visible_ids)
                .execute()
            )
            chunks = (
                database()
                .table("kb_chunks")
                .select("id", count="exact")
                .in_("collection_id", visible_ids)
                .execute()
            )
            document_count = documents.count or len(documents.data or [])
            chunk_count = chunks.count or len(chunks.data or [])
        else:
            document_count = 0
            chunk_count = 0
    except Exception:
        return {
            "ready": False,
            "migration_required": True,
            "migration": "008_knowledge_base.sql",
            "collections": 0,
            "documents": 0,
            "chunks": 0,
            "embedding_enabled": bool(os.getenv("EMBEDDING_API_KEY")),
        }
    return {
        "ready": True,
        "migration_required": False,
        "collections": collections.count or len(collection_rows),
        "documents": document_count,
        "chunks": chunk_count,
        "owned_collections": sum(
            str(row.get("user_id")) == user_id for row in collection_rows
        ),
        "public_collections": sum(
            bool(row.get("is_public")) for row in collection_rows
        ),
        "embedding_enabled": bool(os.getenv("EMBEDDING_API_KEY")),
        "retrieval": "hybrid"
        if os.getenv("EMBEDDING_API_KEY")
        else "full-text",
    }


@router.get("/knowledge/collections")
def list_knowledge_collections(user=Depends(get_current_user)):
    user_id = str(user.id)
    try:
        result = (
            database()
            .table("kb_collections")
            .select(
                "id,user_id,name,description,is_public,document_count,metadata,"
                "created_at,updated_at"
            )
            .or_(f"is_public.eq.true,user_id.eq.{user_id}")
            .order("updated_at", desc=True)
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=409,
            detail="知识库表尚未部署，请先执行迁移 008_knowledge_base.sql",
        ) from None
    return {"items": result.data or [], "total": len(result.data or [])}


@router.post("/knowledge/collections", status_code=201)
def create_knowledge_collection(
    payload: KnowledgeCollectionRequest,
    user=Depends(get_current_user),
):
    user_id = str(user.id)
    profile = get_or_create_profile(user)
    if payload.is_public and profile.get("role") != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以创建公共知识库")
    try:
        result = (
            database()
            .table("kb_collections")
            .insert(
                {
                    "user_id": user_id,
                    "name": payload.name.strip(),
                    "description": (payload.description or "").strip() or None,
                    "is_public": payload.is_public,
                }
            )
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=409,
            detail="创建知识库失败；请确认迁移 008 已执行且名称未重复",
        ) from None
    collection = _first(result)
    if not collection:
        raise HTTPException(status_code=500, detail="创建知识库失败")
    record_activity(
        user_id,
        "knowledge",
        "创建知识库",
        collection["name"],
        entity_type="kb_collection",
        entity_id=collection["id"],
    )
    return collection


@router.patch("/knowledge/collections/{collection_id}")
def update_knowledge_collection(
    collection_id: str,
    payload: KnowledgeCollectionUpdateRequest,
    user=Depends(get_current_user),
):
    collection = _require_writable_kb_collection(collection_id, user)
    changes = payload.model_dump(exclude_none=True)
    if changes.get("name"):
        changes["name"] = changes["name"].strip()
    if "description" in changes:
        changes["description"] = (changes["description"] or "").strip() or None
    if changes.get("is_public"):
        profile = get_or_create_profile(user)
        if profile.get("role") != "admin":
            raise HTTPException(status_code=403, detail="只有管理员可以发布公共知识库")
    if not changes:
        return collection
    try:
        result = (
            database()
            .table("kb_collections")
            .update(changes)
            .eq("id", collection_id)
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=409, detail="更新失败，请检查知识库名称是否重复") from None
    collection = _first(result)
    if not collection:
        raise HTTPException(status_code=404, detail="知识库集合不存在")
    return collection


@router.delete("/knowledge/collections/{collection_id}", status_code=204)
def delete_knowledge_collection(
    collection_id: str,
    user=Depends(get_current_user),
):
    _require_writable_kb_collection(collection_id, user)
    documents = (
        database()
        .table("kb_documents")
        .select("storage_path")
        .eq("collection_id", collection_id)
        .execute()
        .data
        or []
    )
    paths = [row["storage_path"] for row in documents if row.get("storage_path")]
    if paths:
        try:
            database().storage.from_("knowledge-base").remove(paths)
        except Exception:
            raise HTTPException(
                status_code=409,
                detail="文件清理失败，知识库尚未删除，请稍后重试",
            ) from None
    database().table("kb_collections").delete().eq("id", collection_id).execute()
    return Response(status_code=204)


@router.get("/knowledge/documents")
def list_knowledge_documents(
    collection_id: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    user=Depends(get_current_user),
):
    user_id = str(user.id)
    if collection_id:
        visible_collections = [
            _require_visible_kb_collection(collection_id, user_id)
        ]
    else:
        try:
            visible_collections = (
                database()
                .table("kb_collections")
                .select("id")
                .or_(f"is_public.eq.true,user_id.eq.{user_id}")
                .execute()
                .data
                or []
            )
        except Exception:
            raise HTTPException(
                status_code=409,
                detail="知识库表尚未部署，请先执行迁移 008_knowledge_base.sql",
            ) from None
    visible_collection_ids = [row["id"] for row in visible_collections]
    if not visible_collection_ids:
        return {
            "items": [],
            "page": page,
            "limit": limit,
            "total": 0,
        }
    query = (
        database()
        .table("kb_documents")
        .select(
            "id,collection_id,title,source_type,source_url,file_name,mime_type,"
            "file_size,checksum,status,chunk_count,character_count,metadata,"
            "created_at,updated_at",
            count="exact",
        )
        .in_("collection_id", visible_collection_ids)
    )
    try:
        result = (
            query.order("updated_at", desc=True)
            .range((page - 1) * limit, page * limit - 1)
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=409,
            detail="知识库表尚未部署，请先执行迁移 008_knowledge_base.sql",
        ) from None
    return {
        "items": result.data or [],
        "page": page,
        "limit": limit,
        "total": result.count if result.count is not None else len(result.data or []),
    }


@router.get("/knowledge/documents/{document_id}")
def get_knowledge_document(
    document_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    user=Depends(get_current_user),
):
    user_id = str(user.id)
    document_result = (
        database()
        .table("kb_documents")
        .select(
            "id,collection_id,title,source_type,source_url,file_name,mime_type,"
            "file_size,checksum,status,chunk_count,character_count,metadata,"
            "created_at,updated_at"
        )
        .eq("id", document_id)
        .limit(1)
        .execute()
    )
    document = _first(document_result)
    if not document:
        raise HTTPException(status_code=404, detail="知识库文档不存在")
    _require_visible_kb_collection(document["collection_id"], user_id)
    chunks = (
        database()
        .table("kb_chunks")
        .select("id,chunk_index,title,content,token_count,metadata,created_at", count="exact")
        .eq("document_id", document_id)
        .order("chunk_index")
        .range((page - 1) * limit, page * limit - 1)
        .execute()
    )
    return {
        **document,
        "chunks": chunks.data or [],
        "chunk_page": page,
        "chunk_total": chunks.count if chunks.count is not None else len(chunks.data or []),
    }


@router.post("/knowledge/documents/upload", status_code=201)
async def upload_knowledge_document(
    file: UploadFile = File(...),
    collection_id: str | None = Form(default=None),
    title: str | None = Form(default=None),
    user=Depends(get_current_user),
):
    user_id = str(user.id)
    collection = (
        _require_writable_kb_collection(collection_id, user)
        if collection_id
        else _default_kb_collection(user_id)
    )
    max_bytes = int(os.getenv("MAX_KB_UPLOAD_MB", "25")) * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if not content or len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"知识库文件为空或超过 {max_bytes // 1024 // 1024}MB",
        )
    file_name = file.filename or "knowledge-document"
    try:
        extracted = extract_knowledge_text(content, file_name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    text = extracted["text"].strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail="未提取到文本；扫描版 PDF 请先执行 OCR",
        )
    max_chars = int(os.getenv("MAX_KB_EXTRACTED_CHARS", "2000000"))
    was_truncated = len(text) > max_chars
    text = text[:max_chars]

    checksum = sha256_bytes(content)
    duplicate = (
        database()
        .table("kb_documents")
        .select("*")
        .eq("collection_id", collection["id"])
        .eq("checksum", checksum)
        .limit(1)
        .execute()
    )
    existing = _first(duplicate)
    if existing:
        return {**existing, "duplicate": True}

    storage_path = (
        f"{user_id}/{collection['id']}/{uuid.uuid4()}-{safe_kb_filename(file_name)}"
    )
    try:
        database().storage.from_("knowledge-base").upload(
            storage_path,
            content,
            file_options={
                "content-type": file.content_type or "application/octet-stream",
                "upsert": "false",
            },
        )
    except Exception:
        raise HTTPException(
            status_code=409,
            detail="知识库文件桶尚未部署或上传失败，请先执行迁移 008",
        ) from None

    try:
        result_document = _store_kb_text_document(
            user_id=user_id,
            collection_id=collection["id"],
            title=title or extracted["title"] or Path(file_name).stem,
            text=text,
            source_type=extracted["source_type"],
            storage_path=storage_path,
            file_name=file_name[:500],
            mime_type=file.content_type or "application/octet-stream",
            file_size=len(content),
            checksum=checksum,
            metadata={
                "page_count": extracted.get("page_count"),
                "truncated": was_truncated,
            },
        )
    except Exception:
        persisted = (
            database()
            .table("kb_documents")
            .select("id")
            .eq("collection_id", collection["id"])
            .eq("checksum", checksum)
            .limit(1)
            .execute()
        )
        if not persisted.data:
            try:
                database().storage.from_("knowledge-base").remove([storage_path])
            except Exception:
                pass
        raise

    record_activity(
        user_id,
        "knowledge",
        "导入知识文档",
        result_document["title"],
        entity_type="kb_document",
        entity_id=result_document["id"],
        metadata={"chunks": result_document.get("chunk_count", 0)},
    )
    return result_document


@router.post("/knowledge/documents/text", status_code=201)
def create_knowledge_text_document(
    payload: KnowledgeTextDocumentRequest,
    user=Depends(get_current_user),
):
    user_id = str(user.id)
    collection = (
        _require_writable_kb_collection(payload.collection_id, user)
        if payload.collection_id
        else _default_kb_collection(user_id)
    )
    text = payload.content.strip()
    checksum = sha256_bytes(text.encode("utf-8"))
    duplicate = (
        database()
        .table("kb_documents")
        .select("*")
        .eq("collection_id", collection["id"])
        .eq("checksum", checksum)
        .limit(1)
        .execute()
    )
    existing = _first(duplicate)
    if existing:
        return {**existing, "duplicate": True}
    document = _store_kb_text_document(
        user_id=user_id,
        collection_id=collection["id"],
        title=payload.title.strip(),
        text=text,
        source_type="note",
        source_url=payload.source_url,
        checksum=checksum,
        metadata={"created_from": "editor"},
    )
    record_activity(
        user_id,
        "knowledge",
        "新建知识笔记",
        document["title"],
        entity_type="kb_document",
        entity_id=document["id"],
        metadata={"chunks": document.get("chunk_count", 0)},
    )
    return document


@router.delete("/knowledge/documents/{document_id}", status_code=204)
def delete_knowledge_document(document_id: str, user=Depends(get_current_user)):
    document_result = (
        database()
        .table("kb_documents")
        .select("*")
        .eq("id", document_id)
        .limit(1)
        .execute()
    )
    document = _first(document_result)
    if not document:
        raise HTTPException(status_code=404, detail="知识库文档不存在")
    _require_writable_kb_collection(document["collection_id"], user)
    storage_path = document.get("storage_path")
    if storage_path:
        try:
            database().storage.from_("knowledge-base").remove([storage_path])
        except Exception:
            raise HTTPException(
                status_code=409,
                detail="原文件清理失败，文档尚未删除，请稍后重试",
            ) from None
    database().table("kb_documents").delete().eq("id", document_id).execute()
    return Response(status_code=204)


@router.post("/knowledge/search")
def search_knowledge_base(
    payload: KnowledgeSearchRequest,
    user=Depends(get_current_user),
):
    rows = _search_knowledge_base(
        query=payload.query.strip(),
        user_id=str(user.id),
        collection_id=payload.collection_id,
        top_k=payload.top_k,
    )
    retrieval_mode = (
        "hybrid" if os.getenv("EMBEDDING_API_KEY") else "full-text"
    )
    retrieval_id = _record_kb_retrieval(
        user_id=str(user.id),
        query=payload.query.strip(),
        rows=rows,
        collection_id=payload.collection_id,
        answer=None,
        retrieval_mode=retrieval_mode,
    )
    return {
        "query": payload.query,
        "items": rows,
        "total": len(rows),
        "retrieval": retrieval_mode,
        "retrieval_id": retrieval_id,
    }


@router.post("/knowledge/answer")
def answer_from_knowledge_base(
    payload: KnowledgeAnswerRequest,
    user=Depends(get_current_user),
):
    rows = _search_knowledge_base(
        query=payload.query.strip(),
        user_id=str(user.id),
        collection_id=payload.collection_id,
        top_k=payload.top_k,
    )
    citations = [
        {
            "index": index,
            "document_id": row.get("document_id"),
            "chunk_id": row.get("chunk_id"),
            "title": row.get("document_title") or row.get("title") or "未命名文档",
            "chunk_index": row.get("chunk_index"),
            "source_url": row.get("source_url"),
            "file_name": row.get("file_name"),
            "score": row.get("score"),
            "excerpt": (row.get("content") or "")[:500],
        }
        for index, row in enumerate(rows, start=1)
    ]
    if not rows:
        retrieval_id = _record_kb_retrieval(
            user_id=str(user.id),
            query=payload.query.strip(),
            rows=[],
            collection_id=payload.collection_id,
            answer="当前知识库没有检索到足以回答该问题的内容。",
            retrieval_mode=(
                "hybrid" if os.getenv("EMBEDDING_API_KEY") else "full-text"
            ),
        )
        return {
            "query": payload.query,
            "answer": "当前知识库没有检索到足以回答该问题的内容。",
            "citations": [],
            "retrieval_id": retrieval_id,
        }

    if not payload.include_answer:
        retrieval_id = _record_kb_retrieval(
            user_id=str(user.id),
            query=payload.query.strip(),
            rows=rows,
            collection_id=payload.collection_id,
            answer=None,
            retrieval_mode=(
                "hybrid" if os.getenv("EMBEDDING_API_KEY") else "full-text"
            ),
        )
        return {
            "query": payload.query,
            "answer": None,
            "citations": citations,
            "retrieval_id": retrieval_id,
        }

    if os.getenv("LLM_API_KEY"):
        context = "\n\n".join(
            f"[{index}] {row.get('document_title') or '未命名文档'}\n"
            f"{(row.get('content') or '')[:1800]}"
            for index, row in enumerate(rows[:12], start=1)
        )
        answer = call_default_llm(
            system_prompt=(
                "你是科研知识库问答助手。只能依据给定资料回答；"
                "每个实质性结论必须使用 [数字] 标注来源。"
                "资料不足时明确说明，不得编造引用。"
            ),
            user_message=f"问题：{payload.query}\n\n检索资料：\n{context}",
        )
        valid_citation_indexes = set(range(1, len(citations) + 1))
        answer = re.sub(
            r"\[(\d+)\]",
            lambda match: (
                match.group(0)
                if int(match.group(1)) in valid_citation_indexes
                else "[来源未验证]"
            ),
            answer,
        )
    else:
        answer = (
            "尚未配置问答模型，以下是知识库中最相关的检索片段：\n\n"
            + "\n\n".join(
                f"[{item['index']}] {item['title']}：{item['excerpt']}"
                for item in citations[:5]
            )
        )
    record_activity(
        str(user.id),
        "knowledge",
        "知识库问答",
        payload.query[:200],
        metadata={"citation_count": len(citations)},
    )
    retrieval_id = _record_kb_retrieval(
        user_id=str(user.id),
        query=payload.query.strip(),
        rows=rows,
        collection_id=payload.collection_id,
        answer=answer,
        retrieval_mode=(
            "hybrid" if os.getenv("EMBEDDING_API_KEY") else "full-text"
        ),
    )
    return {
        "query": payload.query,
        "answer": answer,
        "citations": citations,
        "retrieval_id": retrieval_id,
    }


# ---------------------------------------------------------------------------
# Research artifacts, public catalog, knowledge graph, dashboard
# ---------------------------------------------------------------------------


@router.post("/research/decompose")
def decompose_research(payload: ResearchDecomposeRequest, user=Depends(get_current_user)):
    user_id = str(user.id)
    nodes = [
        {
            "id": str(uuid.uuid4()),
            "question": f"如何定义“{payload.direction[:80]}”的核心变量与可验证目标？",
            "feasibility": "high",
            "datasets": [],
            "papers": [],
        },
        {
            "id": str(uuid.uuid4()),
            "question": "哪些公开数据集、基线方法和评价指标适合该问题？",
            "feasibility": "high",
            "datasets": [],
            "papers": [],
        },
        {
            "id": str(uuid.uuid4()),
            "question": "如何设计对照实验、消融实验并识别主要风险？",
            "feasibility": "medium",
            "datasets": [],
            "papers": [],
        },
    ]
    content = {"core_question": payload.direction, "sub_questions": nodes}
    artifact = _save_artifact(
        user_id, "research-decomposition", payload.direction[:200], payload.model_dump(), content
    )
    record_activity(
        user_id,
        "research",
        "拆解问题",
        payload.direction[:200],
        entity_type="artifact",
        entity_id=artifact["id"],
    )
    return {"id": artifact["id"], **content}


@router.get("/research/{artifact_id}")
def get_research(artifact_id: str, user=Depends(get_current_user)):
    artifact = require_owned_row("research_artifacts", artifact_id, str(user.id))
    return {"id": artifact["id"], **(artifact.get("content") or {})}


@router.post("/experiments/generate-roadmap")
def generate_roadmap(payload: ExperimentRoadmapRequest, user=Depends(get_current_user)):
    user_id = str(user.id)
    objective = payload.objective or f"围绕研究问题 {payload.question_id} 建立可复现实验"
    repositories = (
        database()
        .table("catalog_resources")
        .select("id,title,url,repository_url,description,metadata")
        .eq("resource_type", "repository")
        .eq("is_public", True)
        .limit(3)
        .execute()
        .data
        or []
    )
    datasets = (
        database()
        .table("catalog_resources")
        .select("title,url,description,metadata")
        .eq("resource_type", "dataset")
        .eq("is_public", True)
        .limit(3)
        .execute()
        .data
        or []
    )
    content = {
        "objective": objective,
        "steps": [
            {"step": 1, "task": "确定假设与指标", "details": "固定研究问题、输入输出和成功标准", "estimated_days": 2, "status": "pending"},
            {"step": 2, "task": "准备数据与基线", "details": "记录版本、许可、划分方式和预处理", "estimated_days": 5, "status": "pending"},
            {"step": 3, "task": "实现与复现", "details": "先复现基线，再实现改进方法", "estimated_days": 10, "status": "pending"},
            {"step": 4, "task": "对照与消融", "details": "运行多随机种子并保存原始结果", "estimated_days": 7, "status": "pending"},
            {"step": 5, "task": "分析与归档", "details": "解释结果、记录限制并整理复现说明", "estimated_days": 4, "status": "pending"},
        ],
        "baselines": [
            {
                "name": row["title"],
                "paper_id": row["id"],
                "github_url": row.get("repository_url") or row["url"],
                "description": row.get("description"),
            }
            for row in repositories
        ],
        "datasets": [
            {
                "name": row["title"],
                "size": str((row.get("metadata") or {}).get("size", "见来源说明")),
                "language": str((row.get("metadata") or {}).get("language", "多语言")),
                "url": row["url"],
                "description": row.get("description"),
            }
            for row in datasets
        ],
        "tools": ["Python", "Git", "Docker", "实验追踪工具"],
    }
    artifact = _save_artifact(
        user_id, "experiment-roadmap", objective[:200], payload.model_dump(), content
    )
    record_activity(user_id, "experiment", "生成实验路线", objective[:200], entity_type="artifact", entity_id=artifact["id"])
    return {"id": artifact["id"], **content}


@router.get("/experiments/{artifact_id}")
def get_roadmap(artifact_id: str, user=Depends(get_current_user)):
    artifact = require_owned_row("research_artifacts", artifact_id, str(user.id))
    return {"id": artifact["id"], **(artifact.get("content") or {})}


@router.post("/code/analyze-repo")
def analyze_repository(payload: RepoAnalysisRequest, user=Depends(get_current_user)):
    match = re.match(r"^https?://github\.com/([^/]+)/([^/#?]+)", payload.repo_url.strip())
    if not match:
        raise HTTPException(status_code=400, detail="请输入有效的 GitHub 仓库地址")
    owner, repo = match.groups()
    repo = repo.removesuffix(".git")
    content = {
        "repo_name": repo,
        "repo_url": f"https://github.com/{owner}/{repo}",
        "language": "Unknown",
        "stars": 0,
        "description": "仓库已登记，连接代码复现智能体后可进一步分析目录与依赖。",
        "file_tree": [],
        "dependencies": [],
        "steps": [
            {"step": 1, "instruction": "阅读 README、LICENSE 与发布版本", "checked": False},
            {"step": 2, "instruction": "在隔离环境安装锁定依赖", "checked": False},
            {"step": 3, "instruction": "使用最小样例验证入口命令", "checked": False},
        ],
    }
    artifact = _save_artifact(str(user.id), "code-reproduction", f"{owner}/{repo}", payload.model_dump(), content)
    record_activity(str(user.id), "code", "登记复现仓库", f"{owner}/{repo}", entity_type="artifact", entity_id=artifact["id"])
    return {"id": artifact["id"], **content}


@router.get("/code/{artifact_id}")
def get_repository_analysis(artifact_id: str, user=Depends(get_current_user)):
    artifact = require_owned_row("research_artifacts", artifact_id, str(user.id))
    return {"id": artifact["id"], **(artifact.get("content") or {})}


@router.post("/code/diagnose")
def diagnose_repository(payload: DiagnoseRequest, user=Depends(get_current_user)):
    require_owned_row("research_artifacts", payload.repo_id, str(user.id))
    return {
        "diagnosis": "错误日志已保存。建议先确认首个异常、依赖版本、运行目录和环境变量，再使用代码复现智能体进行语义诊断。",
        "error_excerpt": payload.error_log[:1000],
    }


def _read_tabular(file_name: str, content: bytes) -> list[dict[str, Any]]:
    lower = file_name.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig")
        return list(csv.DictReader(StringIO(text)))[:10_000]
    if lower.endswith(".json"):
        value = json.loads(content.decode("utf-8"))
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise ValueError("JSON 必须是对象数组")
        return value[:10_000]
    if lower.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        sheet = load_workbook(BytesIO(content), read_only=True, data_only=True).active
        rows = sheet.iter_rows(values_only=True)
        headers = [str(value) if value is not None else "" for value in next(rows)]
        return [dict(zip(headers, row)) for _, row in zip(range(10_000), rows)]
    raise ValueError("只支持 CSV、JSON 或 XLSX")


@router.post("/results/analyze")
async def analyze_results(
    file: UploadFile = File(...),
    config: str | None = Form(default=None),
    user=Depends(get_current_user),
):
    raw = await file.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="结果文件超过 20MB")
    try:
        rows = _read_tabular(file.filename or "results.csv", raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法读取结果文件：{exc}") from None
    numeric: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            try:
                number = float(value)
                if math.isfinite(number):
                    numeric.setdefault(str(key), []).append(number)
            except (TypeError, ValueError):
                continue
    stats = []
    for metric, values in numeric.items():
        mean = statistics.fmean(values)
        std = statistics.stdev(values) if len(values) > 1 else 0.0
        margin = 1.96 * std / math.sqrt(len(values)) if values else 0.0
        stats.append(
            {
                "metric": metric,
                "mean": mean,
                "std": std,
                "min": min(values),
                "max": max(values),
                "ci95": [mean - margin, mean + margin],
            }
        )
    result_content = {
        "charts": [],
        "stats": stats,
        "interpretation": f"已读取 {len(rows)} 行数据和 {len(numeric)} 个数值字段。",
        "suggestions": ["核对数据划分与随机种子", "报告均值、标准差和样本量", "保存原始结果与运行配置"],
    }
    artifact = _save_artifact(
        str(user.id),
        "result-analysis",
        file.filename or "结果分析",
        {"file_name": file.filename, "config": json.loads(config) if config else {}},
        result_content,
    )
    record_activity(str(user.id), "result", "分析实验结果", file.filename or "结果文件", entity_type="artifact", entity_id=artifact["id"])
    return {"id": artifact["id"], **result_content}


@router.get("/results/{artifact_id}")
def get_result_analysis(artifact_id: str, user=Depends(get_current_user)):
    artifact = require_owned_row("research_artifacts", artifact_id, str(user.id))
    return {"id": artifact["id"], **(artifact.get("content") or {})}


@router.get("/resources")
def list_resources(
    resource_type: str | None = None,
    topic: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    query = (
        database()
        .table("catalog_resources")
        .select("*", count="exact")
        .eq("is_public", True)
    )
    if resource_type:
        query = query.eq("resource_type", resource_type)
    if topic:
        query = query.contains("topics", [topic])
    result = query.order("is_featured", desc=True).order("title").limit(limit).execute()
    return {"items": result.data or [], "total": result.count or len(result.data or [])}


@router.get("/kg/explore")
def explore_knowledge_graph(
    query: str | None = None,
    nodeId: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    user=Depends(get_current_user),
):
    user_id = str(user.id)
    nodes_query = database().table("knowledge_nodes").select(
        "id,label,category,description,is_public,user_id"
    ).or_(f"is_public.eq.true,user_id.eq.{user_id}")
    if query:
        nodes_query = nodes_query.ilike("label", f"%{query}%")
    if nodeId:
        nodes_query = nodes_query.eq("id", nodeId)
    nodes = nodes_query.limit(limit).execute().data or []
    node_ids = {row["id"] for row in nodes}
    edges = (
        database()
        .table("knowledge_edges")
        .select("source_node_id,target_node_id,relation,strength,is_public,user_id")
        .or_(f"is_public.eq.true,user_id.eq.{user_id}")
        .limit(limit * 3)
        .execute()
        .data
        or []
    )
    visible_edges = [
        {
            "source": edge["source_node_id"],
            "target": edge["target_node_id"],
            "relation": edge["relation"],
            "strength": float(edge.get("strength") or 1),
        }
        for edge in edges
        if edge["source_node_id"] in node_ids and edge["target_node_id"] in node_ids
    ]
    return {
        "nodes": [
            {key: row[key] for key in ("id", "label", "category", "description")}
            for row in nodes
        ],
        "edges": visible_edges,
    }


@router.get("/kg/search")
def search_knowledge_nodes(
    q: str = Query(min_length=1, max_length=200),
    user=Depends(get_current_user),
):
    result = (
        database()
        .table("knowledge_nodes")
        .select("id,label,category,description")
        .or_(f"is_public.eq.true,user_id.eq.{str(user.id)}")
        .ilike("label", f"%{q}%")
        .limit(30)
        .execute()
    )
    return result.data or []


@router.get("/dashboard/summary")
def dashboard_summary(user=Depends(get_current_user)):
    user_id = str(user.id)
    papers = _safe_data(
        lambda: database()
        .table("papers")
        .select(PAPER_COLUMNS)
        .eq("user_id", user_id)
        .order("uploaded_at", desc=True)
        .limit(5)
        .execute()
    )
    all_papers = _safe_data(
        lambda: database()
        .table("papers")
        .select("id,is_favorite")
        .eq("user_id", user_id)
        .execute()
    )
    conversations = _safe_data(
        lambda: database()
        .table("conversations")
        .select("id")
        .eq("user_id", user_id)
        .execute()
    )
    artifacts = _safe_data(
        lambda: database()
        .table("research_artifacts")
        .select("id,artifact_type,status")
        .eq("user_id", user_id)
        .execute()
    )
    activities = _safe_data(
        lambda: database()
        .table("activities")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(8)
        .execute()
    )
    catalog = _safe_data(
        lambda: database()
        .table("catalog_resources")
        .select("topics")
        .eq("is_public", True)
        .execute()
    )
    topics = Counter(topic for row in catalog for topic in (row.get("topics") or []))
    return {
        "stats": {
            "paper_count": len(all_papers),
            "conversation_count": len(conversations),
            "favorite_count": sum(bool(row.get("is_favorite")) for row in all_papers),
            "artifact_count": len(artifacts),
            "experiment_count": sum(row.get("artifact_type") == "experiment-roadmap" for row in artifacts),
            "code_reproduction_count": sum(row.get("artifact_type") == "code-reproduction" for row in artifacts),
        },
        "recent_papers": papers,
        "recent_activities": activities,
        "trending": [
            {"title": topic, "papers": count, "trend": "公开目录"}
            for topic, count in topics.most_common(6)
        ],
    }
