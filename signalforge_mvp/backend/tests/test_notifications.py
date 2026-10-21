"""Incident notifications (Slack / PagerDuty)."""

from datetime import datetime, timezone
from unittest.mock import patch

import httpx

from app import notifications
from app.schemas import Incident, IncidentStatus


def _incident() -> Incident:
    now = datetime.now(timezone.utc)
    return Incident(
        id="inc-1",
        tenant_id="demo-company",
        service_name="payment-service",
        title="Critical service health anomaly detected",
        severity="critical",
        status=IncidentStatus.investigating,
        summary="SignalForge detected abnormal behavior in payment-service.",
        evidence=["Error count is 19/20 (95%).", "p95 latency is 2330 ms."],
        created_at=now,
        updated_at=now,
    )


def test_no_channels_configured_is_noop(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("PAGERDUTY_ROUTING_KEY", raising=False)
    with patch.object(notifications.httpx, "post") as post:
        notifications.notify_incident(_incident())
    post.assert_not_called()


def test_slack_alert_payload(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    monkeypatch.delenv("PAGERDUTY_ROUTING_KEY", raising=False)
    with patch.object(notifications.httpx, "post") as post:
        notifications.notify_incident(_incident())
    post.assert_called_once()
    assert post.call_args.args[0] == "https://hooks.slack.test/x"
    body = post.call_args.kwargs["json"]
    assert "payment-service" in body["text"]
    assert body["blocks"][0]["text"]["text"].startswith("CRITICAL")


def test_pagerduty_alert_payload(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("PAGERDUTY_ROUTING_KEY", "R-123")
    with patch.object(notifications.httpx, "post") as post:
        notifications.notify_incident(_incident())
    post.assert_called_once()
    assert post.call_args.args[0] == "https://events.pagerduty.com/v2/enqueue"
    body = post.call_args.kwargs["json"]
    assert body["routing_key"] == "R-123"
    assert body["event_action"] == "trigger"
    assert body["dedup_key"] == "inc-1"
    assert body["payload"]["severity"] == "critical"


def test_both_channels_fire(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    monkeypatch.setenv("PAGERDUTY_ROUTING_KEY", "R-123")
    with patch.object(notifications.httpx, "post") as post:
        notifications.notify_incident(_incident())
    assert post.call_count == 2


def test_failed_webhook_does_not_raise(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    monkeypatch.delenv("PAGERDUTY_ROUTING_KEY", raising=False)
    with patch.object(notifications.httpx, "post", side_effect=httpx.ConnectError("down")):
        notifications.notify_incident(_incident())  # must not raise
