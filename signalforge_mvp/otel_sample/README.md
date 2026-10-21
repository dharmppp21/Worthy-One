# OTel sample service — real telemetry for SignalForge

A tiny FastAPI service instrumented with the OpenTelemetry SDK. Its requests
export as real OTLP traces to the SignalForge backend (`POST /v1/traces`), which
maps them into metrics, incidents and dependency edges. This replaces the
traffic simulator with a **real** telemetry source.

## Run (PowerShell)

1. Start the backend (from `signalforge_mvp/backend`):
   ```powershell
   .\.venv\Scripts\python -m uvicorn app.main:app --port 8000
   ```
2. Start this sample (from `signalforge_mvp/otel_sample`):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\pip install -r requirements.txt
   $env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:8000"
   $env:OTEL_EXPORTER_OTLP_HEADERS  = "x-api-key=sf-api-key-demo"
   $env:OTEL_SERVICE_NAME           = "payment-service"
   .\.venv\Scripts\python -m uvicorn main:app --port 8090
   ```
3. Generate load (≥20 requests arms the anomaly detector):
   ```powershell
   1..30 | ForEach-Object { Invoke-WebRequest -UseBasicParsing http://localhost:8090/charge | Out-Null }
   ```
   The dashboard (`http://localhost:8080`) now shows real request metrics for
   `payment-service` — no incident yet, because it's healthy.

## Simulate a bad deploy

Restart the sample with `BROKEN=1` (500s + high latency), then send load again:
```powershell
$env:BROKEN = "1"
.\.venv\Scripts\python -m uvicorn main:app --port 8090
# in another terminal:
1..30 | ForEach-Object { try { Invoke-WebRequest -UseBasicParsing http://localhost:8090/charge | Out-Null } catch {} }
```
Within a few seconds SignalForge opens a `payment-service` incident from **real**
OTel data.

## Show a dependency edge

Run a second instance as the downstream service and point the first at it with
`PAYMENT_URL`, e.g. `$env:PAYMENT_URL = "http://localhost:8091/charge"`. The
outbound call produces a `service_call` span → a dependency edge in the topology.

## Config

| Env var | Meaning | Default |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | SignalForge backend base URL | — (required) |
| `OTEL_EXPORTER_OTLP_HEADERS` | must include `x-api-key=<key>` | — (required) |
| `OTEL_SERVICE_NAME` | service name shown in SignalForge | `payment-service` |
| `PAYMENT_URL` | optional downstream dependency to call | unset |
| `BROKEN` | `1` = fail + slow (bad-deploy demo) | `0` |
