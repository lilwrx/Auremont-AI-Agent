from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

SalePresence = Literal["online", "offline", "busy"]


class SaleAccountCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    is_active: bool = True

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Mật khẩu không được vượt quá 72 byte.")
        if not any(character.isalpha() for character in value) or not any(character.isdigit() for character in value):
            raise ValueError("Mật khẩu phải có ít nhất một chữ cái và một chữ số.")
        return value


class SaleStatusResponse(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    presence: SalePresence
    active_chat_sessions: int
    handled_sessions: int
    interaction_rate: float | None = None
    conversion_rate: float | None = None
    last_activity_at: datetime | None = None


class ManagedLiveSessionResponse(BaseModel):
    session_id: int
    customer_label: str
    current_sale_id: int | None = None
    current_sale_name: str | None = None
    status: str
    waiting_since: datetime | None = None
    project_id: str | None = None
    last_message_preview: str = ""


class SalesBoardSummary(BaseModel):
    total_sales: int
    active_accounts: int
    online_sales: int
    busy_sales: int
    waiting_customers: int
    live_customers: int


class SalesBoardResponse(BaseModel):
    generated_at: datetime
    presence_window_minutes: int
    summary: SalesBoardSummary
    sales: list[SaleStatusResponse]
    live_sessions: list[ManagedLiveSessionResponse]


class SaleActiveUpdate(BaseModel):
    is_active: bool


class SaleReassignRequest(BaseModel):
    session_id: int
    to_sale_id: int


class ToolReliabilityMetric(BaseModel):
    key: str
    name: str
    calls: int
    errors: int
    success_rate: float | None = None
    average_latency_ms: float | None = None


class TokenDailyMetric(BaseModel):
    date: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class UserMonitoringMetric(BaseModel):
    dau: int
    mau: int
    active_sessions: int
    waiting_sessions: int


class TokenMonitoringMetric(BaseModel):
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    projected_monthly_cost_usd: float
    cost_configured: bool
    daily: list[TokenDailyMetric]


class ModuleUsageMetric(BaseModel):
    module: str
    calls: int


class AuditLogEntry(BaseModel):
    id: int
    timestamp: datetime
    severity: Literal["INFO", "WARN", "ERROR"]
    module: str
    event: str
    username: str | None = None
    request_id: str | None = None


class TraceStepResponse(BaseModel):
    name: str
    at_ms: float
    duration_ms: float | None = None
    status: Literal["success", "error", "skipped"]
    detail: str | None = None


class TraceSummaryResponse(BaseModel):
    run_id: str
    started_at: datetime
    duration_ms: float
    project_id: str | None = None
    clearance: str
    outcome: str
    verifier_score: float | None = None
    steps: list[TraceStepResponse]


class IntentBucketMetric(BaseModel):
    label: str
    count: int


class PopularProjectMetric(BaseModel):
    project_id: str
    project_name: str
    count: int


class FallbackAlertResponse(BaseModel):
    message_id: int
    session_id: int | None = None
    severity: Literal["warning", "critical"]
    verifier_score: float
    failure_mode: str | None = None
    customer_question: str | None = None
    created_at: datetime


class ObservabilityOverviewResponse(BaseModel):
    generated_at: datetime
    period_days: int
    tracing_enabled: bool
    tool_reliability: list[ToolReliabilityMetric]
    users: UserMonitoringMetric
    tokens: TokenMonitoringMetric
    most_used_modules: list[ModuleUsageMetric]
    logs: list[AuditLogEntry]
    traces: list[TraceSummaryResponse]
    budget_intents: list[IntentBucketMetric]
    popular_projects: list[PopularProjectMetric]
    fallback_alerts: list[FallbackAlertResponse]


class ApiTestRequest(BaseModel):
    method: Literal["GET", "POST", "PATCH", "PUT", "DELETE"] = "GET"
    path: str = Field(min_length=1, max_length=500)
    body: dict | list | None = None


class BusinessPeriod(BaseModel):
    current_start: str
    current_end: str
    previous_start: str
    previous_end: str
    timezone: str


class BusinessSummaryBase(BaseModel):
    sessions: int
    customers: int
    questions: int
    active_sales: int
    helpful_rate: float | None = None
    verifier_avg: float | None = None
    hitl_required: int
    hitl_confirmed: int


class BusinessSummary(BusinessSummaryBase):
    ready_documents: int


class BusinessActivityPoint(BaseModel):
    date: str
    sessions: int
    questions: int


class BusinessProjectMetric(BaseModel):
    project_id: str | None = None
    name: str
    sessions: int


class BusinessSaleMetric(BaseModel):
    sale_id: int
    username: str
    sessions: int
    customers: int
    questions: int


class BusinessFeedbackDistribution(BaseModel):
    helpful: int
    wrong: int
    incomplete: int
    unrated: int


class BusinessQualityPoint(BaseModel):
    date: str
    faithfulness: float | None = None
    relevancy: float | None = None


class BusinessHitlFunnel(BaseModel):
    answers: int
    required: int
    confirmed: int


class BusinessDocumentCoverage(BaseModel):
    project_id: str
    name: str
    ready_count: int
    categories: dict[str, Literal["ready", "pending_review", "unavailable", "missing"]]


class BusinessFilterProject(BaseModel):
    id: str
    name: str


class BusinessFilterSale(BaseModel):
    id: int
    username: str


class BusinessFilterOptions(BaseModel):
    projects: list[BusinessFilterProject]
    sales: list[BusinessFilterSale]


class BusinessAppliedFilters(BaseModel):
    project_id: str | None = None
    sale_id: int | None = None


class BusinessDashboardResponse(BaseModel):
    period_days: int
    period: BusinessPeriod
    applied_filters: BusinessAppliedFilters
    filter_options: BusinessFilterOptions
    verifier_threshold: float
    summary: BusinessSummary
    previous_summary: BusinessSummaryBase
    activity: list[BusinessActivityPoint]
    top_projects: list[BusinessProjectMetric]
    top_sales: list[BusinessSaleMetric]
    feedback_distribution: BusinessFeedbackDistribution
    quality_trend: list[BusinessQualityPoint]
    hitl_funnel: BusinessHitlFunnel
    document_coverage: list[BusinessDocumentCoverage]


class LeadTierCounts(BaseModel):
    hot: int = 0
    warm: int = 0
    cold: int = 0
    total: int = 0


class LeadTrendPoint(BaseModel):
    date: str
    hot: int = 0
    warm: int = 0
    cold: int = 0


class LeadEnrichmentStats(BaseModel):
    """How often the LLM pass actually ran. Makes the cost brake measured, not assumed."""

    scored: int = 0
    llm_calls: int = 0
    call_rate: float = 0.0


class LeadStatsResponse(BaseModel):
    """Lead capture and scoring, on its own endpoint rather than folded into /business.

    /business scopes every metric to sessions owned by an official Sale. Customer-chat
    sessions have `sale_id IS NULL` until claimed, so leads sit outside that universe by
    construction — merging them would make the headline session/customer counts describe two
    different populations, which is the inconsistency /business's own scoping comment exists
    to prevent.
    """

    period_days: int
    totals: LeadTierCounts
    trend: list[LeadTrendPoint]
    registered: int = 0
    anonymous: int = 0
    contactable: int = 0
    contact_rate: float = 0.0
    avg_score: float = 0.0
    llm_enrichment: LeadEnrichmentStats = LeadEnrichmentStats()
