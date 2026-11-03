"""The Redis anomaly-detection window must hold only request-metric samples.

Regression test: OTLP enrichment emits a span_error log per failing request. If
those (and other non-metric events) enter the fixed-size rolling window, they
evict real http_request samples and starve incident detection when Redis is on.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from app.schemas import EventType, TelemetryEvent
from app.storage import store


def _metric(i: int) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=f"win-metric-{i}", tenant_id="demo-company", service_name="svc",
        event_type=EventType.metric, timestamp=datetime.now(timezone.utc),
        name="http_request", value=1, attributes={"status_code": 500, "latency_ms": 100},
    )


def _log(i: int) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=f"win-log-event-{i}", tenant_id="demo-company", service_name="svc",
        event_type=EventType.log, timestamp=datetime.now(timezone.utc),
        name="span_error", severity="error", message="boom",
    )


def test_rolling_window_only_receives_request_metrics(reset_store):
    with patch("app.storage.redis_window.add_event") as push:
        assert store.add_event(_metric(1)) is True
        assert store.add_event(_log(1)) is True          # persisted, but...
        assert store.add_event(_metric(2)) is True

    # ...only the two http_request metrics reach the rolling window; the
    # span_error log does not.
    assert push.call_count == 2
    pushed_names = [call.args[2]["name"] for call in push.call_args_list]
    assert pushed_names == ["http_request", "http_request"]
