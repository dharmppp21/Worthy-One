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

