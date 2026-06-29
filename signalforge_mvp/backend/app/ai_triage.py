"""AI Triage layer with provider abstraction.

Produces structured incident explanations from only provided evidence.
The LLM is NOT treated as the source of truth — it augments the rule-based
root-cause engine with natural-language summaries and suggestions.

Provider chain:
1. OpenAIProvider — uses OpenAI API with structured JSON output
2. MockProvider — deterministic fallback for tests and demos
3. None — returns "unavailable" with a clear disclaimer
"""

from datetime import datetime, timezone
from typing import Any

from app.schemas import AITriageEvidence, AITriageResponse, Incident


class AIProvider:
    """Base class for AI triage providers."""

    name: str = "base"

    def generate_triage(self, incident: Incident) -> AITriageResponse:
        raise NotImplementedError


class OpenAIProvider(AIProvider):
    """Uses OpenAI API to generate structured incident analysis from evidence."""

    name = "openai"

    def __init__(self) -> None:
        self._client: Any | None = None
        try:
            import openai
            from app.database import get_settings
            api_key = getattr(get_settings(), "OPENAI_API_KEY", None)
            if api_key:
                self._client = openai.OpenAI(api_key=api_key)
        except Exception:
            pass

    def is_available(self) -> bool:
        return self._client is not None

    def _build_prompt(self, incident: Incident) -> str:
        # Extract evidence from timeline
        evidence_lines = []
        for entry in incident.timeline:
            meta = entry.metadata or {}
            if entry.event_type.value == "created":
                evidence_lines.append(f"- Incident created: {entry.message}")
            elif entry.event_type.value == "evidence_added":
                if "error_rate" in meta:
                    evidence_lines.append(
                        f"- Anomaly stats: error_rate={meta.get('error_rate', 'N/A'):.1%}, "
                        f"p95_latency={meta.get('p95_latency_ms', 'N/A')}ms, "
                        f"avg_latency={meta.get('avg_latency_ms', 'N/A')}ms, "
                        f"samples={meta.get('sample_count', 'N/A')}"
                    )
                if "deployment_version" in meta:
                    evidence_lines.append(
                        f"- Deployment: v{meta.get('deployment_version')} at {meta.get('deployment_time', 'N/A')}"
                    )
                if "recent_event_count" in meta:
                    evidence_lines.append(f"- Rolling window: {meta['recent_event_count']} events")

        evidence_text = "\n".join(evidence_lines) if evidence_lines else "- No structured evidence available."

        prompt = f"""You are an expert site reliability engineer analyzing an incident.

You must ONLY use the evidence provided below. Do not hallucinate causes, metrics, or events not present in the evidence.

Incident: {incident.title}
Service: {incident.service_name}
Severity: {incident.severity}
Summary: {incident.summary}
Status: {incident.status.value}

Evidence:
{evidence_text}

Analyze this incident and produce a structured JSON response with exactly these fields:
- summary: A concise 1-2 sentence overview of what happened based ONLY on the evidence.
- likely_causes: A list of 2-3 possible root causes, each as a short string. Rank from most to least likely.
- evidence_points: A list of objects, each with {type, description, source}. Each point must reference specific evidence above.
- suggested_actions: A list of 2-4 concrete remediation steps, each as a short string.
- confidence: "high" if the evidence is clear and specific, "medium" if partial, "low" if sparse.

Return ONLY valid JSON. No markdown, no explanation."""
        return prompt

    def generate_triage(self, incident: Incident) -> AITriageResponse:
        if not self._client:
            raise RuntimeError("OpenAI client not available")

        prompt = self._build_prompt(incident)
        try:
            import json
            response = self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a structured incident triage assistant."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=1000,
                temperature=0.2,
            )
            raw = response.choices[0].message.content
            parsed = json.loads(raw)

            evidence_points = []
            for pt in parsed.get("evidence_points", []):
                evidence_points.append(
                    AITriageEvidence(
                        type=pt.get("type", "unknown"),
                        description=pt.get("description", ""),
                        source=pt.get("source", "unknown"),
                    )
                )

            return AITriageResponse(
                summary=parsed.get("summary", "No summary generated."),
                likely_causes=parsed.get("likely_causes", []),
                evidence_points=evidence_points,
                suggested_actions=parsed.get("suggested_actions", []),
                confidence=parsed.get("confidence", "low"),
                generated_by=self.name,
                generated_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            # On any failure, let the fallback handle it
            raise RuntimeError(f"OpenAI triage failed: {exc}")


class MockProvider(AIProvider):
    """Deterministic fallback provider for tests and demos.

    Generates structured responses based on patterns in the incident data.
    No external API calls. Fully predictable."""

    name = "mock"

    def generate_triage(self, incident: Incident) -> AITriageResponse:
        # Extract evidence from timeline for deterministic responses
        has_deployment = False
        deployment_version = None
        has_high_error_rate = False
        has_high_latency = False
        has_rolling_window = False
        sample_count = 0

        for entry in incident.timeline:
            meta = entry.metadata or {}
            if "deployment_version" in meta:
                has_deployment = True
                deployment_version = meta.get("deployment_version")
            if "error_rate" in meta:
                error_rate = meta.get("error_rate", 0)
                if error_rate >= 0.2:
                    has_high_error_rate = True
                p95 = meta.get("p95_latency_ms", 0)
                avg = meta.get("avg_latency_ms", 0)
                if p95 >= 1500 or avg >= 1000:
                    has_high_latency = True
                sample_count = meta.get("sample_count", 0)
            if "recent_event_count" in meta:
                has_rolling_window = True

        # Build deterministic likely causes
        likely_causes = []
        if has_deployment and (has_high_error_rate or has_high_latency):
            likely_causes.append(f"Recent deployment (v{deployment_version}) introduced a regression")
        if has_high_error_rate:
            likely_causes.append("Elevated error rate suggests a code or configuration issue")
        if has_high_latency:
            likely_causes.append("High latency indicates resource contention or downstream dependency slowdown")
        if not likely_causes:
            likely_causes.append("Anomaly detected but root cause is unclear from current evidence")

        # Build evidence points
        evidence_points = []
        if has_deployment:
            evidence_points.append(
                AITriageEvidence(
                    type="deployment",
                    description=f"Deployment v{deployment_version} occurred shortly before the incident",
                    source="timeline",
                )
            )
        if has_high_error_rate:
            evidence_points.append(
                AITriageEvidence(
                    type="anomaly",
                    description="Error rate exceeded warning threshold in the rolling window",
                    source="anomaly_stats",
                )
            )
        if has_high_latency:
            evidence_points.append(
                AITriageEvidence(
                    type="anomaly",
                    description="Latency p95/avg exceeded warning thresholds in the rolling window",
                    source="anomaly_stats",
                )
            )
        if has_rolling_window:
            evidence_points.append(
                AITriageEvidence(
                    type="context",
                    description=f"Rolling window analysis included {sample_count} recent events",
                    source="rolling_window",
                )
            )
        if not evidence_points:
            evidence_points.append(
                AITriageEvidence(
                    type="context",
                    description="Incident triggered but limited evidence is available",
                    source="incident",
                )
            )

        # Build suggested actions
        suggested_actions = []
        if has_deployment:
            suggested_actions.append("Consider rolling back the recent deployment and monitoring recovery")
        if has_high_error_rate:
            suggested_actions.append("Check application logs for error patterns and stack traces")
        if has_high_latency:
            suggested_actions.append("Investigate resource usage (CPU, memory, connections) and downstream dependencies")
        suggested_actions.append("Monitor the service for 10-15 minutes after any change")

        # Determine confidence
        confidence = "low"
        if has_deployment and (has_high_error_rate or has_high_latency):
            confidence = "high"
        elif has_high_error_rate or has_high_latency:
            confidence = "medium"

        summary = f"Anomaly detected in {incident.service_name}"
        if has_deployment and (has_high_error_rate or has_high_latency):
            summary = f"Anomaly in {incident.service_name} correlated with recent deployment v{deployment_version}. {', '.join(likely_causes[:1])}."
        elif has_high_error_rate or has_high_latency:
            summary = f"Performance degradation in {incident.service_name}: {', '.join(likely_causes[:1])}."
        else:
            summary = f"Anomaly detected in {incident.service_name} but insufficient evidence for a clear diagnosis."

        return AITriageResponse(
            summary=summary,
            likely_causes=likely_causes,
            evidence_points=evidence_points,
            suggested_actions=suggested_actions,
            confidence=confidence,
            generated_by=self.name,
            generated_at=datetime.now(timezone.utc),
        )


# ─────────── Provider Selection ───────────

def _create_provider() -> AIProvider | None:
    """Try OpenAI first, then fall back to mock."""
    openai_provider = OpenAIProvider()
    if openai_provider.is_available():
        return openai_provider
    return MockProvider()


ai_provider: AIProvider | None = None


def get_ai_provider() -> AIProvider | None:
    """Lazy-load the AI provider."""
    global ai_provider
    if ai_provider is None:
        ai_provider = _create_provider()
    return ai_provider


def ai_triage_incident(incident: Incident) -> AITriageResponse:
    """Generate an AI triage report for an incident.

    Tries the best available provider. If none works, returns a structured
    "unavailable" response with a clear disclaimer.
    """
    provider = get_ai_provider()
    if provider is None:
        return AITriageResponse(
            summary="AI triage is not available. No OpenAI API key or mock provider configured.",
            likely_causes=["Use the rule-based root-cause endpoint for structured analysis"],
            evidence_points=[
                AITriageEvidence(
                    type="unavailable",
                    description="No AI provider is configured. Set OPENAI_API_KEY for live analysis.",
                    source="system",
                )
            ],
            suggested_actions=[
                "Check the Root Cause Analysis panel for rule-based evidence scoring",
                "Review the incident timeline and evidence manually",
            ],
            confidence="low",
            generated_by="unavailable",
            generated_at=datetime.now(timezone.utc),
        )

    try:
        return provider.generate_triage(incident)
    except Exception:
        # If the provider fails, fall back to mock
        try:
            return MockProvider().generate_triage(incident)
        except Exception:
            return AITriageResponse(
                summary="AI triage failed. Please use the rule-based root-cause analysis.",
                likely_causes=["AI provider encountered an error"],
                evidence_points=[
                    AITriageEvidence(
                        type="error",
                        description="The AI provider failed to generate a response. Falling back to manual analysis.",
                        source="system",
                    )
                ],
                suggested_actions=[
                    "Check the Root Cause Analysis panel for structured evidence",
                    "Review the incident timeline and evidence manually",
                ],
                confidence="low",
                generated_by="unavailable",
                generated_at=datetime.now(timezone.utc),
            )
