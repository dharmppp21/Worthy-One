import { useEffect, useRef, useState } from "react";
import type { DiscoveryEvent, DiscoveredService } from "../types";

const EVENT_ICONS: Record<string, string> = {
  service_discovered: "🟢",
  service_removed: "⚫",
  health_changed: "🔴",
  dependency_detected: "🔵",
  dependency_removed: "⚪",
};

const SEVERITY_COLORS: Record<string, string> = {
  info: "#374151",
  warning: "#92400e",
  critical: "#991b1b",
};

const TYPE_ICONS: Record<string, string> = {
  database: "🗄️",
  cache: "⚡",
  web: "🌐",
  api: "🔧",
  message_queue: "📨",
  unknown: "❓",
};

const HEALTH_DOT: Record<string, string> = {
  up: "#22c55e",
  down: "#ef4444",
  unknown: "#eab308",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export default function DiscoveryEventFeed({
  events,
  services,
}: {
  events: DiscoveryEvent[];
  services: DiscoveredService[];
}) {
  const [activeTab, setActiveTab] = useState<"events" | "services">("services");
  const [paused, setPaused] = useState(false);
  const [eventFilter, setEventFilter] = useState<Set<string>>(new Set());
  const [serviceSearch, setServiceSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());
  const [sourceFilter, setSourceFilter] = useState<Set<string>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  const allTypes = [
    "service_discovered",
    "service_removed",
    "health_changed",
    "dependency_detected",
    "dependency_removed",
  ];

  const filteredEvents = events.filter((e) => {
    if (eventFilter.size > 0 && !eventFilter.has(e.type)) return false;
    return true;
  });

  const filteredServices = services.filter((s) => {
    if (serviceSearch && !s.service_name.toLowerCase().includes(serviceSearch.toLowerCase())) return false;
    if (typeFilter.size > 0 && !typeFilter.has(s.service_type)) return false;
    if (sourceFilter.size > 0 && !sourceFilter.has(s.discovery_source)) return false;
    return true;
  });

  useEffect(() => {
    if (!paused && bottomRef.current && activeTab === "events") {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [filteredEvents, paused, activeTab]);

  const allServiceTypes = Array.from(new Set(services.map((s) => s.service_type)));
  const allSources = Array.from(new Set(services.map((s) => s.discovery_source)));

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Tab switcher */}
      <div style={{ padding: "12px 16px 0", borderBottom: "1px solid #e5e7eb", display: "flex", gap: 8 }}>
        <button
          className={`tab-btn ${activeTab === "events" ? "active" : ""}`}
          onClick={() => setActiveTab("events")}
        >
          📡 Live Events ({events.length})
        </button>
        <button
          className={`tab-btn ${activeTab === "services" ? "active" : ""}`}
          onClick={() => setActiveTab("services")}
        >
          🗺️ Discovered Services ({services.length})
        </button>
      </div>

      {activeTab === "events" && (
        <>
          <div
            style={{
              padding: "12px 16px",
              borderBottom: "1px solid #e5e7eb",
              display: "flex",
              gap: 12,
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            <button
              className="tab-btn"
              onClick={() => setPaused(!paused)}
              style={{ fontSize: 11 }}
            >
              {paused ? "▶ Resume" : "⏸ Pause"}
            </button>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {allTypes.map((t) => (
                <label
                  key={t}
                  style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}
                >
                  <input
                    type="checkbox"
                    checked={eventFilter.has(t)}
                    onChange={(e) => {
                      const next = new Set(eventFilter);
                      e.target.checked ? next.add(t) : next.delete(t);
                      setEventFilter(next);
                    }}
                  />
                  {EVENT_ICONS[t]} {t.replace("_", " ")}
                </label>
              ))}
            </div>
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: "8px 16px" }}>
            {filteredEvents.length === 0 ? (
              <div style={{ textAlign: "center", padding: 40 }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>📡</div>
                <h3>No events yet</h3>
                <p style={{ color: "#6b7280", fontSize: 13 }}>
                  Events appear here in real-time as the discovery engine finds new services.
                  <br />
                  Keep this tab open while the backend is running to see live updates.
                </p>
              </div>
            ) : (
              filteredEvents.slice(-100).map((e, i) => (
                <div
                  key={i}
                  style={{
                    padding: "6px 0",
                    borderBottom: "1px solid #f3f4f6",
                    fontSize: 13,
                    color: SEVERITY_COLORS[e.severity] || "#374151",
                  }}
                >
                  <span
                    style={{
                      fontFamily: "monospace",
                      fontSize: 11,
                      color: "#9ca3af",
                      marginRight: 8,
                    }}
                  >
                    {new Date(e.timestamp).toLocaleTimeString()}
                  </span>
                  <span>{EVENT_ICONS[e.type] || "•"}</span>{" "}
                  <strong>{e.service_name}</strong>{" "}
                  <span>{e.detail}</span>
                </div>
              ))
            )}
            <div ref={bottomRef} />
          </div>
        </>
      )}

      {activeTab === "services" && (
        <div style={{ flex: 1, overflowY: "auto", padding: "16px" }}>
          {/* Search & Filters */}
          <div
            style={{
              display: "flex",
              gap: 12,
              flexWrap: "wrap",
              marginBottom: 16,
              alignItems: "center",
            }}
          >
            <input
              type="text"
              placeholder="Search service..."
              value={serviceSearch}
              onChange={(e) => setServiceSearch(e.target.value)}
              style={{
                padding: "6px 10px",
                borderRadius: 6,
                border: "1px solid #d1d5db",
                fontSize: 13,
                minWidth: 180,
              }}
            />

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {allServiceTypes.map((t) => (
                <label
                  key={t}
                  style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}
                >
                  <input
                    type="checkbox"
                    checked={typeFilter.has(t)}
                    onChange={(e) => {
                      const next = new Set(typeFilter);
                      e.target.checked ? next.add(t) : next.delete(t);
                      setTypeFilter(next);
                    }}
                  />
                  {TYPE_ICONS[t] || "❓"} {t}
                </label>
              ))}
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {allSources.map((s) => (
                <label
                  key={s}
                  style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}
                >
                  <input
                    type="checkbox"
                    checked={sourceFilter.has(s)}
                    onChange={(e) => {
                      const next = new Set(sourceFilter);
                      e.target.checked ? next.add(s) : next.delete(s);
                      setSourceFilter(next);
                    }}
                  />
                  {s}
                </label>
              ))}
            </div>
          </div>

          {/* Services Table */}
          {filteredServices.length === 0 ? (
            <p style={{ textAlign: "center", color: "#9ca3af", padding: 20 }}>
              No services match your filters.
            </p>
          ) : (
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 13,
              }}
            >
              <thead>
                <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
                  <th style={{ padding: "8px 12px" }}>Name</th>
                  <th style={{ padding: "8px 12px" }}>Type</th>
                  <th style={{ padding: "8px 12px" }}>Source</th>
                  <th style={{ padding: "8px 12px" }}>Host</th>
                  <th style={{ padding: "8px 12px" }}>Endpoints</th>
                  <th style={{ padding: "8px 12px" }}>Health</th>
                  <th style={{ padding: "8px 12px" }}>First Seen</th>
                </tr>
              </thead>
              <tbody>
                {filteredServices.map((s) => (
                  <tr
                    key={s.service_id}
                    style={{ borderBottom: "1px solid #f3f4f6" }}
                  >
                    <td style={{ padding: "8px 12px", fontWeight: 600 }}>
                      {s.service_name}
                    </td>
                    <td style={{ padding: "8px 12px" }}>
                      {TYPE_ICONS[s.service_type] || "❓"} {s.service_type}
                    </td>
                    <td style={{ padding: "8px 12px" }}>
                      <span
                        style={{
                          padding: "2px 8px",
                          borderRadius: 12,
                          background:
                            s.discovery_source === "process"
                              ? "#dbeafe"
                              : s.discovery_source === "docker"
                              ? "#dcfce7"
                              : "#f3f4f6",
                          fontSize: 11,
                        }}
                      >
                        {s.discovery_source}
                      </span>
                    </td>
                    <td style={{ padding: "8px 12px", color: "#6b7280" }}>
                      {s.host}
                    </td>
                    <td style={{ padding: "8px 12px", color: "#6b7280", fontSize: 12 }}>
                      {s.endpoints.slice(0, 2).join(", ")}
                      {s.endpoints.length > 2 && ` +${s.endpoints.length - 2} more`}
                    </td>
                    <td style={{ padding: "8px 12px" }}>
                      <span
                        style={{
                          display: "inline-block",
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: HEALTH_DOT[s.health_status || "unknown"],
                          marginRight: 6,
                        }}
                      />
                      {s.health_status || "unknown"}
                    </td>
                    <td style={{ padding: "8px 12px", color: "#6b7280", fontSize: 12 }}>
                      {formatDate(s.first_seen_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
