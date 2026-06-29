# SignalForge Demo Walkthrough

A repeatable, 5-minute demo that tells the full story: healthy traffic → bad
deployment → cascading failure → incident creation → structured evidence →
root cause → runbook retrieval → AI triage.

---

## Setup (30 seconds)

```powershell
cd signalforge_mvp/backend
.venv/Scripts/python.exe ../scripts/seed_demo.py
```

This creates a complete, deterministic demo dataset with 50 events, 1 critical
incident, 2 runbooks, and 1 deployment — all linked to the same story.

Start the backend:

```powershell
uvicorn app.main:app --reload
```

Open the dashboard: `http://localhost:5173` (or `http://localhost:80` if using Docker)

---

## The Story

**Notification-service v2.1.0 was deployed with a bug. It started returning 500
errors with 2000ms+ latency. Checkout-service, which depends on notification-service,
cascaded into failure. The system detected the anomaly, created an incident with
structured evidence, correlated the deployment, and surfaced the runbook.**

---

## Demo Script (5 minutes)

### Step 1: Show the healthy baseline (30 seconds)

> **Say:** "Before the incident, all 5 services were healthy."

Open the dashboard. The incident feed may be empty or show the resolved baseline.

Show the API:

```powershell
curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/events
```

> **Say:** "20 healthy metric events, 200ms latency, 200 OK status. Normal traffic
> across checkout, payment, inventory, fraud, and notification services."

---

### Step 2: Trigger the bad deployment (30 seconds)

> **Say:** "Then a deployment happened."

Show the deployment event:

```powershell
curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/deployments
```

Response:

```json
{
  "deployments": [
    {
      "event_id": "demo-deploy-001",
      "service_name": "notification-service",
      "event_type": "deployment",
      "attributes": { "version": "v2.1.0" }
    }
  ]
}
```

> **Say:** "Notification-service v2.1.0 was deployed. This is the change event
> that will correlate with the incident."

---

### Step 3: Show the incident (1 minute)

> **Say:** "Immediately after the deployment, the anomaly detector flagged
> notification-service as critical."

Show the incident:

```powershell
curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/incidents
```

Response (excerpt):

```json
{
  "incidents": [
    {
      "id": "...",
      "service_name": "notification-service",
      "severity": "critical",
      "status": "investigating",
      "title": "Anomaly detected on notification-service",
      "evidence": [
        {
          "type": "anomaly_stats",
          "sample_count": 21,
          "error_count": 20,
          "error_rate": 0.95,
          "avg_latency_ms": 2000,
          "p95_latency_ms": 2041,
          "breached_thresholds": ["critical_error_rate"]
        }
      ],
      "timeline": [
        { "event_type": "incident_opened", "message": "Incident opened..." },
        { "event_type": "evidence_added", "message": "Attached rolling-window context..." },
        { "event_type": "evidence_added", "message": "Recent deployment detected: notification-service v2.1.0" }
      ]
    }
  ]
}
```

> **Say:** "The incident has structured evidence: 21 events sampled, 20 errors,
> 95% error rate, 2000ms average latency. The timeline shows three things:
> the incident was opened, the rolling window context was attached, and the
> deployment was correlated. This is all automatic — no human had to piece
> together the timeline."

---

### Step 4: Show the service graph (1 minute)

> **Say:** "The service graph shows why checkout-service also failed."

```powershell
curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/graph
```

Response:

```json
{
  "nodes": [
    { "id": "checkout-service", "label": "checkout-service" },
    { "id": "payment-service", "label": "payment-service" },
    { "id": "inventory-service", "label": "inventory-service" },
    { "id": "fraud-service", "label": "fraud-service" },
    { "id": "notification-service", "label": "notification-service" }
  ],
  "edges": [
    { "source": "checkout-service", "target": "payment-service", "label": "calls", "count": 10 },
    { "source": "checkout-service", "target": "inventory-service", "label": "calls", "count": 10 },
    { "source": "checkout-service", "target": "notification-service", "label": "calls", "count": 10 },
    { "source": "payment-service", "target": "fraud-service", "label": "calls", "count": 10 }
  ]
}
```

> **Say:** "Checkout-service calls payment, inventory, and notification. When
> notification-service fails, checkout-service cascades. The graph shows the
> dependency — not just that checkout failed, but *why* it failed. We also
> have 10 trace events showing checkout -> notification returning 500 errors."

---

### Step 5: Root cause analysis (1 minute)

> **Say:** "The root cause engine scores evidence across 5 dimensions."

```powershell
curl -H "X-API-Key: sf-api-key-demo" \
  "http://localhost:8000/services/notification-service/root-cause"
```

Response (excerpt):

```json
{
  "service_name": "notification-service",
  "hypotheses": [
    {
      "score": 85,
      "summary": "Recent deployment v2.1.0 + critical error rate (95%) + failed traces",
      "evidence": [
        "Deployment v2.1.0 deployed minutes ago",
        "Error rate: 95% (threshold: 50%)",
        "p95 latency: 2041ms (threshold: 2500ms)",
        "10 failed traces to notification-service"
      ]
    }
  ]
}
```

> **Say:** "Score 85 out of 100. High confidence. The evidence is explicit:
> deployment v2.1.0, 95% error rate, 2041ms p95 latency, 10 failed traces.
> This is rule-based, not a black box. Every point in the score is traceable
> to an actual event in the database."

---

### Step 6: Runbook retrieval (30 seconds)

> **Say:** "The system also surfaced the runbook for this service."

```powershell
curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/runbooks
```

Response (excerpt):

```json
[
  {
    "id": "rb-notification-001",
    "service_name": "notification-service",
    "title": "Notification Service Recovery Playbook",
    "steps": [
      "Check deployment history for recent changes",
      "Verify database connection pool settings",
      "Restart notification-service pods if connection pool is exhausted",
      "Check downstream queue depth (Kafka/SQS)",
      "If rolling back, use version tag from last known good deployment"
    ]
  }
]
```

> **Say:** "The first step is 'check deployment history for recent changes' —
> which we already did automatically. The last step is 'use version tag from
> last known good deployment' — which is exactly what we need: rollback to
> v2.0.0 or whatever the previous stable version was."

---

### Step 7: AI triage (30 seconds)

> **Say:** "The AI triage assistant analyzes the evidence and suggests actions."

```powershell
curl -H "X-API-Key: sf-api-key-demo" \
  "http://localhost:8000/incidents/{incident-id}/ai-triage"
```

Response (excerpt, mock provider):

```json
{
  "incident_id": "...",
  "summary": "notification-service is experiencing 500 errors with high latency.
    Recent deployment v2.1.0 correlates with the incident onset.",
  "likely_causes": [
    "Deployment v2.1.0 introduced a bug causing 500 errors",
    "Database connection pool exhausted after deployment"
  ],
  "evidence_points": [
    "Error rate increased from 0% to 95% after v2.1.0 deployment",
    "p95 latency jumped from 200ms to 2041ms",
    "10 failed traces from checkout-service to notification-service"
  ],
  "suggested_actions": [
    "Rollback deployment v2.1.0 to previous stable version",
    "Check database connection pool settings",
    "Verify checkout-service health after notification recovers"
  ],
  "confidence": "high"
}
```

> **Say:** "The AI doesn't guess — it reads the evidence we already collected.
> The summary mentions the deployment correlation. The suggested actions include
> rollback, which is the same as the runbook's recommendation. If OpenAI is
> unavailable, it falls back to a deterministic mock provider that still produces
> structured output."

---

### Step 8: Search (30 seconds)

> **Say:** "We can search across incidents and runbooks by keyword."

```powershell
curl -H "X-API-Key: sf-api-key-demo" \
  "http://localhost:8000/search?q=notification&tenant_id=demo-company"
```

> **Say:** "Searching for 'notification' returns the incident and the runbook
> in one result set. This is operational memory — past incidents and how to
> fix them, linked together."

---

## Closing Statement (15 seconds)

> **Say:** "SignalForge detected the anomaly in under 1 second after the 20th
> bad event. It created an incident with structured evidence, correlated the
> deployment, showed the service dependency graph, ranked the root cause with
> traceable evidence, retrieved the runbook, and suggested AI-generated actions.
> The entire pipeline is automatic: event ingestion, anomaly detection, incident
> creation, evidence gathering, root cause ranking, and operational memory
> retrieval. The engineer just has to read the incident and follow the runbook."

---

## Commands Cheat Sheet

```powershell
# Seed demo data (run once)
cd signalforge_mvp/backend
.venv/Scripts/python.exe ../scripts/seed_demo.py

# Start backend
uvicorn app.main:app --reload

# API queries (with auth header)
curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/health
curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/incidents
curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/events
curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/graph
curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/deployments
curl -H "X-API-Key: sf-api-key-demo" http://localhost:8000/runbooks
curl -H "X-API-Key: sf-api-key-demo" \
  "http://localhost:8000/services/notification-service/root-cause"
curl -H "X-API-Key: sf-api-key-demo" \
  "http://localhost:8000/search?q=notification&tenant_id=demo-company"

# Dashboard
http://localhost:5173   # or http://localhost:80 with Docker
```

---

## What the Seed Script Creates

| Phase | Events | Description |
|-------|--------|-------------|
| 1 | 20 healthy metric | All 5 services, 200ms, 200 OK |
| 2 | 1 deployment | notification-service v2.1.0 |
| 3 | 20 bad metric | notification-service, 500 errors, 2000-2500ms |
| 4 | 10 bad trace | checkout -> notification, 500 errors |
| 5 | 10 bad metric | checkout-service, 500 errors, 2200ms |
| 6 | 5 error logs | "connection pool exhausted" |
| 7 | 2 runbooks | checkout-service and notification-service playbooks |

**Result:** 1 critical incident (notification-service) with deployment correlation,
anomaly evidence, and cascading impact. 2 runbooks ready for retrieval.

---

## Demo Tips

- **Run the seed script first** — it resets the database and creates a clean story.
- **Start the backend second** — the seed creates data in the database directly.
- **Open the dashboard third** — the data is already there, no waiting.
- **Use the API curl commands** — they show the raw JSON, which is impressive
  for technical interviews.
- **Tell the story, not the tech** — "A bad deploy caused a cascade. The system
detected it, created an incident, found the root cause, and retrieved the runbook."
- **Mention the numbers** — "95% error rate, 2041ms p95, 10 failed traces, score 85."

