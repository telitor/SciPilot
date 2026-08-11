import json
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_must_contain_letters_and_numbers(cls, value: str) -> str:
        if not any(char.isalpha() for char in value) or not any(
            char.isdigit() for char in value
        ):
            raise ValueError("Password must contain at least one letter and one number")
        return value


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
    project_id: Optional[UUID] = None
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("context")
    @classmethod
    def validate_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        paper_id = value.get("paper_id")
        if paper_id is not None and (
            not isinstance(paper_id, str) or not paper_id.strip() or len(paper_id) > 100
        ):
            raise ValueError("context.paper_id 格式不正确")
        if len(json.dumps(value, ensure_ascii=False)) > 10_000:
            raise ValueError("context 内容不能超过 10000 个字符")
        return value


class NewMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)


class MessageFeedbackRequest(BaseModel):
    rating: Literal["helpful", "unhelpful"]
    comment: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("comment")
    @classmethod
    def normalize_feedback_comment(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class MessageFeedbackResponse(BaseModel):
    id: str
    message_id: str
    rating: Literal["helpful", "unhelpful"]
    comment: Optional[str] = None
    review_status: Literal["pending", "reviewed", "rejected"]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FeedbackReviewRequest(BaseModel):
    review_status: Literal["reviewed", "rejected"]
    review_note: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("review_note")
    @classmethod
    def normalize_review_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AdminFeedbackResponse(MessageFeedbackResponse):
    user_id: str
    conversation_id: str
    ai_run_id: Optional[str] = None
    reviewed_by: Optional[str] = None
    review_note: Optional[str] = None
    reviewed_at: Optional[str] = None


class AdminFeedbackListResponse(BaseModel):
    items: list[AdminFeedbackResponse]
    total: int = Field(ge=0)


class AdminUserResponse(BaseModel):
    id: str
    email: str
    username: str
    role: Literal["user", "admin"]
    email_confirmed_at: Optional[str] = None
    last_sign_in_at: Optional[str] = None
    created_at: Optional[str] = None


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    total: int = Field(ge=0)


class AdminRoleChangeRequest(BaseModel):
    role: Literal["user", "admin"]
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_role_change_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("角色变更原因至少需要 3 个字符")
        return cleaned


class AdminRoleAuditResponse(BaseModel):
    id: str
    target_user_id: Optional[str] = None
    actor_user_id: Optional[str] = None
    previous_role: Literal["user", "admin"]
    new_role: Literal["user", "admin"]
    source: Literal["bootstrap-script", "admin-api"]
    reason: str
    created_at: Optional[str] = None


class AdminRoleAuditListResponse(BaseModel):
    items: list[AdminRoleAuditResponse]
    total: int = Field(ge=0)


class EvaluationSuiteResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: Optional[str] = None
    module: str
    version: int = Field(ge=1)
    is_active: bool
    case_count: int = Field(default=0, ge=0)


class EvaluationRunRequest(BaseModel):
    suite_slug: str = Field(default="rag-retrieval-baseline", min_length=1, max_length=100)
    mode: Literal["offline", "real-model"] = "offline"
    confirm_external_calls: bool = False


class EvaluationRunResponse(BaseModel):
    id: str
    suite_id: str
    mode: Literal["offline", "real-model"]
    status: Literal["running", "completed", "failed"]
    provider: Optional[str] = None
    model: Optional[str] = None
    case_count: int = Field(default=0, ge=0)
    passed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    metrics: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class EvaluationRunListResponse(BaseModel):
    items: list[EvaluationRunResponse]
    total: int = Field(ge=0)


class AiMetricsResponse(BaseModel):
    hours: int = Field(ge=1, le=720)
    total_runs: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    degraded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    failure_rate: float = Field(ge=0, le=1)
    degraded_rate: float = Field(ge=0, le=1)
    p95_latency_ms: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_cny: float
    unknown_cost_runs: int = Field(ge=0)
    usage_sources: dict[str, int] = Field(default_factory=dict)
    by_module: list[dict[str, Any]] = Field(default_factory=list)


class AiAlertResponse(BaseModel):
    id: str
    module: str
    alert_type: Literal[
        "failure-rate", "degraded-rate", "p95-latency", "daily-volume"
    ]
    severity: Literal["warning", "critical"]
    status: Literal["open", "acknowledged", "resolved"]
    title: str
    detail: str
    metric_value: Optional[float] = None
    threshold_value: Optional[float] = None
    occurrence_count: int = Field(ge=1)
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    acknowledged_at: Optional[str] = None
    acknowledged_by: Optional[str] = None


class AiAlertListResponse(BaseModel):
    items: list[AiAlertResponse]
    total: int = Field(ge=0)


class LegacyChatRequest(BaseModel):
    conversation_id: str
    agent_id: str
    message: str = Field(min_length=1, max_length=50_000)


class ResearchDecomposeRequest(BaseModel):
    direction: str = Field(min_length=3, max_length=4000)
    project_id: Optional[UUID] = None
    paper_id: Optional[str] = Field(default=None, max_length=100)


class ExperimentRoadmapRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=100)
    objective: Optional[str] = Field(default=None, max_length=2000)
    project_id: Optional[UUID] = None


class RepoAnalysisRequest(BaseModel):
    repo_url: str = Field(min_length=8, max_length=2048)
    project_id: Optional[UUID] = None
    roadmap_id: Optional[str] = Field(default=None, max_length=100)


class ExperimentRunOutputFile(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    relative_path: Optional[str] = Field(default=None, max_length=1024)
    size_bytes: Optional[int] = Field(default=None, ge=0)
    sha256: Optional[str] = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    media_type: Optional[str] = Field(default=None, max_length=200)


class CreateExperimentRunRequest(BaseModel):
    code_artifact_id: str = Field(min_length=1, max_length=100)
    commit_sha: str = Field(pattern=r"^[0-9a-fA-F]{7,64}$")
    command: str = Field(min_length=1, max_length=4000)
    environment: dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("command", "notes")
    @classmethod
    def normalize_experiment_run_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("运行命令和备注不能只包含空白字符")
        return cleaned

    @field_validator("environment")
    @classmethod
    def validate_experiment_environment(
        cls, value: dict[str, Any]
    ) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False)) > 20_000:
            raise ValueError("环境快照不能超过 20000 个字符")
        return value


class UpdateExperimentRunRequest(BaseModel):
    status: Literal["running", "succeeded", "failed", "cancelled"]
    exit_code: Optional[int] = None
    stdout_excerpt: Optional[str] = Field(default=None, max_length=50_000)
    stderr_excerpt: Optional[str] = Field(default=None, max_length=50_000)
    output_files: list[ExperimentRunOutputFile] = Field(
        default_factory=list,
        max_length=50,
    )
    notes: Optional[str] = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_experiment_result(self):
        if self.status == "succeeded" and self.exit_code != 0:
            raise ValueError("成功运行的退出码必须为 0")
        if self.status == "failed" and self.exit_code is None:
            raise ValueError("失败运行必须记录退出码")
        if self.status in {"running", "cancelled"} and self.exit_code is not None:
            raise ValueError("运行中或已取消状态不能记录退出码")
        return self


class DiagnoseRequest(BaseModel):
    error_log: str = Field(min_length=1, max_length=50_000)
    repo_id: str


ProjectStatus = Literal["draft", "active", "completed", "archived"]
ProjectStage = Literal[
    "discovery",
    "literature",
    "question",
    "experiment",
    "reproduction",
    "analysis",
    "completed",
]
ArtifactReviewStatus = Literal["draft", "confirmed", "deprecated"]
ProjectMemoryType = Literal[
    "fact",
    "decision",
    "constraint",
    "preference",
    "lesson",
    "artifact-summary",
]
ProjectMemoryStatus = Literal["active", "archived"]


class CreateResearchProjectRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    objective: Optional[str] = Field(default=None, max_length=2000)
    current_stage: ProjectStage = "discovery"

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("项目名称至少需要 2 个字符")
        return cleaned


class UpdateResearchProjectRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    objective: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[Literal["draft", "active", "completed"]] = None
    current_stage: Optional[ProjectStage] = None

    @field_validator("name")
    @classmethod
    def updated_name_must_not_be_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("项目名称至少需要 2 个字符")
        return cleaned

    @model_validator(mode="after")
    def require_update(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个需要更新的项目字段")
        return self


class ProjectAssignmentRequest(BaseModel):
    project_id: Optional[UUID] = None


class CreateProjectMemoryRequest(BaseModel):
    memory_type: ProjectMemoryType = "fact"
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("title", "content")
    @classmethod
    def memory_text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("记忆内容不能为空")
        return cleaned


class UpdateProjectMemoryRequest(BaseModel):
    memory_type: Optional[ProjectMemoryType] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    content: Optional[str] = Field(default=None, min_length=1, max_length=8000)
    status: Optional[ProjectMemoryStatus] = None

    @field_validator("title", "content")
    @classmethod
    def updated_memory_text_must_not_be_blank(
        cls, value: Optional[str]
    ) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("记忆内容不能为空")
        return cleaned

    @model_validator(mode="after")
    def require_memory_update(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个需要更新的记忆字段")
        return self


class ProjectMemoryResponse(BaseModel):
    id: str
    project_id: str
    memory_type: ProjectMemoryType
    title: str
    content: str
    source_type: Literal["manual", "artifact"]
    source_id: Optional[str] = None
    source_version: Optional[int] = Field(default=None, ge=1)
    status: ProjectMemoryStatus
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProjectMemoryListResponse(BaseModel):
    items: list[ProjectMemoryResponse]
    total: int = Field(ge=0)


AgentTaskStatus = Literal[
    "blocked",
    "ready",
    "in_progress",
    "awaiting_approval",
    "completed",
    "failed",
]


class AgentWorkflowTaskResponse(BaseModel):
    id: str
    workflow_id: str
    project_id: str
    task_key: Literal[
        "paper-reading",
        "problem-decomposition",
        "project-planning",
        "code-reproduction",
        "result-interpretation",
    ]
    title: str
    agent_category: str
    position: int = Field(ge=1, le=5)
    status: AgentTaskStatus
    research_job_id: Optional[str] = None
    output_paper_id: Optional[str] = None
    output_artifact_id: Optional[str] = None
    error_message: Optional[str] = None
    launch_path: str
    started_at: Optional[str] = None
    approved_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgentWorkflowResponse(BaseModel):
    id: str
    project_id: str
    name: str
    status: Literal["active", "completed", "archived"]
    tasks: list[AgentWorkflowTaskResponse]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgentWorkflowEnvelopeResponse(BaseModel):
    workflow: Optional[AgentWorkflowResponse] = None


# Stable response contracts for the P0 research workflow. These models keep
# FastAPI's OpenAPI schema useful to the frontend and CI without constraining
# provider-specific metadata stored alongside the core fields.


ResearchJobStatus = Literal[
    "pending", "running", "succeeded", "failed", "cancelled"
]


class PaperUploadJobResponse(BaseModel):
    job_id: str
    paper_id: str
    status: ResearchJobStatus
    progress: int = Field(ge=0, le=100)


class ResearchJobResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    paper_id: Optional[str] = None
    job_type: str
    status: ResearchJobStatus
    progress: int = Field(ge=0, le=100)
    result: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    attempts: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ResearchJobListResponse(BaseModel):
    items: list[ResearchJobResponse]


class ArtifactRevisionRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    content: dict[str, Any]
    revision_note: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("标题不能为空")
        return cleaned

    @field_validator("content")
    @classmethod
    def content_must_be_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("产物内容不能为空")
        if len(json.dumps(value, ensure_ascii=False)) > 250_000:
            raise ValueError("产物内容不能超过 250000 个字符")
        return value


class ArtifactRestoreRequest(BaseModel):
    revision_note: Optional[str] = Field(default=None, max_length=1000)


class ArtifactDetailResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    artifact_type: str
    title: str
    content: dict[str, Any]
    review_status: ArtifactReviewStatus
    version_group_id: str
    version: int = Field(ge=1)
    parent_version_id: Optional[str] = None
    confirmed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ArtifactVersionSummaryResponse(BaseModel):
    id: str
    title: str
    review_status: ArtifactReviewStatus
    version: int = Field(ge=1)
    parent_version_id: Optional[str] = None
    confirmed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ArtifactVersionListResponse(BaseModel):
    version_group_id: str
    latest_version: int = Field(ge=1)
    items: list[ArtifactVersionSummaryResponse]


class ChatAgentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    is_public: bool = True


class AiRunSummaryResponse(BaseModel):
    id: str
    status: Literal["succeeded", "degraded", "failed"]
    response_mode: Optional[str] = None
    fallback_reason: Optional[str] = None
    retrieval_count: int = Field(default=0, ge=0)
    latency_ms: int = Field(ge=0)
    model_latency_ms: Optional[int] = Field(default=None, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    usage_source: Literal["provider", "estimated", "unavailable"] = "unavailable"
    estimated_cost_cny: Optional[float] = Field(default=None, ge=0)
    created_at: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    message: dict[str, Any]
    citations: list[dict[str, Any]]
    knowledge_used: bool
    model: Optional[str] = None
    agent: ChatAgentResponse
    run: Optional[AiRunSummaryResponse] = None


class DashboardChatResponse(BaseModel):
    reply: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    model: Optional[str] = None
    knowledge_used: bool
    knowledge_unavailable: bool = False
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    persistence_unavailable: bool = False
    run: Optional[AiRunSummaryResponse] = None


class ResearchNodeResponse(BaseModel):
    id: str
    question: str
    feasibility: Literal["high", "medium", "low"]
    datasets: list[str] = Field(default_factory=list)
    papers: list[str] = Field(default_factory=list)
    children: list["ResearchNodeResponse"] = Field(default_factory=list)


class ResearchTreeResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    review_status: ArtifactReviewStatus
    version_group_id: str
    version: int = Field(ge=1)
    parent_version_id: Optional[str] = None
    confirmed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    core_question: str
    sub_questions: list[ResearchNodeResponse]
    generation_mode: Optional[str] = None


class ExperimentStepResponse(BaseModel):
    step: int = Field(ge=1)
    task: str
    details: str
    estimated_days: int = Field(ge=1)
    status: Literal["pending", "in_progress", "completed"] = "pending"


class BaselineResponse(BaseModel):
    name: str
    paper_id: str
    github_url: str
    stars: int = 0
    description: Optional[str] = None


class DatasetResponse(BaseModel):
    name: str
    size: str
    language: str
    url: str
    description: Optional[str] = None


class ExperimentRoadmapResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    review_status: ArtifactReviewStatus
    version_group_id: str
    version: int = Field(ge=1)
    parent_version_id: Optional[str] = None
    confirmed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    objective: str
    steps: list[ExperimentStepResponse]
    baselines: list[BaselineResponse]
    datasets: list[DatasetResponse]
    tools: list[str] = Field(default_factory=list)
    generation_mode: Optional[str] = None


class RepoFileResponse(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory"]
    children: list["RepoFileResponse"] = Field(default_factory=list)
    size: Optional[int] = None


class DependencyResponse(BaseModel):
    name: str
    version: str
    purpose: str


class ReproductionStepResponse(BaseModel):
    step: int = Field(ge=1)
    instruction: str
    command: Optional[str] = None
    checked: bool = False


class CodeReproductionResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    review_status: ArtifactReviewStatus
    version_group_id: str
    version: int = Field(ge=1)
    parent_version_id: Optional[str] = None
    confirmed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    repo_name: str
    repo_url: str
    language: str
    stars: int
    description: str
    file_tree: list[RepoFileResponse]
    dependencies: list[DependencyResponse]
    steps: list[ReproductionStepResponse]
    generation_mode: Optional[str] = None


class ExperimentRunResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    code_artifact_id: str
    result_artifact_id: Optional[str] = None
    execution_mode: Literal["manual-evidence"]
    status: Literal["planned", "running", "succeeded", "failed", "cancelled"]
    commit_sha: str
    command: str
    environment: dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    exit_code: Optional[int] = None
    stdout_excerpt: Optional[str] = None
    stderr_excerpt: Optional[str] = None
    output_files: list[ExperimentRunOutputFile] = Field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ExperimentRunListResponse(BaseModel):
    items: list[ExperimentRunResponse]


class ChartResponse(BaseModel):
    type: Literal["bar", "line", "boxplot", "radar", "heatmap"]
    title: str
    data: Any
    options: Optional[dict[str, Any]] = None


class StatsSummaryResponse(BaseModel):
    metric: str
    mean: float
    std: float
    min: float
    max: float
    ci95: tuple[float, float]
    count: Optional[int] = None
    p_value: Optional[float] = None


class ResultAnalysisResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    review_status: ArtifactReviewStatus
    version_group_id: str
    version: int = Field(ge=1)
    parent_version_id: Optional[str] = None
    confirmed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    charts: list[ChartResponse]
    stats: list[StatsSummaryResponse]
    interpretation: str
    suggestions: list[str]
    row_count: Optional[int] = None
    generation_mode: Optional[str] = None
    experiment_run_id: Optional[str] = None
    code_artifact_id: Optional[str] = None
