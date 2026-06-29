# SignalForge Sample Telemetry Events

These files are example payloads for `POST /ingest`.

Use them to understand the four current telemetry event types:

- `metric_event.json`
- `log_event.json`
- `trace_event.json`
- `deployment_event.json`

PowerShell example:

```powershell
$body = Get-Content .\signalforge_mvp\samples\metric_event.json -Raw
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/ingest" -ContentType "application/json" -Body $body
```

Duplicate protection test:

Run the same command twice with the same sample file. The first response should have `"duplicate": false`; the second response should have `"duplicate": true`.

