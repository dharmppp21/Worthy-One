# SignalForge Mobile

A native (Expo / React Native) client for the SignalForge incident platform. It
plays two roles against **any** SignalForge backend:

- **Viewer** — browse incidents, open root-cause analysis and the remediation
  proposal, and **approve/reject a rollback** from your phone.
- **Telemetry source** — send request metrics to SignalForge's `/ingest` API
  straight from the device, and show the OTLP endpoint + env vars so any other
  instrumented system can connect.

It talks to the backend over plain REST (`X-API-Key` auth), so it works over the
public internet, a LAN IP, or localhost.

## Run

```bash
cd signalforge_mvp/mobile
npm install            # or: npx expo install
npm run web            # preview in a browser
npm run ios            # or: npm run android  (device/simulator)
```

## Connect it to your SignalForge

Open **Settings** and set:

| Field | Example |
|-------|---------|
| Base URL | `https://your-host/api` (include the `/api` proxy prefix the web dashboard uses), or `http://192.168.1.20:8000` for a LAN backend |
| API key | `sf-api-key-demo` (sent as `X-API-Key`) |
| Tenant | `demo-company` (stamped on telemetry this app sends) |

It defaults to the live demo deployment; override at build time with
`EXPO_PUBLIC_SIGNALFORGE_URL` / `_KEY` / `_TENANT`.

> A real device can't reach `localhost` — use your machine's LAN IP, or a public
> tunnel URL.

## Connect other systems (the real-world path)

The **Connect** tab shows the three OpenTelemetry env vars to point any
instrumented service at this SignalForge, plus the raw OTLP endpoint
(`…/api/v1/traces`). That's how a customer wires their own services in.

## Prove it from your phone

On the **Connect** tab, tap **“Send failing traffic → incident”**. The app posts
25 request metrics (HTTP 500 + high latency) to `/ingest`; after a few seconds an
incident opens, visible on the **Incidents** tab with root-cause and a rollback
proposal you can approve.

---

Cloned from the original Expo prototype and rewired: the generated
`@workspace/api-client-react` client was replaced with `lib/signalforge.ts`
(pointed at the real SignalForge REST API), and the account/paywall flow was
dropped in favour of a configurable connection.
