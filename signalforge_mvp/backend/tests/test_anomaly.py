from datetime import datetime, timezone

from app.anomaly import analyze_service_window
from app.schemas import EventType, TelemetryEvent


def make_request_event(index: int, status_code: int = 200, latency_ms: int = 120) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=f"test-metric-{index:03d}",
        tenant_id="demo-company",
        service_name="payment-service",
        event_type=EventType.metric,
        timestamp=datetime.now(timezone.utc),
        name="http_request",
        value=1,
        attributes={
            "status_code": status_code,
            "latency_ms": latency_ms,
            "endpoint": "/charge",
        },
    )


def test_not_enough_samples_is_not_anomaly():
    events = [make_request_event(index) for index in range(10)]

    result = analyze_service_window(events)

    assert result.is_anomaly is False
    assert result.severity == "info"
    assert "Need at least 20 request events" in result.evidence[0]


def test_healthy_window_is_not_anomaly():
    events = [make_request_event(index, status_code=200, latency_ms=120) for index in range(20)]

    result = analyze_service_window(events)

    assert result.is_anomaly is False
    assert result.severity == "info"
    assert result.stats is not None
    assert result.stats.error_rate == 0


def test_warning_error_rate_is_anomaly():
    events = [make_request_event(index, status_code=500, latency_ms=120) for index in range(4)]
    events += [make_request_event(index + 4, status_code=200, latency_ms=120) for index in range(16)]

    result = analyze_service_window(events)

    assert result.is_anomaly is True
    assert result.severity == "warning"
    assert any("Warning error-rate breach" in item for item in result.evidence)


def test_warning_average_latency_is_anomaly():
    events = [make_request_event(index, status_code=200, latency_ms=1200) for index in range(20)]

    result = analyze_service_window(events)

    assert result.is_anomaly is True
    assert result.severity == "warning"
    assert any("Warning average-latency breach" in item for item in result.evidence)


def test_warning_p95_latency_is_anomaly():
    events = [make_request_event(index, status_code=200, latency_ms=120) for index in range(18)]
    events += [make_request_event(18, status_code=200, latency_ms=1800)]
    events += [make_request_event(19, status_code=200, latency_ms=1900)]

    result = analyze_service_window(events)

    assert result.is_anomaly is True
    assert result.severity == "warning"
    assert any("Warning p95-latency breach" in item for item in result.evidence)


def test_critical_error_rate_is_anomaly():
    events = [make_request_event(index, status_code=500, latency_ms=120) for index in range(10)]
    events += [make_request_event(index + 10, status_code=200, latency_ms=120) for index in range(10)]

    result = analyze_service_window(events)

    assert result.is_anomaly is True
    assert result.severity == "critical"
    assert any("Critical error-rate breach" in item for item in result.evidence)


def test_critical_p95_latency_is_anomaly():
    events = [make_request_event(index, status_code=200, latency_ms=120) for index in range(18)]
    events += [make_request_event(18, status_code=200, latency_ms=2600)]
    events += [make_request_event(19, status_code=200, latency_ms=2700)]

    result = analyze_service_window(events)

    assert result.is_anomaly is True
    assert result.severity == "critical"
    assert any("Critical p95-latency breach" in item for item in result.evidence)


def test_critical_average_latency_is_anomaly():
    events = [make_request_event(index, status_code=200, latency_ms=1900) for index in range(20)]

    result = analyze_service_window(events)

    assert result.is_anomaly is True
    assert result.severity == "critical"
    assert any("Critical average-latency breach" in item for item in result.evidence)
