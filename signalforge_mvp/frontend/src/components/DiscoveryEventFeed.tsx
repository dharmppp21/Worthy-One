import { useEffect, useRef, useState } from "react";
import type { DiscoveryEvent } from "../types";

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

export default function DiscoveryEventFeed({ events }: { events: DiscoveryEvent[] }) {
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState<Set<string>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  const allTypes = ["service_discovered", "service_removed", "health_changed", "dependency_detected", "dependency_removed"];

  const filtered = events.filter((e) => {
    if (filter.size > 0 && !filter.has(e.type)) return false;
    return true;
  });

  useEffect(() => {
    if (!paused && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [filtered, paused]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ padding: "12px 16px", borderBottom: "1px solid #e5e7eb", display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>Discovery Events</span>
        <span style={{ fontSize: 12, color: "#6b7280" }}>{events.length} total</span>
        <button
          className="tab-btn"
          onClick={() => setPaused(!paused)}
          style={{ fontSize: 11, marginLeft: "auto" }}
        >
          {paused ? "▶ Resume" : "⏸ Pause"}
        </button>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {allTypes.map((t) => (
            <label key={t} style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}>
              <input
                type="checkbox"
                checked={filter.has(t)}
                onChange={(e) => {
                  const next = new Set(filter);
                  e.target.checked ? next.add(t) : next.delete(t);
                  setFilter(next);
                }}
              />
              {EVENT_ICONS[t]} {t.replace("_", " ")}
            </label>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "8px 16px" }}>
        {filtered.length === 0 ? (
          <p style={{ textAlign: "center", color: "#9ca3af", padding: 20 }}>No events yet.</p>
        ) : (
          filtered.slice(-100).map((e, i) => (
            <div
              key={i}
              style={{
                padding: "6px 0",
                borderBottom: "1px solid #f3f4f6",
                fontSize: 13,
                color: SEVERITY_COLORS[e.severity] || "#374151",
              }}
            >
              <span style={{ fontFamily: "monospace", fontSize: 11, color: "#9ca3af", marginRight: 8 }}>
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
    </div>
  );
}
