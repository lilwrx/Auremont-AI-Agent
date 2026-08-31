from functools import lru_cache
from typing import ClassVar, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_NON_PRODUCTION_ENVS = frozenset({"development", "dev", "test", "testing", "local"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI20K Project"
    app_env: str = "development"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"  # noqa: S104 - containers must listen beyond loopback
    business_timezone: str = "Asia/Bangkok"
    log_level: str = "INFO"
    log_json: bool | None = None
    log_query_text: bool = True
    health_check_timeout_seconds: float = Field(default=3.0, gt=0, le=30)

    DEFAULT_INSECURE_SECRET_KEY: ClassVar[str] = "dev-secret-key-change-in-production"  # noqa: S105
    secret_key: str = Field(default=DEFAULT_INSECURE_SECRET_KEY, description="Secret key for JWT signing")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    database_url: str = ""

    llm_api_key: str = ""
    llm_model: str = ""

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    classification_auto_approve_threshold: float = Field(default=0.9, ge=0.0, le=1.0)
    classification_require_admin_approval_before_indexing: bool = True
    semantic_conflict_detection_enabled: bool = True
    semantic_conflict_fail_closed: bool = True
    semantic_conflict_min_confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    semantic_conflict_max_candidates: int = Field(default=40, ge=1, le=200)
    semantic_conflict_max_chars_per_document: int = Field(default=48_000, ge=4_000, le=60_000)
    semantic_conflict_sample_segments: int = Field(default=5, ge=3, le=7)
    semantic_conflict_max_facts_per_document: int = Field(default=200, ge=1, le=500)
    semantic_conflict_max_fact_chars_per_document: int = Field(default=32_000, ge=1_000, le=100_000)

    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "salesmate_documents"
    qdrant_timeout_seconds: int = Field(default=5, ge=1, le=60)

    hybrid_search_enabled: bool = False
    sparse_model_name: str = "Qdrant/bm25"

    rerank_enabled: bool = False
    cohere_api_key: str = ""
    cohere_rerank_model: str = "rerank-v3.5"
    cohere_rerank_timeout_seconds: float = Field(default=2.5, gt=0, le=30)

    rag_max_context_chars: int = Field(default=12_000, ge=1_000, le=100_000)
    rag_duplicate_similarity_threshold: float = Field(default=0.88, ge=0.5, le=1.0)

    tracing_enabled: bool = False
    trace_file: str = "eval/runs.jsonl"
    evaluation_report_path: str = "eval/results/report.json"
    deepeval_report_path: str = "eval/results/deepeval_report.json"
    observability_metrics_enabled: bool = False
    token_input_cost_per_million_usd: float = Field(default=0.0, ge=0)
    token_output_cost_per_million_usd: float = Field(default=0.0, ge=0)
    admin_presence_window_minutes: int = Field(default=15, ge=1, le=1440)

    redis_url: str = "redis://localhost:6379/0"

    memory_ttl_seconds: int = 60 * 60 * 24 * 90

    reflection_memory_enabled: bool = True
    reflection_ttl_seconds: int = 60 * 60 * 24 * 30

    search_criteria_enabled: bool = True
    search_criteria_ttl_seconds: int = 60 * 60 * 24

    verifier_threshold_sale: float = 0.7

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"  # noqa: S105 - local MinIO development credential
    minio_secure: bool = False
    minio_bucket_documents: str = "salesmate-documents"
    minio_bucket_project_images: str = "project-images"
    minio_bucket_news_images: str = "news-images"
    minio_public_endpoint: str = ""
    project_images_base_url: str = ""
    project_images_archive_url: str = ""
    auto_load_demo_data: bool = True

    inventory_api_url: str = ""
    inventory_api_key: str = ""
    inventory_project_map: str = ""

    news_default_ttl_days: int = Field(default=180, ge=7, le=1095)
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    upload_max_bytes: int = 20 * 1024 * 1024
    document_security_block_threshold: Literal["warning", "high_risk", "disabled"] = "high_risk"
    document_security_max_findings: int = Field(default=20, ge=1, le=200)
    document_security_excerpt_context_chars: int = Field(default=80, ge=20, le=500)

    customer_anonymous_turn_limit: int = 3

    customer_anonymous_daily_limit: int = 3
    customer_registered_daily_limit: int = 10

    anonymous_rate_limit_per_window: int = 20
    anonymous_rate_limit_window_seconds: int = 300
    trusted_proxy_count: int = 0

    lead_scoring_enabled: bool = True
    lead_scoring_llm_enabled: bool = True
    lead_hot_threshold: int = 65
    lead_warm_threshold: int = 35
    lead_llm_min_turns: int = 3
    lead_llm_max_history_turns: int = 6
    lead_inbox_fairness_minutes: int = 10
    lead_require_phone_on_register: bool = True

    @property
    def is_production(self) -> bool:
        """True outside the known development/test environments.

        Phrased as a denylist so an unrecognised APP_ENV (a typo, a new staging name)
        is treated as production and gets the stricter checks, never the laxer ones.
        """
        return self.app_env.lower() not in _NON_PRODUCTION_ENVS

    @model_validator(mode="after")
    def _resolve_log_json(self) -> "Settings":
        if self.log_json is None:
            self.log_json = self.is_production
        return self

    @model_validator(mode="after")
    def _reject_insecure_secret_key(self) -> "Settings":
        """Refuse to boot a production app signing JWTs with the public default key.

        Failing at startup is deliberate: the alternative is a deployment that looks
        healthy while every token it issues can be forged by anyone with this source.
        """
        if self.is_production and self.secret_key == self.DEFAULT_INSECURE_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY must be set to a unique value when APP_ENV is not a development "
                'environment. Generate one with: python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        return self

    @model_validator(mode="after")
    def _reject_inverted_lead_thresholds(self) -> "Settings":
        """Refuse to boot when the WARM threshold is not below the HOT one.

        An inverted pair silently marks every lead HOT, which is worse than shipping no
        scoring at all: a Sale who cannot trust the badge stops reading it, and the queue
        goes back to being unordered while looking like it is prioritised.
        """
        if self.lead_warm_threshold >= self.lead_hot_threshold:
            raise ValueError(
                f"LEAD_WARM_THRESHOLD ({self.lead_warm_threshold}) must be below "
                f"LEAD_HOT_THRESHOLD ({self.lead_hot_threshold}) — otherwise every lead scores HOT."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
