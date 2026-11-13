/**
 * SignalForge API client.
 *
 * Talks to a real SignalForge backend over its REST API. The connection
 * (base URL + API key + tenant) is configurable at runtime, so this one app
 * can point at any SignalForge instance — your live demo, a staging box, or a
 * customer's own deployment.
 *
 * Two roles:
 *  - viewer:   read incidents, root-cause and remediation (x-api-key auth).
 *  - producer: push telemetry to /ingest so the app (or a quick test) can feed
 *              SignalForge, just like any instrumented service would.
 */

export type Connection = {
  /** Base URL including any reverse-proxy prefix, e.g. https://host/api */
  baseUrl: string;
  apiKey: string;
  /** Tenant the API key belongs to; stamped on telemetry events. */
  tenant: string;
};

export type Severity = 'critical' | 'warning' | 'info';
export type IncidentStatus = 'investigating' | 'mitigated' | 'resolved';

export type IncidentTimelineEntry = {
  timestamp: string;
  event_type: 'created' | 'status_changed' | 'evidence_added' | 'remediation';
  message: string;
  actor: string;
  metadata: Record<string, unknown>;
};

export type Incident = {
  id: string;
  tenant_id: string;
  service_name: string;
  title: string;
  severity: Severity;
  status: IncidentStatus;
  summary: string;
  evidence: string[];
  timeline: IncidentTimelineEntry[];
  created_at: string;
  updated_at: string;
};

export type RootCauseEvidence = {
  type: string;
  score: number;
  reason: string;
  details: string | null;
};

export type RootCauseHypothesis = {
  rank: number;
  service_name: string;
  total_score: number;
  confidence: 'high' | 'medium' | 'low';
  evidence: RootCauseEvidence[];
  recommended_action: string;
};

export type RootCauseResponse = {
  service_name: string;
  hypotheses: RootCauseHypothesis[];
  generated_at: string;
};

export type RemediationProposal = {
  incident_id: string;
  service_name: string;
  action: 'rollback' | 'investigate';
  from_version: string | null;
  to_version: string | null;
  summary: string;
  requires_approval: boolean;
};

export type Health = {
  status: string;
  environment: string;
  dependencies: Record<string, string>;
};

export class SignalForgeError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'SignalForgeError';
  }
}

/** Trim a trailing slash so `${baseUrl}${path}` never doubles up. */
function normalizeBase(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, '');
}

async function sfFetch<T>(conn: Connection, path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${normalizeBase(conn.baseUrl)}${path}`, {
      ...init,
      headers: {
        'X-API-Key': conn.apiKey,
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    });
  } catch (err) {
    throw new SignalForgeError(0, `Cannot reach ${conn.baseUrl}. Is the backend running?`);
  }
  if (!res.ok) {
    throw new SignalForgeError(res.status, `${init?.method ?? 'GET'} ${path} failed (${res.status}).`);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/* ─── Viewer ─── */

export async function listIncidents(conn: Connection): Promise<Incident[]> {
  const data = await sfFetch<{ count: number; incidents: Incident[] }>(conn, '/incidents');
  return data.incidents;
}

export function getIncident(conn: Connection, id: string): Promise<Incident> {
  return sfFetch<Incident>(conn, `/incidents/${encodeURIComponent(id)}`);
}

export function getRootCause(conn: Connection, service: string): Promise<RootCauseResponse> {
  return sfFetch<RootCauseResponse>(conn, `/services/${encodeURIComponent(service)}/root-cause`);
}

export function getRemediation(conn: Connection, id: string): Promise<RemediationProposal> {
  return sfFetch<RemediationProposal>(conn, `/incidents/${encodeURIComponent(id)}/remediation`);
}

export function decideRemediation(
  conn: Connection,
  id: string,
  approved: boolean,
  actor = 'mobile-operator',
  note?: string,
): Promise<Incident> {
  return sfFetch<Incident>(conn, `/incidents/${encodeURIComponent(id)}/remediation/decision`, {
    method: 'POST',
    body: JSON.stringify({ approved, actor, note }),
  });
}

export function updateStatus(conn: Connection, id: string, status: IncidentStatus): Promise<Incident> {
  return sfFetch<Incident>(conn, `/incidents/${encodeURIComponent(id)}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status, actor: 'mobile-operator' }),
  });
}

export function getHealth(conn: Connection): Promise<Health> {
  return sfFetch<Health>(conn, '/health');
}

/* ─── Producer (telemetry) ─── */

/** The OTLP endpoint a customer points other instrumented systems at. */
export function otlpEndpoint(conn: Connection): string {
  return `${normalizeBase(conn.baseUrl)}/v1/traces`;
}

function requestEvent(conn: Connection, service: string, i: number, failing: boolean) {
  return {
    event_id: `mobile-${service}-${Date.now()}-${i}`,
    tenant_id: conn.tenant,
    service_name: service,
    event_type: 'metric',
    timestamp: new Date().toISOString(),
    name: 'http_request',
    value: 1,
    attributes: {
      status_code: failing ? 500 : 200,
      latency_ms: failing ? 1800 : 60,
      endpoint: '/charge',
    },
  };
}

/**
 * Push N request-metric events to /ingest from this device. `failing: true`
 * sends 500s + high latency, which trips the anomaly detector (needs ~20
 * samples) and opens a real incident — a one-tap way to prove the pipeline.
 */
export async function sendTestTraffic(
  conn: Connection,
  service: string,
  opts: { count: number; failing: boolean },
): Promise<void> {
  await Promise.all(
    Array.from({ length: opts.count }, (_, i) =>
      sfFetch(conn, '/ingest', {
        method: 'POST',
        body: JSON.stringify(requestEvent(conn, service, i, opts.failing)),
      }),
    ),
  );
}
