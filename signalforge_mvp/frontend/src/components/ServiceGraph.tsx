import type { ServiceGraphEdge, ServiceGraphNode } from "../types";

interface ServiceGraphProps {
  nodes: ServiceGraphNode[];
  edges: ServiceGraphEdge[];
}

/**
 * A simple SVG service dependency graph.
 * Services are arranged in a circle. Edges show caller -> callee arrows.
 */
export function ServiceGraphView({ nodes, edges }: ServiceGraphProps) {
  if (nodes.length === 0) {
    return (
      <div className="graph-empty">
        <div className="empty-icon">🕸️</div>
        <h3>No service graph data yet</h3>
        <p>Start the traffic simulator to generate trace events.</p>
      </div>
    );
  }

  const width = 700;
  const height = 500;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) / 2 - 80;

  // Arrange nodes in a circle
  const nodePositions = new Map<string, { x: number; y: number }>();
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
    nodePositions.set(node.id, {
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle),
    });
  });

  // Build arrow markers
  const arrowId = `arrowhead-${Math.random().toString(36).slice(2)}`;

  return (
    <div className="service-graph">
      <h2 className="graph-title">Service Dependency Graph</h2>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="graph-svg"
        width="100%"
        height="100%"
        style={{ maxWidth: width, maxHeight: height }}
      >
        <defs>
          <marker
            id={arrowId}
            markerWidth="10"
            markerHeight="7"
            refX="10"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#64748b" />
          </marker>
        </defs>

        {/* Edges */}
        {edges.map((edge, i) => {
          const src = nodePositions.get(edge.source);
          const tgt = nodePositions.get(edge.target);
          if (!src || !tgt) return null;

          // Offset start and end so arrows don't overlap node circles
          const dx = tgt.x - src.x;
          const dy = tgt.y - src.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const offset = 40;
          const sx = src.x + (dx / dist) * offset;
          const sy = src.y + (dy / dist) * offset;
          const tx = tgt.x - (dx / dist) * offset;
          const ty = tgt.y - (dy / dist) * offset;

          // Curved path for bidirectional edges
          const mx = (sx + tx) / 2;
          const my = (sy + ty) / 2;
          // Perpendicular offset for curve
          const perpX = -(dy / dist) * 20;
          const perpY = (dx / dist) * 20;
          const cx = mx + perpX;
          const cy = my + perpY;

          const d = `M ${sx} ${sy} Q ${cx} ${cy} ${tx} ${ty}`;

          return (
            <g key={`edge-${i}`}>
              <path
                d={d}
                fill="none"
                stroke="#64748b"
                strokeWidth={Math.min(1 + edge.count * 0.3, 4)}
                opacity={0.7}
                markerEnd={`url(#${arrowId})`}
              />
              {/* Edge label showing count */}
              <text
                x={cx}
                y={cy}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize="11"
                fill="#475569"
                className="edge-label"
              >
                {edge.count > 1 ? `${edge.count}` : ""}
              </text>
            </g>
          );
        })}

        {/* Nodes */}
        {nodes.map((node) => {
          const pos = nodePositions.get(node.id)!;
          return (
            <g key={node.id} transform={`translate(${pos.x}, ${pos.y})`}>
              <circle
                r="32"
                fill="#f1f5f9"
                stroke="#3b82f6"
                strokeWidth="2"
                className="graph-node-circle"
              />
              <text
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize="12"
                fontWeight="600"
                fill="#1e293b"
                className="graph-node-label"
              >
                {node.label}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="graph-legend">
        <span className="legend-item">
          <span className="legend-dot" style={{ background: "#3b82f6" }} />
          Service
        </span>
        <span className="legend-item">
          <span className="legend-arrow">→</span>
          Calls
        </span>
      </div>
    </div>
  );
}
