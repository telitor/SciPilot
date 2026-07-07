import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")


def generate_reply(system_prompt: str, user_message: str) -> str:
    """
    第一版先支持两种情况：

    1. 如果 .env 配置了 LLM_API_KEY，就调用真实大模型。
    2. 如果还没有配置 LLM_API_KEY，就返回一个临时测试回复，先保证接口流程跑通。
    """

    if not LLM_API_KEY:
        return (
            "这是 SciCopilot 后端的临时测试回复。"
            "目前 /chat 接口已经收到你的消息，并完成了后端流程测试。"
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