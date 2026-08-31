from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.mysql_client import Base
from backend.utils.time import utcnow


class PipelineTraceRun(Base):
    """Durable, content-free execution trace for one AI chat request.

    The payload contains routing/tool metadata only. The pipeline deliberately never
    places the user's prompt or the generated answer in a trace, so retaining these rows
    for operations does not turn the observability store into a second conversation DB.
    """

    __tablename__ = "pipeline_trace_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    clearance: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", index=True)
    verifier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class LlmUsageEvent(Base):
    """Provider-reported token usage for every Gemini generation call.

    This is separate from a pipeline trace because document classification and conflict
    analysis also call the LLM without running the chat graph. Keeping a provider usage
    row per response makes the Admin token totals complete and independently auditable.
    """

    __tablename__ = "llm_usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usage_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False, default="gemini_generation", index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
