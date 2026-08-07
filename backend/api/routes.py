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
    local_demo_login,
    local_demo_mode_enabled,
    local_demo_token,
    record_activity,
    require_owned_row,
)
from api.schemas import (
    AgentKnowledgeAskRequest,
    DashboardChatRequest,
    CreateConversationRequest,
    DiagnoseRequest,
    ExperimentRoadmapRequest,
    KnowledgeQueryRequest,
    LegacyChatRequest,
    LoginRequest,
    NewMessageRequest,
    RegisterRequest,
    RepoAnalysisRequest,
    ResearchDecomposeRequest,
    UpdateProfileRequest,
)
from services.finetuned_model_service import (
    call_finetuned_model,
    model_service_status,
)
from services.supabase_service import get_supabase_auth_client
from services.xunfei_knowledge_base_service import (
    XunfeiKnowledgeBaseError,
    get_xunfei_knowledge_status,
    is_xunfei_knowledge_base_configured,
    search_xunfei_knowledge_base,
)

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


def _upstream_error(service_name: str) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail=f"{service_name}暂时不可用，请稍后重试",
    )


def _search_external_knowledge(
    message: str,
    *,
    top_n: int,
) -> list[dict[str, Any]]:
    try:
        return search_xunfei_knowledge_base(message.strip(), top_n=top_n)
    except (XunfeiKnowledgeBaseError, ValueError):
        raise _upstream_error("星火知识库") from None
    except Exception:
        # Never expose provider response bodies, request URLs, or credentials.
        raise _upstream_error("星火知识库") from None


def _knowledge_context(citations: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    remaining = 24_000
    for position, citation in enumerate(citations[:10], start=1):
        excerpt = str(citation.get("excerpt") or "").strip()
        if not excerpt or remaining <= 0:
            continue
        excerpt = excerpt[: min(3_000, remaining)]
        remaining -= len(excerpt)
        index = citation.get("index") or position
        title = citation.get("title") or citation.get("file_name") or "未命名论文"
        blocks.append(f"[{index}] {title}\n{excerpt}")
    return "\n\n".join(blocks)


def _evidence_only_answer(citations: list[dict[str, Any]]) -> str:
    if not citations:
        return "当前星火知识库没有检索到足以回答该问题的论文证据。"
    excerpts = []
    for position, citation in enumerate(citations[:5], start=1):
        index = citation.get("index") or position
        title = citation.get("title") or citation.get("file_name") or "未命名论文"
        excerpt = str(citation.get("excerpt") or "").strip()[:800]
        excerpts.append(f"[{index}] {title}：{excerpt}")
    return "当前未启用 MaaS 生成模型，以下是可核验的相关论文原文摘录：\n\n" + "\n\n".join(
        excerpts
    )


def _knowledge_system_prompt(
    base_prompt: str,
    citations: list[dict[str, Any]],
    *,
    knowledge_requested: bool,
) -> str:
    prompt = base_prompt.strip()
    if citations:
        return (
            f"{prompt}\n\n"
            "你必须仅依据下方“检索证据”回答涉及事实的内容。"
            "每个实质性结论都使用 [数字] 标注来源；证据不足时明确说明，"
            "不得编造论文、作者、数据或引用。\n\n"
            f"检索证据：\n{_knowledge_context(citations)}"
        )
    if knowledge_requested:
        return (
            f"{prompt}\n\n"
            "本次星火知识库检索没有返回证据。请明确说明证据不足，"
            "不要编造论文内容或引用。"
        )
    return prompt


def _call_maas(
    messages: list[dict[str, str]],
    *,
    system_prompt: str,
) -> str:
    try:
        return call_finetuned_model(
            messages=[
                {"role": "system", "content": system_prompt},
                *messages,
            ]
        )
    except Exception:
        # The upstream SDK may include request details in exception strings.
        raise _upstream_error("对话模型") from None


def _agent_knowledge_answer(
    *,
    agent: dict[str, Any],
    message: str,
    top_k: int,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    citations = _search_external_knowledge(message, top_n=top_k)
    model_status = model_service_status()
    model = model_status.get("model") if model_status.get("available") else None
    if citations and model_status.get("available"):
        conversation = history or [{"role": "user", "content": message}]
        reply = _call_maas(
            conversation,
            system_prompt=_knowledge_system_prompt(
                str(
                    agent.get("system_prompt")
                    or "你是 SciPilot 科研智能体，请提供严谨、清晰且可复核的回答。"
                ),
                citations,
                knowledge_requested=True,
            ),
        )
        response_mode = "xunfei-rag-maas"
    else:
        reply = _evidence_only_answer(citations)
        response_mode = "xunfei-evidence-only"
    return {
        "reply": reply,
        "citations": citations,
        "knowledge_used": bool(citations),
        "retrieval_mode": "xunfei-vector-search",
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

    history_result = (
        database()
        .table("messages")
        .select("role,content,created_at")
        .eq("conversation_id", conversation["id"])
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    history = [
        {
            "role": str(item.get("role")),
            "content": str(item.get("content") or "").strip(),
        }
        for item in reversed(history_result.data or [])
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    if not history or history[-1]["role"] != "user":
        history.append({"role": "user", "content": content})

    answer = _agent_knowledge_answer(
        agent=agent,
        message=content,
        top_k=8,
        history=history,
    )
    assistant = (
        database()
        .table("messages")
        .insert(
            {
                "conversation_id": conversation["id"],
                "user_id": user_id,
                "agent_id": agent["id"],
                "role": "assistant",
                "content": answer["reply"],
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
    saved_message = _first(assistant)
    if not saved_message:
        raise HTTPException(status_code=500, detail="保存智能体回复失败")
    return {
        "reply": answer["reply"],
        "message": saved_message,
        "citations": answer["citations"],
        "knowledge_used": answer["knowledge_used"],
        "model": answer["model"],
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
    if local_demo_mode_enabled():
        demo_user = local_demo_login(payload.email, payload.password)
        if not demo_user:
            raise _auth_error()
        return {
            "user": format_user(demo_user, get_or_create_profile(demo_user)),
            "token": local_demo_token(),
        }
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
        top_k=payload.top_k,
    )
    record_activity(
        user_id,
        agent.get("category") or "agent",
        "智能体知识问答",
        message[:200],
        entity_type="agent",
        entity_id=agent["id"],
        metadata={
            "provider": "xunfei-chatdoc",
            "citation_count": len(answer["citations"]),
        },
    )
    return {
        "reply": answer["reply"],
        "citations": answer["citations"],
        "knowledge_used": answer["knowledge_used"],
        "model": answer["model"],
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
# External Spark knowledge base and dashboard MaaS chat
# ---------------------------------------------------------------------------


def _public_knowledge_status() -> dict[str, Any]:
    try:
        status = get_xunfei_knowledge_status()
    except XunfeiKnowledgeBaseError:
        raise _upstream_error("星火知识库") from None
    except Exception:
        raise _upstream_error("星火知识库") from None

    files = []
    for item in status.get("files") or []:
        files.append(
            {
                "file_id": item.get("fileId") or item.get("file_id"),
                "file_name": item.get("fileName") or item.get("file_name"),
                "status": item.get("fileStatus") or item.get("status") or "unknown",
                "extension": item.get("fileType") or item.get("extension"),
                "created_at": item.get("createTime") or item.get("created_at"),
            }
        )
    return {
        "provider": status.get("provider") or "xunfei-chatdoc",
        "configured": bool(status.get("configured")),
        "ready": bool(status.get("ready")),
        "repository_name": status.get("repository_name"),
        "document_count": int(status.get("document_count") or 0),
        "vectored_count": int(status.get("vectored_count") or 0),
        "files": files,
        "reason": (
            None
            if status.get("ready")
            else "星火知识库尚未完成服务端配置或远端仓库尚未就绪"
        ),
    }


@router.get("/knowledge/status")
@router.get("/knowledge/xunfei/status")
def knowledge_status(user=Depends(get_current_user)):
    return _public_knowledge_status()


@router.post("/knowledge/search")
def search_knowledge_base(
    payload: KnowledgeQueryRequest,
    user=Depends(get_current_user),
):
    query = payload.text
    citations = _search_external_knowledge(query, top_n=payload.top_n)
    record_activity(
        str(user.id),
        "knowledge",
        "星火知识库检索",
        query[:200],
        metadata={
            "provider": "xunfei-chatdoc",
            "citation_count": len(citations),
        },
    )
    return {
        "query": query,
        "citations": citations,
        "total": len(citations),
        "provider": "xunfei-chatdoc",
    }


@router.post("/knowledge/answer")
@router.post("/knowledge/xunfei/answer")
def answer_from_knowledge_base(
    payload: KnowledgeQueryRequest,
    user=Depends(get_current_user),
):
    query = payload.text
    citations = _search_external_knowledge(query, top_n=payload.top_n)
    status = model_service_status()
    model = status.get("model") if status.get("available") else None
    if citations and status.get("available"):
        answer = _call_maas(
            [{"role": "user", "content": query}],
            system_prompt=_knowledge_system_prompt(
                "你是 SciPilot 科研知识问答助手，回答应准确、简洁并可核验。",
                citations,
                knowledge_requested=True,
            ),
        )
    else:
        answer = _evidence_only_answer(citations)
    record_activity(
        str(user.id),
        "knowledge",
        "星火知识库问答",
        query[:200],
        metadata={
            "provider": "xunfei-chatdoc",
            "citation_count": len(citations),
            "model": model,
        },
    )
    return {
        "query": query,
        "answer": answer,
        "citations": citations,
        "total": len(citations),
        "provider": "xunfei-chatdoc",
        "model": model,
    }


@router.get("/dashboard/chat/status")
def dashboard_chat_status(user=Depends(get_current_user)):
    status = dict(model_service_status())
    # Keep the model control path independent from a slow ChatDoc repository.
    # The dedicated /knowledge/status endpoint performs the remote readiness
    # check; dashboard messages degrade safely if retrieval later fails.
    status["knowledge_available"] = is_xunfei_knowledge_base_configured()
    return status


@router.post("/dashboard/chat")
def dashboard_chat(
    payload: DashboardChatRequest,
    user=Depends(get_current_user),
):
    history = [
        {"role": item.role, "content": item.content.strip()}
        for item in payload.messages
    ]
    query = history[-1]["content"]
    knowledge_unavailable = False
    citations: list[dict[str, Any]] = []
    if payload.use_knowledge_base:
        try:
            citations = _search_external_knowledge(query, top_n=6)
        except HTTPException as exc:
            if exc.status_code != 502:
                raise
            # ChatDoc is an enhancement, not a prerequisite for MaaS chat.
            knowledge_unavailable = True
    status = model_service_status()
    if not status.get("available"):
        raise _upstream_error("对话模型")
    reply = _call_maas(
        history,
        system_prompt=_knowledge_system_prompt(
            (
                "你是 SciPilot 科研对话助手。请结合完整对话历史理解用户意图，"
                "使用清晰、严谨、适合科研工作的中文作答。"
            ),
            citations,
            knowledge_requested=payload.use_knowledge_base
            and not knowledge_unavailable,
        ),
    )
    record_activity(
        str(user.id),
        "dashboard",
        "模型对话",
        query[:200],
        metadata={
            "provider": "xunfei-maas",
            "knowledge_used": bool(citations),
            "citation_count": len(citations),
        },
    )
    return {
        "reply": reply,
        "citations": citations,
        "model": status.get("model"),
        "knowledge_used": bool(citations),
        "knowledge_unavailable": knowledge_unavailable,
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
