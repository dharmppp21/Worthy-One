import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchDiscoveredServices, fetchIncidentsByService, fetchRunbooks, fetchAutoGraph } from "../api";
import type { DiscoveredService, ServiceHealth, Incident, Runbook, AutoDependencyEdge } from "../types";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function uptimePercent(svc: DiscoveredService, health?: ServiceHealth) {
  if (health?.uptime_percentage !== undefined) return `${health.uptime_percentage.toFixed(1)}%`;
  const first = new Date(svc.first_seen_at).getTime();
  const now = Date.now();
  const total = now - first;
  return total > 0 ? "100%" : "N/A";
}

export default function ServiceDetailsPanel({
  service,
  health,
  onClose,
}: {
  service: DiscoveredService;
  health?: ServiceHealth;
  onClose: () => void;
}) {
  const [activeTab, setActiveTabState] = useState<"overview" | "incidents" | "dependencies" | "runbooks" | "metadata">(() => {
    const saved = localStorage.getItem("signalforge:detailTab");
    if (saved && ["overview", "incidents", "dependencies", "runbooks", "metadata"].includes(saved)) {
      return saved as "overview" | "incidents" | "dependencies" | "runbooks" | "metadata";
    }
    return "overview";
  });
  const setActiveTab = (tab: typeof activeTab) => {
    localStorage.setItem("signalforge:detailTab", tab);
    setActiveTabState(tab);
  };

  const { data: incidents } = useQuery({
    queryKey: ["incidents-by-service", service.service_name],
    queryFn: () => fetchIncidentsByService(service.service_name),
    enabled: activeTab === "incidents",
  });

  const { data: runbooks } = useQuery({
    queryKey: ["runbooks", service.service_name],
    queryFn: () => fetchRunbooks(service.service_name),
    enabled: activeTab === "runbooks",
  });

  const { data: graphData, isLoading: graphLoading } = useQuery({
    queryKey: ["auto-graph"],
    queryFn: () => fetchAutoGraph(),
    enabled: activeTab === "dependencies",
  });

  const neighbors = graphData?.edges.filter(
    (e: AutoDependencyEdge) => e.source === service.service_id || e.target === service.service_id
  ) ?? [];

  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 600 }}>
        <div className="detail-panel-header">
          <div className="detail-panel-title">
            <h2>
              {service.service_name}{" "}
              <span
                style={{
                  fontSize: 12,
                  padding: "2px 8px",
                  borderRadius: 12,
                  background: service.health_status === "up" ? "#dcfce7" : service.health_status === "down" ? "#fee2e2" : "#fef3c7",
                  color: service.health_status === "up" ? "#166534" : service.health_status === "down" ? "#991b1b" : "#92400e",
                }}
              >
                {service.health_status || "unknown"}
              </span>
            </h2>
          </div>
          <button className="close-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <nav className="tab-nav" style={{ marginTop: 0, borderBottom: "1px solid #e5e7eb" }}>
          {(["overview", "incidents", "dependencies", "runbooks", "metadata"] as const).map((t) => (
            <button
              key={t}
              className={`tab-btn ${activeTab === t ? "active" : ""}`}
              onClick={() => setActiveTab(t)}
              style={{ padding: "8px 12px", fontSize: 13 }}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </nav>

        <div className="detail-panel-body" style={{ paddingTop: 16 }}>
          {activeTab === "overview" && (
            <>
              <div className="detail-section">
                <h4>Service Info</h4>
                <p><strong>Type:</strong> {service.service_type}</p>
                <p><strong>Source:</strong> {service.discovery_source}</p>
                <p><strong>Host:</strong> {service.host}</p>
                <p><strong>Endpoints:</strong> {service.endpoints.join(", ") || "N/A"}</p>
                <p><strong>First seen:</strong> {formatDate(service.first_seen_at)}</p>
                <p><strong>Last heartbeat:</strong> {formatDate(service.last_heartbeat_at)}</p>
                <p><strong>Uptime:</strong> {uptimePercent(service, health)}</p>
              </div>
              {health && (
                <div className="detail-section">
                  <h4>Health</h4>
                  <p><strong>Status:</strong> {health.status}</p>
                  <p><strong>Response time:</strong> {health.response_time_ms?.toFixed(1) ?? "?"} ms</p>
                  <p><strong>Last probe:</strong> {formatDate(health.last_probe_at)}</p>
                </div>
              )}
            </>
          )}

          {activeTab === "incidents" && (
            <div className="detail-section">
              <h4>Recent Incidents</h4>
              {!incidents || incidents.length === 0 ? (
                <p className="empty-hint">No incidents for this service.</p>
              ) : (
                <div className="incident-grid" style={{ gridTemplateColumns: "1fr" }}>
                  {incidents.slice(0, 10).map((inc: Incident) => (
                    <div key={inc.id} className={`incident-card severity-${inc.severity}`} style={{ padding: 12 }}>
                      <div className="incident-card-header">
                        <span className={`severity-badge severity-${inc.severity}`}>{inc.severity}</span>
                        <span className="incident-time">{formatDate(inc.created_at)}</span>
                      </div>
                      <h5 className="incident-title" style={{ margin: "4px 0" }}>{inc.title}</h5>
                      <span className={`status-badge status-${inc.status}`}>{inc.status}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === "dependencies" && (
            <div className="detail-section">
              <h4>Dependencies (1 hop)</h4>
              {graphLoading ? (
                <p className="empty-hint">Loading dependency graph...</p>
              ) : graphData === undefined ? (
                <div>
                  <p className="empty-hint">Dependency graph not available.</p>
                  <p style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
                    Run dependency analysis from the backend to populate this data.
                  </p>
                </div>
              ) : neighbors.length === 0 ? (
                <div>
                  <p className="empty-hint">No dependencies detected for this service.</p>
                  <p style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
                    This service has no recorded connections in the dependency graph.
                  </p>
                </div>
              ) : (
                <ul style={{ listStyle: "none", padding: 0 }}>
                  {neighbors.map((e: AutoDependencyEdge) => {
                    const isOutgoing = e.source === service.service_id;
                    const other = isOutgoing ? e.target : e.source;
                    return (
                      <li key={`${e.source}->${e.target}`} style={{ padding: "8px 0", borderBottom: "1px solid #f3f4f6" }}>
                        <strong>{isOutgoing ? "→" : "←"} {other}</strong>
                        <span style={{ fontSize: 12, color: "#6b7280", marginLeft: 8 }}>
                          {e.dependency_type} · confidence {e.confidence?.toFixed(2) ?? "?"} · {e.connection_count ?? "?"} reqs · {e.avg_latency_ms?.toFixed(0) ?? "?"}ms
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}

          {activeTab === "runbooks" && (
            <div className="detail-section">
              <h4>Runbooks</h4>
              {!runbooks || runbooks.length === 0 ? (
                <p className="empty-hint">No runbooks for this service.</p>
              ) : (
                <div className="related-runbooks">
                  {runbooks.map((rb: Runbook) => (
                    <div key={rb.id} className="related-runbook-card">
                      <div className="related-runbook-title">📖 {rb.title}</div>
                      <p className="related-runbook-desc">{rb.description}</p>
                      {rb.steps.length > 0 && (
                        <ol className="related-runbook-steps">
                          {rb.steps.map((step, i) => <li key={i}>{step}</li>)}
                        </ol>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === "metadata" && (
            <div className="detail-section">
              <h4>Discovery Metadata</h4>
              <pre style={{ background: "#f9fafb", padding: 12, borderRadius: 8, fontSize: 12, overflow: "auto" }}>
                {JSON.stringify(service.metadata, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
