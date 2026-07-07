from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from services.llm_service import generate_reply
from services.supabase_service import get_supabase_client

app = FastAPI(
    title="SciCopilot Backend",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase = get_supabase_client()


class CreateConversationRequest(BaseModel):
    agent_id: str
    title: Optional[str] = "新的对话"


class ChatRequest(BaseModel):
    conversation_id: str
    agent_id: str
    message: str


def get_current_user(authorization: str = Header(None)):
    """
    从请求头 Authorization 中读取 token：

    Authorization: Bearer 用户的 access_token

    然后调用 Supabase Auth 验证 token，拿到当前用户。
    """

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization format")

    token = authorization.replace("Bearer ", "").strip()

    try:
        user_response = supabase.auth.get_user(token)
        user = user_response.user

        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        return user

    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "SciCopilot Backend",
        "version": "v0.1",
    }


@app.get("/agents")
def get_agents():
    """
    获取公开智能体列表。

    第一版应该返回：
    - 论文精读助手
    - 代码解释助手
    - 项目规划助手
    """

    result = (
        supabase.table("agents")
        .select("id,name,description,category,is_public,created_at")
        .eq("is_public", True)
        .execute()
    )

    return result.data


@app.post("/conversations")
def create_conversation(
    payload: CreateConversationRequest,
    user=Depends(get_current_user),
):
    """
    创建一条新对话。

    前端点击某个智能体后，调用这个接口创建 conversation。
    """

    # 先检查 agent 是否存在
    agent_result = (
        supabase.table("agents")
        .select("id,name")
        .eq("id", payload.agent_id)
        .eq("is_public", True)
        .execute()
    )

    if not agent_result.data:
        raise HTTPException(status_code=404, detail="Agent not found")

    data = {
        "user_id": user.id,
        "agent_id": payload.agent_id,
        "title": payload.title or "新的对话",
    }

    result = supabase.table("conversations").insert(data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create conversation")

    return result.data[0]


@app.get("/conversations")
def list_conversations(user=Depends(get_current_user)):
    """
    获取当前用户自己的历史对话。
    """

    result = (
        supabase.table("conversations")
        .select("id,agent_id,title,created_at,updated_at")
        .eq("user_id", user.id)
        .order("updated_at", desc=True)
        .execute()
    )

    return result.data


@app.get("/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: str,
    user=Depends(get_current_user),
):
    """
    获取某个对话里的消息。

    必须先检查这个 conversation 是否属于当前用户。
    """

    conversation = (
        supabase.table("conversations")
        .select("id,user_id")
        .eq("id", conversation_id)
        .eq("user_id", user.id)
        .execute()
    )

    if not conversation.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = (
        supabase.table("messages")
        .select("id,role,content,created_at")
        .eq("conversation_id", conversation_id)
        .eq("user_id", user.id)
        .order("created_at")
        .execute()
    )

    return result.data


@app.post("/chat")
def chat(
    payload: ChatRequest,
    user=Depends(get_current_user),
):
    """
    发送消息并获取 AI 回复。

    核心流程：
    1. 检查 conversation 是否属于当前用户
    2. 检查 agent 是否存在
    3. 保存用户消息
    4. 调用大模型生成回复
    5. 保存 AI 回复
    6. 更新 conversation 时间
    7. 返回 AI 回复
    """

    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # 1. 检查 conversation 是否属于当前用户
    conversation = (
        supabase.table("conversations")
        .select("id,user_id,agent_id,title")
        .eq("id", payload.conversation_id)
        .eq("user_id", user.id)
        .execute()
    )

    if not conversation.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 2. 检查 agent 是否存在
    agent = (
        supabase.table("agents")
        .select("id,name,system_prompt")
        .eq("id", payload.agent_id)
        .eq("is_public", True)
        .execute()
    )

    if not agent.data:
        raise HTTPException(status_code=404, detail="Agent not found")

    system_prompt = agent.data[0]["system_prompt"]

    # 3. 保存用户消息
    user_message_result = supabase.table("messages").insert(
        {
            "conversation_id": payload.conversation_id,
            "user_id": user.id,
            "role": "user",
            "content": payload.message,
        }
    ).execute()

    if not user_message_result.data:
        raise HTTPException(status_code=500, detail="Failed to save user message")

    # 4. 调用大模型或临时测试回复
    try:
        reply = generate_reply(system_prompt, payload.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM call failed: {str(e)}")

    # 5. 保存 AI 回复
    assistant_message_result = supabase.table("messages").insert(
        {
            "conversation_id": payload.conversation_id,
            "user_id": user.id,
            "role": "assistant",
            "content": reply,
        }
    ).execute()

    if not assistant_message_result.data:
        raise HTTPException(status_code=500, detail="Failed to save assistant message")

    # 6. 更新 conversation
    # 这里会触发你前面创建的 updated_at trigger
    new_title = payload.message[:30]

    supabase.table("conversations").update(
        {
            "title": new_title,
        }
    ).eq("id", payload.conversation_id).eq("user_id", user.id).execute()

    # 7. 返回结果
    return {
        "reply": reply,
    }
