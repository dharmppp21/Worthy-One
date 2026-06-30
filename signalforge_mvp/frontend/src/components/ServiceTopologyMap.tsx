import { useCallback, useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type Edge,
  type Node,
  Handle,
  Position,
} from "reactflow";
import "reactflow/dist/style.css";
import dagre from "@dagrejs/dagre";
import type { DiscoveredService, AutoDependencyEdge, ServiceHealth } from "../types";

/* ─── Icon mapping by service type ─── */
const TYPE_ICONS: Record<string, string> = {
  database: "🗄️",
  cache: "⚡",
  web: "🌐",
  api: "🔧",
  message_queue: "📨",
  unknown: "❓",
};

const TYPE_BG: Record<string, string> = {
  database: "#dbeafe",
  cache: "#fef3c7",
  web: "#dcfce7",
  api: "#e0e7ff",
  message_queue: "#f3e8ff",
  unknown: "#f3f4f6",
};

const HEALTH_BORDER: Record<string, string> = {
  up: "#22c55e",
  down: "#ef4444",
  unknown: "#eab308",
};

/* ─── Custom node component ─── */
function ServiceNode({ data }: { data: any }) {
  const svc: DiscoveredService = data.service;
  const health = data.health as ServiceHealth | undefined;
  const icon = TYPE_ICONS[svc.service_type] || TYPE_ICONS.unknown;
  const bg = TYPE_BG[svc.service_type] || TYPE_BG.unknown;
  const border = HEALTH_BORDER[svc.health_status || "unknown"];

  return (
    <div
      style={{
        padding: "10px 14px",
        borderRadius: "10px",
        background: bg,
        border: `2px solid ${border}`,
        minWidth: 120,
        textAlign: "center",
        fontSize: 13,
        cursor: "pointer",
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <div style={{ fontSize: 20, marginBottom: 4 }}>{icon}</div>
      <div style={{ fontWeight: 600, color: "#1f2937" }}>{svc.service_name}</div>
      <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>
        {svc.service_type} · {health ? `${health.uptime_percentage.toFixed(0)}%` : "?"}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { service: ServiceNode };

/* ─── Dagre layout helper ─── */
function getLayoutedElements(nodes: Node[], edges: Edge[], direction: "TB" | "LR" = "TB") {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: direction, nodesep: 80, ranksep: 100 });
  g.setDefaultEdgeLabel(() => ({}));

  nodes.forEach((n) => g.setNode(n.id, { width: 140, height: 70 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  const laidOutNodes = nodes.map((n) => {
    const node = g.node(n.id);
    return { ...n, position: { x: node.x - 70, y: node.y - 35 } };
  });

  return { nodes: laidOutNodes, edges };
}

/* ─── Main component ─── */
export default function ServiceTopologyMap({
  services,
  edges: rawEdges,
  healthData,
  onNodeClick,
  isLoading,
  error,
  onRetry,
}: {
  services: DiscoveredService[];
  edges: AutoDependencyEdge[];
  healthData: ServiceHealth[];
  onNodeClick: (svc: DiscoveredService) => void;
  isLoading: boolean;
  error: Error | null;
  onRetry: () => void;
}) {
  const [layoutDir, setLayoutDir] = useState<"TB" | "LR">("TB");
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());
  const [healthFilter, setHealthFilter] = useState<Set<string>>(new Set());
  const [minConfidence, setMinConfidence] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);

  /* Build health lookup */
  const healthMap = useMemo(() => {
    const map: Record<string, ServiceHealth> = {};
    healthData.forEach((h) => (map[h.service_id] = h));
    return map;
  }, [healthData]);

  /* Enrich services with health status */
  const enrichedServices = useMemo(() => {
    return services.map((s) => ({
      ...s,
      health_status: healthMap[s.service_id]?.status || "unknown",
    }));
  }, [services, healthMap]);

  /* Apply filters */
  const filteredServices = useMemo(() => {
    return enrichedServices.filter((s) => {
      if (typeFilter.size > 0 && !typeFilter.has(s.service_type)) return false;
      if (healthFilter.size > 0 && !healthFilter.has(s.health_status || "unknown")) return false;
      if (searchQuery && !s.service_name.toLowerCase().includes(searchQuery.toLowerCase())) return false;
      return true;
    });
  }, [enrichedServices, typeFilter, healthFilter, searchQuery]);

  const filteredEdgeIds = useMemo(() => new Set(filteredServices.map((s) => s.service_id)), [filteredServices]);

  const filteredEdges = useMemo(() => {
    return rawEdges.filter(
      (e) =>
        e.confidence >= minConfidence &&
        filteredEdgeIds.has(e.source) &&
        filteredEdgeIds.has(e.target)
    );
  }, [rawEdges, minConfidence, filteredEdgeIds]);

  /* Build React Flow nodes/edges */
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  useEffect(() => {
    const rfNodes: Node[] = filteredServices.map((s) => ({
      id: s.service_id,
      type: "service",
      data: { service: s, health: healthMap[s.service_id] },
      position: { x: 0, y: 0 },
    }));

    const rfEdges: Edge[] = filteredEdges.map((e) => {
      const strokeStyle = e.confidence > 0.8 ? "solid" : e.confidence > 0.5 ? "dashed" : "dotted";
      const strokeColor = e.confidence > 0.8 ? "#3b82f6" : e.confidence > 0.5 ? "#6b7280" : "#9ca3af";
      const width = Math.min(1 + e.connection_count / 20, 4);
      const animated = e.connection_count > 10;

      return {
        id: `${e.source}->${e.target}`,
        source: e.source,
        target: e.target,
        label: `${e.connection_count} reqs, ${e.avg_latency_ms.toFixed(0)}ms`,
        style: { stroke: strokeColor, strokeWidth: width, strokeDasharray: strokeStyle === "dashed" ? "5,5" : strokeStyle === "dotted" ? "2,2" : undefined },
        animated,
        labelStyle: { fontSize: 10, fill: "#4b5563" },
      };
    });

    const { nodes: laidOut } = getLayoutedElements(rfNodes, rfEdges, layoutDir);
    setNodes(laidOut);
    setEdges(rfEdges);
  }, [filteredServices, filteredEdges, layoutDir, healthMap, setNodes, setEdges]);

  const onConnect = useCallback((params: Connection) => setEdges((eds) => addEdge(params, eds)), [setEdges]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const svc = enrichedServices.find((s) => s.service_id === node.id);
      if (svc) onNodeClick(svc);
    },
    [enrichedServices, onNodeClick]
  );

  if (isLoading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "60vh" }}>
        <div className="spinner" />
        <p style={{ marginLeft: 12 }}>Loading topology...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ textAlign: "center", padding: 40 }}>
        <div style={{ fontSize: 32 }}>⚠️</div>
        <h3>Could not load topology</h3>
        <p>{error.message}</p>
        <button className="retry-btn" onClick={onRetry}>Retry</button>
      </div>
    );
  }

  const allTypes = Array.from(new Set(services.map((s) => s.service_type)));
  const allHealth = ["up", "down", "unknown"];

  return (
    <div style={{ display: "flex", height: "70vh" }}>
      {/* Control panel */}
      <div style={{ width: 240, padding: 16, borderRight: "1px solid #e5e7eb", overflowY: "auto" }}>
        <h4 style={{ margin: "0 0 12px" }}>Filters</h4>

        <div style={{ marginBottom: 12 }}>
          <input
            type="text"
            placeholder="Search service..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{ width: "100%", padding: 6, borderRadius: 6, border: "1px solid #d1d5db" }}
          />
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "#374151" }}>Service Type</label>
          {allTypes.map((t) => (
            <label key={t} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, marginTop: 4 }}>
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

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "#374151" }}>Health</label>
          {allHealth.map((h) => (
            <label key={h} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, marginTop: 4 }}>
              <input
                type="checkbox"
                checked={healthFilter.has(h)}
                onChange={(e) => {
                  const next = new Set(healthFilter);
                  e.target.checked ? next.add(h) : next.delete(h);
                  setHealthFilter(next);
                }}
              />
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: HEALTH_BORDER[h], display: "inline-block" }} />
              {h}
            </label>
          ))}
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "#374151" }}>
            Min Confidence: {minConfidence.toFixed(1)}
          </label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.1}
            value={minConfidence}
            onChange={(e) => setMinConfidence(parseFloat(e.target.value))}
            style={{ width: "100%" }}
          />
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "#374151" }}>Layout</label>
          <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
            <button
              className={`tab-btn ${layoutDir === "TB" ? "active" : ""}`}
              onClick={() => setLayoutDir("TB")}
              style={{ flex: 1, fontSize: 11 }}
            >
              Vertical
            </button>
            <button
              className={`tab-btn ${layoutDir === "LR" ? "active" : ""}`}
              onClick={() => setLayoutDir("LR")}
              style={{ flex: 1, fontSize: 11 }}
            >
              Horizontal
            </button>
          </div>
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
          <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
          Auto-refresh (10s)
        </label>
      </div>

      {/* React Flow canvas */}
      <div style={{ flex: 1 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView
          attributionPosition="bottom-left"
        >
          <Background gap={16} />
          <Controls />
          <MiniMap nodeStrokeWidth={3} zoomable pannable />
        </ReactFlow>
      </div>
    </div>
  );
}
