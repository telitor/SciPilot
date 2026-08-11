import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from services.finetuned_model_service import (
    call_finetuned_model,
    call_finetuned_model_with_metadata,
    is_finetuned_model_configured,
)
from services.xunfei_agent_service import (
    call_xunfei_agent_by_category,
    call_xunfei_agent_by_category_with_metadata,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")


def call_default_llm(system_prompt: str, user_message: str) -> str:
    """
    默认大模型调用。
    如果没有配置 LLM_API_KEY，则返回临时测试回复。
    """

    if not LLM_API_KEY:
        return (
            "这是 SciCopilot 后端的临时测试回复。"
            "当前智能体还没有接入真实模型。"
            f"你刚才发送的内容是：{user_message}"
        )

    client = OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL if LLM_BASE_URL else None,
    )

    response = client.chat.completions.create(
        model=LLM_MODEL or "gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_message,
            },
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content


def generate_reply(
    system_prompt: str,
    user_message: str,
    agent_category: str = "",
    user_id: str = "",
) -> str:
    """
    根据 agent 类型选择调用方式。

    paper-reading:
        调用讯飞星辰论文精读 Agent。

    其他类型:
        暂时调用默认 LLM 或 mock 回复。
    """

    professional_categories = {
        "paper-reading",
        "problem-decomposition",
        "project-planning",
        "result-interpretation",
        "code-reproduction",
    }
    if agent_category in professional_categories:
        agent_message = user_message
        if system_prompt.strip():
            agent_message = (
                f"【智能体职责】\n{system_prompt.strip()}\n\n"
                f"【用户请求】\n{user_message.strip()}"
            )
        return call_xunfei_agent_by_category(
            user_id=user_id,
            user_message=agent_message,
            agent_category=agent_category,
        )

    if is_finetuned_model_configured():
        return call_finetuned_model(
            system_prompt=system_prompt,
            user_message=user_message,
        )

    return call_default_llm(
        system_prompt=system_prompt,
        user_message=user_message,
    )


def generate_reply_with_metadata(
    system_prompt: str,
    user_message: str,
    agent_category: str = "",
    user_id: str = "",
    max_tokens: int | None = None,
) -> dict[str, object]:
    """Generate a reply plus privacy-safe usage metadata."""

    professional_categories = {
        "paper-reading",
        "problem-decomposition",
        "project-planning",
        "result-interpretation",
        "code-reproduction",
    }
    if agent_category in professional_categories:
        agent_message = user_message
        if system_prompt.strip():
            agent_message = (
                f"【智能体职责】\n{system_prompt.strip()}\n\n"
                f"【用户请求】\n{user_message.strip()}"
            )
        return call_xunfei_agent_by_category_with_metadata(
            user_id=user_id,
            user_message=agent_message,
            agent_category=agent_category,
            max_tokens=max_tokens,
        )

    if is_finetuned_model_configured():
        return call_finetuned_model_with_metadata(
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=max_tokens,
        )

    reply = call_default_llm(system_prompt, user_message)
    return {"text": reply, "usage": {}}
