from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ArtifactStatus = Literal["ready", "missing", "invalid"]
PipelineArtifactSource = Literal["artifact", "live_traces"]


class DeepEvalMetricResponse(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    mean_score: float = 0.0
    examples: list[str] = Field(default_factory=list)


class DeepEvalCaseResponse(BaseModel):
    attempts: int = 0
    passed: int = 0
    pass_rate: float = 0.0
    flaky: bool = False


class DeepEvalReportResponse(BaseModel):
    cases: int = 0
    runs: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    deterministic_pass_rate: float | None = None
    judged_pass_rate: float | None = None
    complete: bool = True
    answer_model: str = ""
    judge_model: str = ""
    independent_judge: bool = False
    deterministic_metrics: list[str] = Field(default_factory=list)
    metrics: dict[str, DeepEvalMetricResponse] = Field(default_factory=dict)
    per_case: dict[str, DeepEvalCaseResponse] = Field(default_factory=dict)
    flaky_cases: list[str] = Field(default_factory=list)


class PipelineEvalGraderResponse(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    examples: list[str] = Field(default_factory=list)


class PipelineLatencyResponse(BaseModel):
    p50: float | None = None
    p95: float | None = None
    max: float | None = None


class PipelineEvalReportResponse(BaseModel):
    runs: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    outcomes: dict[str, int] = Field(default_factory=dict)
    failure_modes: dict[str, int] = Field(default_factory=dict)
    graders: dict[str, PipelineEvalGraderResponse] = Field(default_factory=dict)
    latency_ms: PipelineLatencyResponse = Field(default_factory=PipelineLatencyResponse)
    retries: int = 0


class DeepEvalArtifactResponse(BaseModel):
    status: ArtifactStatus
    source: Literal["artifact"] | None = None
    generated_at: datetime | None = None
    report: DeepEvalReportResponse | None = None
    message: str | None = None


class PipelineEvalArtifactResponse(BaseModel):
    status: ArtifactStatus
    source: PipelineArtifactSource | None = None
    generated_at: datetime | None = None
    report: PipelineEvalReportResponse | None = None
    message: str | None = None


class EvalReportsResponse(BaseModel):
    deepeval: DeepEvalArtifactResponse
    evaluation: PipelineEvalArtifactResponse
