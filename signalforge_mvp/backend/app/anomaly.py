from dataclasses import dataclass

from app.schemas import TelemetryEvent


MIN_REQUEST_SAMPLES = 20
REQUEST_WINDOW_SIZE = 20
WARNING_ERROR_RATE = 0.20
CRITICAL_ERROR_RATE = 0.50
WARNING_AVG_LATENCY_MS = 1000
CRITICAL_AVG_LATENCY_MS = 1800
WARNING_P95_LATENCY_MS = 1500
CRITICAL_P95_LATENCY_MS = 2500


@dataclass(frozen=True)
class WindowStats:
    sample_count: int
    error_count: int
    error_rate: float
    avg_latency_ms: float
    p95_latency_ms: float


@dataclass(frozen=True)
class AnomalyResult:
    is_anomaly: bool
    severity: str
    title: str
    evidence: list[str]
    stats: WindowStats | None = None


def analyze_service_window(events: list[TelemetryEvent]) -> AnomalyResult:
    request_events = [
        event
        for event in events
        if event.event_type == "metric" and event.name == "http_request"
    ]

    if len(request_events) < MIN_REQUEST_SAMPLES:
        return AnomalyResult(
            is_anomaly=False,
            severity="info",
            title="Not enough data",
            evidence=[
                f"Need at least {MIN_REQUEST_SAMPLES} request events before detecting anomalies.",
                f"Current request sample count is {len(request_events)}.",
            ],
        )

    last_events = request_events[-REQUEST_WINDOW_SIZE:]
    stats = calculate_window_stats(last_events)
    evidence = build_window_evidence(stats)

    critical_reasons: list[str] = []
    warning_reasons: list[str] = []

    if stats.error_rate >= CRITICAL_ERROR_RATE:
        critical_reasons.append(
            f"Critical error-rate breach: {stats.error_rate:.0%} >= {CRITICAL_ERROR_RATE:.0%}."
        )
    elif stats.error_rate >= WARNING_ERROR_RATE:
        warning_reasons.append(
            f"Warning error-rate breach: {stats.error_rate:.0%} >= {WARNING_ERROR_RATE:.0%}."
        )

    if stats.avg_latency_ms >= CRITICAL_AVG_LATENCY_MS:
        critical_reasons.append(
            f"Critical average-latency breach: {stats.avg_latency_ms:.0f} ms >= {CRITICAL_AVG_LATENCY_MS} ms."
        )
    elif stats.avg_latency_ms >= WARNING_AVG_LATENCY_MS:
        warning_reasons.append(
            f"Warning average-latency breach: {stats.avg_latency_ms:.0f} ms >= {WARNING_AVG_LATENCY_MS} ms."
        )

    if stats.p95_latency_ms >= CRITICAL_P95_LATENCY_MS:
        critical_reasons.append(
            f"Critical p95-latency breach: {stats.p95_latency_ms:.0f} ms >= {CRITICAL_P95_LATENCY_MS} ms."
        )
    elif stats.p95_latency_ms >= WARNING_P95_LATENCY_MS:
        warning_reasons.append(
            f"Warning p95-latency breach: {stats.p95_latency_ms:.0f} ms >= {WARNING_P95_LATENCY_MS} ms."
        )

    if critical_reasons:
        return AnomalyResult(
            is_anomaly=True,
            severity="critical",
            title="Critical service health anomaly detected",
            evidence=evidence + critical_reasons + warning_reasons,
            stats=stats,
        )

    if warning_reasons:
        return AnomalyResult(
            is_anomaly=True,
            severity="warning",
            title="Service health anomaly detected",
            evidence=evidence + warning_reasons,
            stats=stats,
        )

    return AnomalyResult(
        is_anomaly=False,
        severity="info",
        title="Service healthy",
        evidence=evidence + ["No warning or critical thresholds were breached."],
        stats=stats,
    )


def calculate_window_stats(events: list[TelemetryEvent]) -> WindowStats:
    error_count = 0
    latencies: list[float] = []

    for event in events:
        status_code = int(event.attributes.get("status_code", 200))
        latency_ms = float(event.attributes.get("latency_ms", 0))

        if status_code >= 500:
            error_count += 1

        if latency_ms > 0:
            latencies.append(latency_ms)

    error_rate = error_count / len(events)
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    p95_latency = calculate_percentile(latencies, 0.95)

    return WindowStats(
        sample_count=len(events),
        error_count=error_count,
        error_rate=error_rate,
        avg_latency_ms=avg_latency,
        p95_latency_ms=p95_latency,
    )


def calculate_percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0

    sorted_values = sorted(values)
    index = max(0, min(len(sorted_values) - 1, round((len(sorted_values) - 1) * percentile)))
    return sorted_values[index]


def build_window_evidence(stats: WindowStats) -> list[str]:
    return [
        f"Analyzed the last {stats.sample_count} request events.",
        f"Error count is {stats.error_count}/{stats.sample_count} ({stats.error_rate:.0%}).",
        f"Average latency is {stats.avg_latency_ms:.0f} ms.",
        f"p95 latency is {stats.p95_latency_ms:.0f} ms.",
    ]
