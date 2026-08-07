from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    username: str = Field(min_length=2, max_length=50)

    @field_validator("password")
    @classmethod
    def password_must_contain_letters_and_numbers(cls, value: str) -> str:
        if not any(char.isalpha() for char in value) or not any(
            char.isdigit() for char in value
        ):
            raise ValueError("Password must contain at least one letter and one number")
        return value


class UpdateProfileRequest(BaseModel):
    username: Optional[str] = Field(default=None, min_length=2, max_length=50)
    avatar_url: Optional[str] = Field(default=None, max_length=2048)
    bio: Optional[str] = Field(default=None, max_length=500)
    preferences: Optional[dict[str, Any]] = None


class KnowledgeQueryRequest(BaseModel):
    """A single external-knowledge query.

    ``query`` is the public frontend spelling. ``message`` remains accepted so
    older clients using the former Xunfei-only endpoint keep working.
    """

    query: Optional[str] = Field(default=None, min_length=1, max_length=10_000)
    message: Optional[str] = Field(default=None, min_length=1, max_length=10_000)
    top_n: int = Field(default=6, ge=1, le=20)
    thinking_output: bool = False

    @model_validator(mode="after")
    def require_exactly_one_query_field(self):
        if any(
            value is not None and not value.strip()
            for value in (self.query, self.message)
        ):
            raise ValueError("query 和 message 不能只包含空白字符")
        provided = [
            bool(value and value.strip()) for value in (self.query, self.message)
        ]
        if sum(provided) != 1:
            raise ValueError("query 和 message 必须且只能提供一个")
        return self

    @property
    def text(self) -> str:
        return (self.query or self.message or "").strip()


class AgentKnowledgeAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=50_000)
    top_k: int = Field(default=8, ge=1, le=20)


class ChatMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content 不能只包含空白字符")
        return value


class DashboardChatRequest(BaseModel):
    messages: list[ChatMessageRequest] = Field(min_length=1, max_length=20)
    use_knowledge_base: bool = True
    conversation_id: Optional[str] = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_history(self):
        if self.messages[-1].role != "user":
            raise ValueError("messages 必须以 user 消息结尾")
        if sum(len(item.content) for item in self.messages) > 50_000:
            raise ValueError("对话历史总长度不能超过 50000 个字符")
        return self


class CreateConversationRequest(BaseModel):
    title: str = Field(default="新的对话", max_length=200)
    module: str = Field(default="general", max_length=50)
    agent_id: Optional[str] = None


class NewMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)


class LegacyChatRequest(BaseModel):
    conversation_id: str
    agent_id: str
    message: str = Field(min_length=1, max_length=50_000)


class ResearchDecomposeRequest(BaseModel):
    direction: str = Field(min_length=3, max_length=4000)


class ExperimentRoadmapRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=100)
    objective: Optional[str] = Field(default=None, max_length=2000)


class RepoAnalysisRequest(BaseModel):
    repo_url: str = Field(min_length=8, max_length=2048)


class DiagnoseRequest(BaseModel):
    error_log: str = Field(min_length=1, max_length=50_000)
    repo_id: str
