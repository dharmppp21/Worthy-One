import type { AITriageResponse, Incident, IncidentTimelineEntry, RootCauseResponse, Runbook, ServiceGraphResponse, SearchResponse } from "./types";

// In the production build the app is served by nginx, which proxies `/api` to
// the backend (same-origin, no CORS). In Vite dev we call the backend directly.
export const API_BASE_URL = import.meta.env.PROD ? "/api" : "http://127.0.0.1:8000";
const API_KEY = "sf-api-key-demo";  // Matches backend auth.py

class ApiError extends Error {
  constructor(
    public endpoint: string,
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }

  userMessage(): string {
    if (this.status === 0) {
      return `Cannot reach the backend. Is the server running at ${API_BASE_URL}?`;
    }
    if (this.status >= 500) {
      return `Server error on ${this.endpoint}. Try again in a moment.`;
    }
    if (this.status === 404) {
      return `Not found: ${this.endpoint}.`;
    }
    if (this.status === 422) {
      return `Invalid request to ${this.endpoint}. Check your input.`;
    }
    if (this.status === 401) {
      return `Authentication failed. Check your API key.`;
    }
    return `Request to ${this.endpoint} failed (${this.status}).`;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "X-API-Key": API_KEY,
        ...init?.headers,
      },
    });
  } catch (err) {
    throw new ApiError(path, 0, String(err));
  }
  if (!response.ok) {
    throw new ApiError(path, response.status, response.statusText);
  }
  return (await response.json()) as T;
}

export async function fetchAITriage(incidentId: string): Promise<AITriageResponse> {
  return apiFetch<AITriageResponse>(`/incidents/${encodeURIComponent(incidentId)}/ai-triage`);
}

export async function fetchRootCause(serviceName: string): Promise<RootCauseResponse> {
  return apiFetch<RootCauseResponse>(`/services/${encodeURIComponent(serviceName)}/root-cause`);
}

export async function searchKnowledgeBase(query: string, semantic: boolean = false): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (semantic) {
    params.append("semantic", "true");
  }
  return apiFetch<SearchResponse>(`/search?${params.toString()}`);
}

export async function fetchIncidents(): Promise<Incident[]> {
  const data = await apiFetch<{ count: number; incidents: Incident[] }>("/incidents");
  return data.incidents;
}

export async function fetchIncidentDetail(incidentId: string): Promise<Incident> {
  return apiFetch<Incident>(`/incidents/${encodeURIComponent(incidentId)}`);
}

export async function updateIncidentStatus(
  incidentId: string,
  status: "investigating" | "mitigated" | "resolved",
  actor: string = "operator",
  note?: string
): Promise<Incident> {
  return apiFetch<Incident>(`/incidents/${encodeURIComponent(incidentId)}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, actor, note }),
  });
}

export async function fetchServiceGraph(): Promise<ServiceGraphResponse> {
  return apiFetch<ServiceGraphResponse>("/graph/auto");
}

export async function fetchRunbooks(serviceName?: string): Promise<Runbook[]> {
  const params = serviceName ? `?service_name=${encodeURIComponent(serviceName)}` : "";
  return apiFetch<Runbook[]>(`/runbooks${params}`);
}

export async function createRunbook(data: {
  tenant_id: string;
  service_name: string;
  title: string;
  description: string;
  steps: string[];
}): Promise<Runbook> {
  return apiFetch<Runbook>("/runbooks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deleteRunbook(runbookId: string): Promise<void> {
  return apiFetch<void>(`/runbooks/${encodeURIComponent(runbookId)}`, {
    method: "DELETE",
  });
}

/* ─── Topology / Discovery API ─── */

export type DiscoveredService = {
  service_id: string;
  service_name: string;
  service_type: string;
  host: string;
  endpoints: string[];
  discovery_source: string;
  first_seen_at: string;
  last_heartbeat_at: string;
  metadata: Record<string, any>;
  health_status?: "up" | "down" | "unknown";
};

export type ServiceHealth = {
  service_id: string;
  service_name: string;
  status: "up" | "down" | "unknown";
  last_probe_at: string;
  uptime_percentage: number;
  response_time_ms: number;
};

export type AutoDependencyEdge = {
  source: string;
  target: string;
  dependency_type: string;
  confidence: number;
  connection_count: number;
  avg_latency_ms: number;
  error_rate: number;
  sources: string[];
  first_detected_at: string;
  last_updated_at: string;
};

export type AutoDependencyGraph = {
  nodes: DiscoveredService[];
  edges: AutoDependencyEdge[];
  generated_at: string;
};

export type DiscoveryEvent = {
  type: "service_discovered" | "service_removed" | "health_changed" | "dependency_detected" | "dependency_removed";
  service_name: string;
  detail: string;
  severity: "info" | "warning" | "critical";
  timestamp: string;
};

export async function fetchDiscoveredServices(): Promise<DiscoveredService[]> {
  return apiFetch<DiscoveredService[]>("/services/discovered");
}

export async function fetchAutoGraph(): Promise<AutoDependencyGraph> {
  return apiFetch<AutoDependencyGraph>("/graph/dependencies");
}

export async function fetchServicesHealth(): Promise<ServiceHealth[]> {
  return apiFetch<ServiceHealth[]>("/services/health");
}

export async function fetchIncidentsByService(serviceName: string): Promise<Incident[]> {
  const data = await apiFetch<{ count: number; incidents: Incident[] }>(
    `/incidents?service_name=${encodeURIComponent(serviceName)}`
  );
  return data.incidents;
}

export { ApiError };
