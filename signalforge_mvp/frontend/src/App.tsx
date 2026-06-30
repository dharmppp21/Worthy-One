import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchAITriage, fetchIncidentDetail, fetchIncidents, fetchRootCause, fetchServiceGraph,
  searchKnowledgeBase, updateIncidentStatus, ApiError,
  fetchDiscoveredServices, fetchAutoGraph, fetchServicesHealth,
} from "./api";
import { fetchRunbooks, createRunbook, deleteRunbook } from "./api";
import { RunbookPanel } from "./components/RunbookPanel";
import { ServiceGraphView } from "./components/ServiceGraph";
import ServiceTopologyMap from "./components/ServiceTopologyMap";
import ServiceDetailsPanel from "./components/ServiceDetailsPanel";
import DiscoveryEventFeed from "./components/DiscoveryEventFeed";
import type { Incident, IncidentTimelineEntry, AITriageResponse, RootCauseResponse, Runbook, SearchResultItem, DiscoveredService, DiscoveryEvent } from "./types";
import "./App.css";

const queryClient = new QueryClient();

/* ─────────── Helpers ─────────── */
function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function severityIcon(severity: string): string {
  switch (severity) {
    case "critical": return "🔴";
    case "warning": return "🟡";
    default: return "🔵";
  }
}

function timelineIcon(eventType: string): string {
  switch (eventType) {
    case "created": return "🚨";
    case "status_changed": return "📝";
    case "evidence_added": return "📊";
    default: return "📌";
  }
}

/* ─────────── Incident Card ─────────── */
function IncidentCard({
  incident,
  onClick,
}: {
  incident: Incident;
  onClick: (id: string) => void;
}) {
  return (
    <article
      className={`incident-card severity-${incident.severity}`}
      onClick={() => onClick(incident.id)}
      role="button"
      tabIndex={0}
    >
      <div className="incident-card-header">
        <div className="incident-card-meta">
          <span className={`severity-badge severity-${incident.severity}`}>
            {severityIcon(incident.severity)} {incident.severity}
          </span>
          <span className={`status-badge status-${incident.status}`}>
            {incident.status}
          </span>
        </div>
        <span className="incident-time" title={formatDate(incident.created_at)}>
          {relativeTime(incident.created_at)}
        </span>
      </div>

      <h3 className="incident-title">{incident.title}</h3>
      <p className="incident-summary">{incident.summary}</p>

      <div className="incident-footer">
        <span className="service-tag">{incident.service_name}</span>
        <span className="evidence-count">
          {incident.evidence.length} evidence items
        </span>
      </div>
    </article>
  );
}

/* ─────────── Search Result Card ─────────── */
function SearchResultCard({
  result,
  onIncidentClick,
}: {
  result: SearchResultItem;
  onIncidentClick: (id: string) => void;
}) {
  const isIncident = result.type === "incident";
  return (
    <article
      className={`search-result-card ${isIncident ? "severity-" + (result.severity || "info") : "runbook-result"}`}
      onClick={() => isIncident && onIncidentClick(result.id)}
      role="button"
      tabIndex={0}
      style={{ cursor: isIncident ? "pointer" : "default" }}
    >
      <div className="search-result-header">
        <span className={`search-result-type ${result.type}`}>{result.type}</span>
        <span className="incident-time" title={formatDate(result.created_at)}>
          {relativeTime(result.created_at)}
        </span>
      </div>
      <h3 className="incident-title">{result.title}</h3>
      {result.summary && <p className="incident-summary">{result.summary}</p>}
      <div className="search-result-footer">
        <span className="service-tag">{result.service_name}</span>
        {isIncident && result.status && (
          <span className={`status-badge status-${result.status}`}>{result.status}</span>
        )}
      </div>
    </article>
  );
}

/* ─────────── Timeline Entry ─────────── */
function TimelineEntry({ entry }: { entry: IncidentTimelineEntry }) {
  const isDeployment = entry.metadata?.deployment_version !== undefined;

  return (
    <div className={`timeline-entry ${isDeployment ? "timeline-deployment" : ""}`}>
      <div className="timeline-dot">{timelineIcon(entry.event_type)}</div>
      <div className="timeline-content">
        <div className="timeline-header">
          <span className="timeline-type">{entry.event_type.replace("_", " ")}</span>
          <span className="timeline-time">{formatDate(entry.timestamp)}</span>
        </div>
        <p className="timeline-message">{entry.message}</p>
        {entry.actor !== "system" && (
          <span className="timeline-actor">by {entry.actor}</span>
        )}
        {entry.metadata && Object.keys(entry.metadata).length > 0 && (
          <div className="timeline-meta">
            {entry.metadata.recent_event_count !== undefined && (
              <span>{entry.metadata.recent_event_count} events</span>
            )}
            {entry.metadata.error_rate !== undefined && (
              <span>Error rate: {(entry.metadata.error_rate * 100).toFixed(0)}%</span>
            )}
            {entry.metadata.avg_latency_ms !== undefined && (
              <span>Avg latency: {entry.metadata.avg_latency_ms.toFixed(0)}ms</span>
            )}
            {entry.metadata.deployment_version !== undefined && (
              <span className="deployment-badge">
                🚀 v{entry.metadata.deployment_version} ({entry.metadata.deployments_in_window} deploys in window)
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ─────────── Related Runbooks ─────────── */
function RelatedRunbooks({ serviceName }: { serviceName: string }) {
  const { data: relatedRunbooks } = useQuery({
    queryKey: ["runbooks", serviceName],
    queryFn: () => fetchRunbooks(serviceName),
    enabled: !!serviceName,
  });

  if (!relatedRunbooks || relatedRunbooks.length === 0) return null;

  return (
    <div className="detail-section">
      <h4>Related Runbooks</h4>
      <div className="related-runbooks">
        {relatedRunbooks.map((rb) => (
          <div key={rb.id} className="related-runbook-card">
            <div className="related-runbook-title">📖 {rb.title}</div>
            <p className="related-runbook-desc">{rb.description}</p>
            {rb.steps.length > 0 && (
              <ol className="related-runbook-steps">
                {rb.steps.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ol>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function RootCausePanel({ serviceName }: { serviceName: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["root-cause", serviceName],
    queryFn: () => fetchRootCause(serviceName),
    enabled: !!serviceName,
  });

  if (isLoading) {
    return (
      <div className="detail-section">
        <h4>Root Cause Analysis</h4>
        <div className="loading-state" style={{ padding: "20px" }}>
          <div className="spinner" />
          <p>Analyzing evidence...</p>
        </div>
      </div>
    );
  }

  if (!data || data.hypotheses.length === 0) {
    return (
      <div className="detail-section">
        <h4>Root Cause Analysis</h4>
        <p className="empty-hint">No root-cause hypotheses available.</p>
      </div>
    );
  }

  const topHypothesis = data.hypotheses[0];

  return (
    <div className="detail-section">
      <h4>Root Cause Analysis</h4>
      <div className={`root-cause-card confidence-${topHypothesis.confidence}`}>
        <div className="root-cause-header">
          <span className="root-cause-rank">#{topHypothesis.rank}</span>
          <span className="root-cause-service">{topHypothesis.service_name}</span>
          <span className={`root-cause-confidence confidence-${topHypothesis.confidence}`}>
            {topHypothesis.confidence}
          </span>
        </div>
        <div className="root-cause-score-bar">
          <div
            className="root-cause-score-fill"
            style={{ width: `${topHypothesis.total_score}%` }}
          />
          <span className="root-cause-score-text">{topHypothesis.total_score}/100</span>
        </div>
        <p className="root-cause-action">
          <strong>Recommended:</strong> {topHypothesis.recommended_action}
        </p>
      </div>

      <div className="root-cause-evidence">
        <h5>Evidence breakdown</h5>
        {topHypothesis.evidence
          .filter((e) => e.score > 0)
          .map((e, i) => (
            <div key={i} className="root-cause-evidence-item">
              <div className="evidence-type">{e.type}</div>
              <div className="evidence-score">+{e.score}</div>
              <div className="evidence-reason">{e.reason}</div>
              {e.details && <div className="evidence-details">{e.details}</div>}
            </div>
          ))}
      </div>

      {data.hypotheses.length > 1 && (
        <div className="root-cause-alternatives">
          <h5>Alternative hypotheses</h5>
          {data.hypotheses.slice(1).map((h) => (
            <div key={h.rank} className={`root-cause-alt confidence-${h.confidence}`}>
              <span className="root-cause-alt-rank">#{h.rank}</span>
              <span className="root-cause-alt-service">{h.service_name}</span>
              <span className="root-cause-alt-score">{h.total_score}/100</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
function AITriagePanel({ incidentId }: { incidentId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["ai-triage", incidentId],
    queryFn: () => fetchAITriage(incidentId),
    enabled: !!incidentId,
  });

  if (isLoading) {
    return (
      <div className="detail-section">
        <h4>AI Triage</h4>
        <div className="loading-state" style={{ padding: "20px" }}>
          <div className="spinner" />
          <p>Generating AI analysis...</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="detail-section">
        <h4>AI Triage</h4>
        <p className="empty-hint">AI triage is not available.</p>
      </div>
    );
  }

  return (
    <div className="detail-section">
      <h4>AI Triage</h4>
      <div className={`ai-triage-card confidence-${data.confidence}`}>
        <div className="ai-triage-header">
          <span className={`ai-triage-confidence confidence-${data.confidence}`}>
            {data.confidence} confidence
          </span>
          <span className="ai-triage-source">via {data.generated_by}</span>
        </div>
        <p className="ai-triage-summary">{data.summary}</p>
      </div>

      {data.likely_causes.length > 0 && (
        <div className="ai-triage-section">
          <h5>Likely Causes</h5>
          <ol className="ai-triage-list">
            {data.likely_causes.map((cause, i) => (
              <li key={i}>{cause}</li>
            ))}
          </ol>
        </div>
      )}

      {data.evidence_points.length > 0 && (
        <div className="ai-triage-section">
          <h5>Evidence</h5>
          <ul className="ai-triage-evidence">
            {data.evidence_points.map((pt, i) => (
              <li key={i} className="ai-triage-evidence-item">
                <span className="ai-triage-evidence-type">{pt.type}</span>
                <span className="ai-triage-evidence-desc">{pt.description}</span>
                <span className="ai-triage-evidence-source">({pt.source})</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.suggested_actions.length > 0 && (
        <div className="ai-triage-section">
          <h5>Suggested Actions</h5>
          <ul className="ai-triage-list">
            {data.suggested_actions.map((action, i) => (
              <li key={i}>{action}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="ai-triage-disclaimer">{data.disclaimer}</p>
    </div>
  );
}
function IncidentDetail({
  incident,
  onClose,
  onStatusUpdate,
}: {
  incident: Incident;
  onClose: () => void;
  onStatusUpdate: (status: "investigating" | "mitigated" | "resolved") => void;
}) {
  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={(e) => e.stopPropagation()}>
        <div className="detail-panel-header">
          <div className="detail-panel-title">
            <h2>{incident.title}</h2>
            <div className="detail-badges">
              <span className={`severity-badge severity-${incident.severity}`}>
                {severityIcon(incident.severity)} {incident.severity}
              </span>
              <span className={`status-badge status-${incident.status}`}>
                {incident.status}
              </span>
            </div>
          </div>
          <button className="close-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="detail-panel-body">
          <div className="detail-section">
            <h4>Summary</h4>
            <p>{incident.summary}</p>
          </div>

          <div className="detail-section">
            <h4>Service</h4>
            <p className="service-tag">{incident.service_name}</p>
          </div>

          <RelatedRunbooks serviceName={incident.service_name} />
          <RootCausePanel serviceName={incident.service_name} />
          <AITriagePanel incidentId={incident.id} />

          <div className="detail-section">
            <h4>Evidence</h4>
            <ul className="evidence-list">
              {incident.evidence.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </div>

          <div className="detail-section">
            <h4>Timeline</h4>
            <div className="timeline">
              {incident.timeline.map((entry, index) => (
                <TimelineEntry key={index} entry={entry} />
              ))}
            </div>
          </div>

          <div className="detail-section">
            <h4>Status Actions</h4>
            <div className="status-actions">
              {(["investigating", "mitigated", "resolved"] as const).map((status) => (
                <button
                  key={status}
                  className={`status-action-btn ${incident.status === status ? "active" : ""}`}
                  onClick={() => onStatusUpdate(status)}
                  disabled={incident.status === status}
                >
                  Mark {status}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────── Loading Spinner ─────────── */
function LoadingSpinner() {
  return (
    <div className="loading-state">
      <div className="spinner" />
      <p>Loading incidents...</p>
    </div>
  );
}

/* ─────────── Error State ─────────── */
function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="error-state">
      <div className="error-icon">⚠️</div>
      <h3>Could not load data</h3>
      <p>{message}</p>
      <button className="retry-btn" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

/* ─────────── Empty State ─────────── */
function EmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-icon">✅</div>
      <h3>All systems operational</h3>
      <p>No incidents detected yet.</p>
      <p className="empty-hint">
        Start the traffic simulator to generate microservice traffic and trigger incidents.
      </p>
    </div>
  );
}

/* ─────────── Dashboard ─────────── */
function Dashboard() {
  const [activeTab, setActiveTab] = useState<"incidents" | "graph" | "runbooks" | "search" | "topology" | "discovery">("incidents");
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);
  const [selectedService, setSelectedService] = useState<DiscoveredService | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [semanticMode, setSemanticMode] = useState(false);
  const [discoveryEvents, setDiscoveryEvents] = useState<DiscoveryEvent[]>([]);
  const queryClient = useQueryClient();

  // WebSocket for live incident updates
  useEffect(() => {
    const ws = new WebSocket("ws://127.0.0.1:8000/ws/incidents");
    let pingInterval: ReturnType<typeof setInterval>;

    ws.onopen = () => {
      // Keep connection alive with periodic pings
      pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send("ping");
        }
      }, 30000);
    };

    ws.onmessage = (event) => {
      try {
        const msg: {
        type?: string;
        incident?: { id?: string };
      } = JSON.parse(event.data);
        if (msg.type === "incident_created" || msg.type === "incident_updated") {
          // Invalidate the incidents query to trigger a refetch
          queryClient.invalidateQueries({ queryKey: ["incidents"] });
          // Also invalidate the specific incident if it's the one being viewed
          if (msg.incident?.id) {
            queryClient.invalidateQueries({ queryKey: ["incident", msg.incident.id] });
          }
        }
      } catch {
        // Ignore non-JSON messages
      }
    };

    ws.onclose = () => {
      clearInterval(pingInterval);
    };

    ws.onerror = () => {
      // WebSocket error — polling will continue as fallback
    };

    return () => {
      clearInterval(pingInterval);
      ws.close();
    };
  }, [queryClient]);

  // Discovery WebSocket for real-time topology updates
  useEffect(() => {
    const ws = new WebSocket("ws://127.0.0.1:8000/ws/discovery");
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type && msg.service_name) {
          setDiscoveryEvents((prev) => [
            ...prev.slice(-99),
            {
              type: msg.type,
              service_name: msg.service_name,
              detail: msg.detail || "",
              severity: msg.severity || "info",
              timestamp: msg.timestamp || new Date().toISOString(),
            },
          ]);
          // Invalidate topology queries so TanStack Query refetches
          queryClient.invalidateQueries({ queryKey: ["discovered-services"] });
          queryClient.invalidateQueries({ queryKey: ["auto-graph"] });
          queryClient.invalidateQueries({ queryKey: ["services-health"] });
        }
      } catch {
        // Ignore non-JSON
      }
    };
    ws.onerror = () => {};
    return () => ws.close();
  }, [queryClient]);

  const {
    data: incidents,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["incidents"],
    queryFn: fetchIncidents,
    refetchInterval: 3000,
  });

  const { data: graphData, isLoading: graphLoading, error: graphError } = useQuery({
    queryKey: ["graph"],
    queryFn: fetchServiceGraph,
    refetchInterval: 5000,
    enabled: activeTab === "graph",
  });

  const { data: runbooks, isLoading: runbooksLoading, error: runbooksError } = useQuery({
    queryKey: ["runbooks"],
    queryFn: () => fetchRunbooks(),
    refetchInterval: 10000,
    enabled: activeTab === "runbooks",
  });

  const { data: searchData, isLoading: searchLoading, error: searchError } = useQuery({
    queryKey: ["search", searchQuery, semanticMode],
    queryFn: () => searchKnowledgeBase(searchQuery, semanticMode),
    enabled: activeTab === "search" && searchQuery.length > 0,
  });

  // Topology queries
  const { data: discoveredServices, isLoading: topoLoading, error: topoError } = useQuery({
    queryKey: ["discovered-services"],
    queryFn: fetchDiscoveredServices,
    refetchInterval: activeTab === "topology" ? 10000 : false,
    enabled: activeTab === "topology",
  });

  const { data: autoGraph } = useQuery({
    queryKey: ["auto-graph"],
    queryFn: fetchAutoGraph,
    refetchInterval: activeTab === "topology" ? 10000 : false,
    enabled: activeTab === "topology",
  });

  const { data: healthData } = useQuery({
    queryKey: ["services-health"],
    queryFn: fetchServicesHealth,
    refetchInterval: activeTab === "topology" ? 10000 : false,
    enabled: activeTab === "topology",
  });

  const { data: selectedIncident } = useQuery({
    queryKey: ["incident", selectedIncidentId],
    queryFn: () => fetchIncidentDetail(selectedIncidentId!),
    enabled: !!selectedIncidentId,
  });

  const handleStatusUpdate = async (
    status: "investigating" | "mitigated" | "resolved"
  ) => {
    if (!selectedIncidentId) return;
    await updateIncidentStatus(selectedIncidentId, status, "dashboard-operator");
    queryClient.invalidateQueries({ queryKey: ["incidents"] });
    queryClient.invalidateQueries({ queryKey: ["incident", selectedIncidentId] });
  };

  const handleRetry = () => {
    queryClient.invalidateQueries({ queryKey: ["incidents"] });
  };

  const handleRetryGraph = () => {
    queryClient.invalidateQueries({ queryKey: ["graph"] });
  };

  const handleRetryRunbooks = () => {
    queryClient.invalidateQueries({ queryKey: ["runbooks"] });
  };

  const handleRetrySearch = () => {
    queryClient.invalidateQueries({ queryKey: ["search", searchQuery, semanticMode] });
  };

  const handleCreateRunbook = async (data: {
    tenant_id: string;
    service_name: string;
    title: string;
    description: string;
    steps: string[];
  }) => {
    await createRunbook(data);
    queryClient.invalidateQueries({ queryKey: ["runbooks"] });
  };

  const handleDeleteRunbook = async (id: string) => {
    await deleteRunbook(id);
    queryClient.invalidateQueries({ queryKey: ["runbooks"] });
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      queryClient.invalidateQueries({ queryKey: ["search", searchQuery.trim()] });
    }
  };

  return (
    <main className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">SignalForge</p>
          <h1>Incident Triage Dashboard</h1>
        </div>
        <div className="stats-bar">
          <div className="stat">
            <span className="stat-value">{incidents?.length ?? 0}</span>
            <span className="stat-label">Incidents</span>
          </div>
          <div className="stat">
            <span className="stat-value">
              {incidents?.filter((i) => i.severity === "critical").length ?? 0}
            </span>
            <span className="stat-label critical">Critical</span>
          </div>
          <div className="stat">
            <span className="stat-value">
              {incidents?.filter((i) => i.severity === "warning").length ?? 0}
            </span>
            <span className="stat-label warning">Warning</span>
          </div>
        </div>
      </header>

      {/* Tab Navigation */}
      <nav className="tab-nav">
        <button
          className={`tab-btn ${activeTab === "incidents" ? "active" : ""}`}
          onClick={() => setActiveTab("incidents")}
        >
          🚨 Incidents
        </button>
        <button
          className={`tab-btn ${activeTab === "graph" ? "active" : ""}`}
          onClick={() => setActiveTab("graph")}
        >
          🕸️ Service Graph
        </button>
        <button
          className={`tab-btn ${activeTab === "runbooks" ? "active" : ""}`}
          onClick={() => setActiveTab("runbooks")}
        >
          📖 Runbooks
        </button>
        <button
          className={`tab-btn ${activeTab === "search" ? "active" : ""}`}
          onClick={() => setActiveTab("search")}
        >
          🔍 Search
        </button>
        <button
          className={`tab-btn ${activeTab === "topology" ? "active" : ""}`}
          onClick={() => setActiveTab("topology")}
        >
          🗺️ Topology
        </button>
        <button
          className={`tab-btn ${activeTab === "discovery" ? "active" : ""}`}
          onClick={() => setActiveTab("discovery")}
        >
          📡 Discovery
        </button>
      </nav>

      {/* Incidents Tab */}
      {activeTab === "incidents" && (
        <>
          {isLoading && <LoadingSpinner />}

          {error && !isLoading && <ErrorState message={error instanceof ApiError ? error.userMessage() : "Check that the backend is running at http://127.0.0.1:8000"} onRetry={handleRetry} />}

          {!isLoading && !error && incidents && incidents.length === 0 && <EmptyState />}

          {!isLoading && !error && incidents && incidents.length > 0 && (
            <section className="incident-grid">
              {incidents.map((incident) => (
                <IncidentCard
                  key={incident.id}
                  incident={incident}
                  onClick={setSelectedIncidentId}
                />
              ))}
            </section>
          )}

          {selectedIncident && (
            <IncidentDetail
              incident={selectedIncident}
              onClose={() => setSelectedIncidentId(null)}
              onStatusUpdate={handleStatusUpdate}
            />
          )}
        </>
      )}

      {/* Service Graph Tab */}
      {activeTab === "graph" && graphLoading && (
        <div className="graph-empty">
          <div className="spinner" />
          <h3>Loading service graph...</h3>
        </div>
      )}

      {activeTab === "graph" && graphError && (
        <ErrorState
          message={graphError instanceof ApiError ? graphError.userMessage() : "Failed to load service graph"}
          onRetry={handleRetryGraph}
        />
      )}

      {activeTab === "graph" && !graphLoading && !graphError && graphData && graphData.nodes.length > 0 && (
        <ServiceGraphView nodes={graphData.nodes} edges={graphData.edges} />
      )}

      {activeTab === "graph" && !graphLoading && !graphError && graphData && graphData.nodes.length === 0 && (
        <div className="graph-empty">
          <div className="empty-icon">🕸️</div>
          <h3>No service graph data yet</h3>
          <p>Start the traffic simulator to generate trace events.</p>
        </div>
      )}

      {/* Runbooks Tab */}
      {activeTab === "runbooks" && runbooksLoading && (
        <div className="loading-state" style={{ padding: "40px" }}>
          <div className="spinner" />
          <p>Loading runbooks...</p>
        </div>
      )}

      {activeTab === "runbooks" && runbooksError && (
        <ErrorState
          message={runbooksError instanceof ApiError ? runbooksError.userMessage() : "Failed to load runbooks"}
          onRetry={handleRetryRunbooks}
        />
      )}

      {activeTab === "runbooks" && !runbooksLoading && !runbooksError && (
        <RunbookPanel
          runbooks={runbooks || []}
          onCreate={handleCreateRunbook}
          onDelete={handleDeleteRunbook}
        />
      )}

      {/* Search Tab */}
      {activeTab === "search" && (
        <div className="search-panel">
          <form className="search-form" onSubmit={handleSearchSubmit}>
            <input
              type="text"
              className="search-input"
              placeholder="Search incidents and runbooks..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <button type="submit" className="search-btn">
              Search
            </button>
          </form>
          <div className="semantic-toggle">
            <label className="semantic-label">
              <input
                type="checkbox"
                checked={semanticMode}
                onChange={(e) => setSemanticMode(e.target.checked)}
              />
              <span>Semantic search</span>
            </label>
            <span className="semantic-hint">
              Finds similar results even when wording differs. Falls back to keyword search if unavailable.
            </span>
          </div>

          {searchError && (
            <ErrorState
              message={searchError instanceof ApiError ? searchError.userMessage() : "Search failed"}
              onRetry={handleRetrySearch}
            />
          )}

          {searchLoading && !searchError && (
            <div className="loading-state" style={{ padding: "40px" }}>
              <div className="spinner" />
              <p>Searching...</p>
            </div>
          )}

          {!searchLoading && !searchError && searchData && searchData.results.length === 0 && (
            <div className="empty-state" style={{ padding: "40px" }}>
              <div className="empty-icon">🔍</div>
              <h3>No results found</h3>
              <p>Try a different keyword or check your spelling.</p>
            </div>
          )}

          {!searchLoading && !searchError && searchData && searchData.results.length > 0 && (
            <section className="incident-grid">
              {searchData.results.map((result) => (
                <SearchResultCard
                  key={`${result.type}-${result.id}`}
                  result={result}
                  onIncidentClick={(id) => {
                    setSelectedIncidentId(id);
                    setActiveTab("incidents");
                  }}
                />
              ))}
            </section>
          )}

          {selectedIncident && (
            <IncidentDetail
              incident={selectedIncident}
              onClose={() => setSelectedIncidentId(null)}
              onStatusUpdate={handleStatusUpdate}
            />
          )}
        </div>
      {/* Topology Tab */}
      {activeTab === "topology" && (
        <ServiceTopologyMap
          services={discoveredServices || []}
          edges={autoGraph?.edges || []}
          healthData={healthData || []}
          onNodeClick={(svc) => setSelectedService(svc)}
          isLoading={topoLoading}
          error={topoError}
          onRetry={() => {
            queryClient.invalidateQueries({ queryKey: ["discovered-services"] });
            queryClient.invalidateQueries({ queryKey: ["auto-graph"] });
            queryClient.invalidateQueries({ queryKey: ["services-health"] });
          }}
        />
      )}

      {selectedService && (
        <ServiceDetailsPanel
          service={selectedService}
          health={healthData?.find((h) => h.service_id === selectedService.service_id)}
          onClose={() => setSelectedService(null)}
        />
      )}

      {/* Discovery Feed Tab */}
      {activeTab === "discovery" && (
        <DiscoveryEventFeed events={discoveryEvents} />
      )}

    </main>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Dashboard />
    </QueryClientProvider>
  );
}
