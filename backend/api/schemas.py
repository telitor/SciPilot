from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


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


class KnowledgeCollectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    is_public: bool = False


class KnowledgeCollectionUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    is_public: Optional[bool] = None


class KnowledgeTextDocumentRequest(BaseModel):
    collection_id: Optional[str] = None
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=2_000_000)
    source_url: Optional[str] = Field(default=None, max_length=2048)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    collection_id: Optional[str] = None
    top_k: int = Field(default=8, ge=1, le=30)


class KnowledgeAnswerRequest(KnowledgeSearchRequest):
    include_answer: bool = True


class AgentKnowledgeAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=50_000)
    collection_id: Optional[str] = None
    top_k: int = Field(default=8, ge=1, le=20)


class XunfeiKnowledgeAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    top_n: int = Field(default=6, ge=1, le=20)
    thinking_output: bool = False


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
