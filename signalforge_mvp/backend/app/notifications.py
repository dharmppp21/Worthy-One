"""Incident notifications to Slack and PagerDuty.

Fire-and-forget alerts when a new incident opens, so an on-call engineer is
notified without watching the dashboard. Configured by environment variables;
with no channel set this is a silent no-op, matching how Redis/Kafka degrade.

    SLACK_WEBHOOK_URL       Slack incoming-webhook URL
    PAGERDUTY_ROUTING_KEY   PagerDuty Events API v2 routing key

ponytail: sends synchronously with a short timeout — fine at incident volumes
(one open incident per service). Move to a background task/queue if that grows.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.schemas import Incident

logger = logging.getLogger(__name__)

_PAGERDUTY_URL = "https://events.pagerduty.com/v2/enqueue"
_TIMEOUT = 5.0
_PD_SEVERITY = {"critical": "critical", "warning": "warning", "info": "info"}


def notify_incident(incident: Incident) -> None:
    """Send the incident to every configured channel. Never raises."""
    slack_url = os.environ.get("SLACK_WEBHOOK_URL")
    if slack_url:
        _post("slack", slack_url, _slack_payload(incident))

    pagerduty_key = os.environ.get("PAGERDUTY_ROUTING_KEY")
    if pagerduty_key:
        _post("pagerduty", _PAGERDUTY_URL, _pagerduty_payload(incident, pagerduty_key))


def _post(channel: str, url: str, payload: dict) -> None:
    try:
        httpx.post(url, json=payload, timeout=_TIMEOUT).raise_for_status()
        logger.info("Sent %s alert for incident", channel)
    except httpx.HTTPError as exc:
        # A failing webhook must never break incident creation.
        logger.warning("Failed to send %s alert: %s", channel, exc)


def _slack_payload(incident: Incident) -> dict:
    evidence = "\n".join(f"• {line}" for line in incident.evidence[:6])
    heading = f"{incident.severity.upper()}: {incident.title}"
    return {
        "text": f":rotating_light: {incident.severity.upper()} incident — "
        f"{incident.service_name}: {incident.title}",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": heading}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Service:* {incident.service_name}\n"
                    f"*Status:* {incident.status.value}\n\n{evidence}",
                },
            },
        ],
    }


def _pagerduty_payload(incident: Incident, routing_key: str) -> dict:
    return {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": incident.id,
        "payload": {
            "summary": f"{incident.severity.upper()}: {incident.title}",
            "source": incident.service_name or "signalforge",
            "severity": _PD_SEVERITY.get(incident.severity, "warning"),
            "custom_details": {
                "evidence": incident.evidence,
                "status": incident.status.value,
            },
        },
    }
