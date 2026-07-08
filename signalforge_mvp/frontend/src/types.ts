export type ServiceGraphNode = {
  id: string;
  label: string;
};

export type ServiceGraphEdge = {
  source: string;
  target: string;
  label: string;
  count: number;
};

export type ServiceGraphResponse = {
  nodes: ServiceGraphNode[];
  edges: ServiceGraphEdge[];
};

export type IncidentTimelineEntry = {
  timestamp: string;
  event_type: "created" | "status_changed" | "evidence_added";
  message: string;
  actor: string;
  metadata: Record<string, any>;
};

export type Incident = {
  id: string;
  tenant_id: string;
  service_name: string;
  title: string;
  severity: "critical" | "warning" | "info";
  status: "investigating" | "mitigated" | "resolved";
  summary: string;
  evidence: string[];
  timeline: IncidentTimelineEntry[];
  created_at: string;
  updated_at: string;
};

export type AITriageEvidence = {
  type: string;
  description: string;
  source: string;
};

export type AITriageResponse = {
  summary: string;
  likely_causes: string[];
  evidence_points: AITriageEvidence[];
  suggested_actions: string[];
  confidence: "high" | "medium" | "low";
  generated_by: string;
  disclaimer: string;
  generated_at: string;
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
  confidence: "high" | "medium" | "low";
  evidence: RootCauseEvidence[];
  recommended_action: string;
};

export type RootCauseResponse = {
  service_name: string;
  hypotheses: RootCauseHypothesis[];
  generated_at: string;
};

export type SearchResultItem = {
  id: string;
  type: "incident" | "runbook";
  service_name: string;
  title: string;
  summary: string | null;
  severity: string | null;
  status: string | null;
  created_at: string;
};

export type SearchResponse = {
  query: string;
  results: SearchResultItem[];
};

export type Runbook = {
  id: string;
  tenant_id: string;
  service_name: string;
  title: string;
  description: string;
  steps: string[];
  created_at: string;
  updated_at: string;
};

/* ─── Topology / Discovery Types (re-exported from api.ts for convenience) ─── */
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
  avg_latency_ms: number | null;
  error_rate: number | null;
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
