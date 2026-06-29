from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EventType(str, Enum):
    log = "log"
    metric = "metric"
    trace = "trace"
    deployment = "deployment"


class IncidentStatus(str, Enum):
    investigating = "investigating"
    mitigated = "mitigated"
    resolved = "resolved"


class IncidentTimelineEvent(str, Enum):
    created = "created"
    status_changed = "status_changed"
    evidence_added = "evidence_added"


class TelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=8, max_length=128)
    tenant_id: str = Field(min_length=1)
    service_name: str = Field(min_length=1)
    event_type: EventType
    timestamp: datetime
    name: str = Field(min_length=1)
    trace_id: str | None = None
    value: float | None = None
    severity: str | None = None
    message: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_id", "tenant_id", "service_name", "name")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_event_shape(self) -> "TelemetryEvent":
        if self.event_type == EventType.metric:
            self._validate_metric_event()
        elif self.event_type == EventType.log:
            self._validate_log_event()
        elif self.event_type == EventType.trace:
            self._validate_trace_event()
        elif self.event_type == EventType.deployment:
            self._validate_deployment_event()
        return self

    def _validate_metric_event(self) -> None:
        if self.name != "http_request":
            return

        status_code = self._required_attribute("status_code")
        latency_ms = self._required_attribute("latency_ms")

        try:
            status_code_int = int(status_code)
        except (TypeError, ValueError) as exc:
            raise ValueError("attributes.status_code must be an integer") from exc

        if status_code_int < 100 or status_code_int > 599:
            raise ValueError("attributes.status_code must be between 100 and 599")

        try:
            latency_float = float(latency_ms)
        except (TypeError, ValueError) as exc:
            raise ValueError("attributes.latency_ms must be a number") from exc

        if latency_float < 0:
            raise ValueError("attributes.latency_ms cannot be negative")

    def _validate_log_event(self) -> None:
        if not self.message or not self.message.strip():
            raise ValueError("log events require a non-empty message")

        allowed_severities = {"debug", "info", "warning", "error", "critical"}
        if self.severity and self.severity not in allowed_severities:
            raise ValueError(
                "severity must be one of: debug, info, warning, error, critical"
            )

    def _validate_trace_event(self) -> None:
        if not self.trace_id or not self.trace_id.strip():
            raise ValueError("trace events require trace_id")

        if self.name != "service_call":
            return

        self._required_attribute("caller")
        self._required_attribute("callee")

    def _validate_deployment_event(self) -> None:
        if self.name != "service_deployed":
            return

        self._required_attribute("version")

    def _required_attribute(self, key: str) -> Any:
        value = self.attributes.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"attributes.{key} is required for {self.event_type.value} events")
        return value


class IngestResponse(BaseModel):
    accepted: bool
    event_id: str
    duplicate: bool = False
    mode: str = "sync"  # "async" | "sync"


class IncidentTimelineEntry(BaseModel):
    timestamp: datetime
    event_type: IncidentTimelineEvent
    message: str
    actor: str = "system"
    metadata: dict[str, Any] = Field(default_factory=dict)


class Incident(BaseModel):
    id: str
    tenant_id: str
    service_name: str
    title: str
    severity: str
    status: IncidentStatus
    summary: str
    evidence: list[str]
    timeline: list[IncidentTimelineEntry] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class IncidentStatusUpdate(BaseModel):
    status: IncidentStatus
    actor: str = Field(default="operator", min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("actor")
    @classmethod
    def strip_actor(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("actor cannot be blank")
        return cleaned


class ServiceGraphNode(BaseModel):
    id: str
    label: str


class ServiceGraphEdge(BaseModel):
    source: str
    target: str
    label: str = "calls"
    count: int = 1


class ServiceGraphResponse(BaseModel):
    nodes: list[ServiceGraphNode]
    edges: list[ServiceGraphEdge]


class RunbookCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    service_name: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=2048)
    steps: list[str] = Field(default_factory=list)

    @field_validator("tenant_id", "service_name", "title")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned


class RunbookUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, min_length=1, max_length=2048)
    steps: list[str] | None = Field(default=None)


class Runbook(BaseModel):
    id: str
    tenant_id: str
    service_name: str
    title: str
    description: str
    steps: list[str]
    created_at: datetime
    updated_at: datetime


class RootCauseEvidence(BaseModel):
    type: str
    score: int
    reason: str
    details: str | None = None


class RootCauseHypothesis(BaseModel):
    rank: int
    service_name: str
    total_score: int
    confidence: str  # high | medium | low
    evidence: list[RootCauseEvidence]
    recommended_action: str


class RootCauseResponse(BaseModel):
    service_name: str
    hypotheses: list[RootCauseHypothesis]
    generated_at: datetime


class AITriageEvidence(BaseModel):
    type: str
    description: str
    source: str  # e.g. "timeline", "anomaly_stats", "deployment"


class AITriageResponse(BaseModel):
    summary: str
    likely_causes: list[str]
    evidence_points: list[AITriageEvidence]
    suggested_actions: list[str]
    confidence: str  # high | medium | low
    generated_by: str  # "openai" | "mock" | "unavailable"
    disclaimer: str = "This analysis is generated by an AI model and should be verified against system evidence. It is not the source of truth."
    generated_at: datetime


class SearchResultItem(BaseModel):
    id: str
    type: str  # "incident" | "runbook"
    service_name: str
    title: str
    summary: str | None = None
    severity: str | None = None
    status: str | None = None
    created_at: datetime


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]

