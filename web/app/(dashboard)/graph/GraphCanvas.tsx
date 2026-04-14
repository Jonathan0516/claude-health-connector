"use client";
/**
 * GraphCanvas — ReactFlow canvas, client-only component.
 * Imported dynamically with ssr:false from graph/page.tsx.
 */
import { useCallback, useEffect, useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Node,
  Edge as RFEdge,
  NodeTypes,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  MarkerType,
} from "reactflow";
import "reactflow/dist/style.css";
import { Entity, Edge } from "@/lib/api";
import { TYPE_COLOR, DEFAULT_COLOR } from "./page";

// ── Custom node ───────────────────────────────────────────────────────────────

function EntityNode({ data }: { data: { label: string; entity_type: string } }) {
  const c = TYPE_COLOR[data.entity_type] ?? DEFAULT_COLOR;
  return (
    <div
      style={{ background: c.bg, borderColor: c.border, color: c.text }}
      className="rounded-lg border-2 px-3 py-2 text-xs font-semibold shadow-sm min-w-16 text-center"
    >
      <Handle type="target" position={Position.Top} style={{ background: c.border }} />
      <div className="text-[10px] font-normal opacity-70 mb-0.5">{data.entity_type}</div>
      {data.label}
      <Handle type="source" position={Position.Bottom} style={{ background: c.border }} />
    </div>
  );
}

const NODE_TYPES: NodeTypes = { entity: EntityNode };

// ── Layout: column per entity_type, rows within each column ──────────────────

function buildNodes(entities: Entity[]): Node[] {
  const byType: Record<string, Entity[]> = {};
  for (const e of entities) {
    (byType[e.entity_type] ??= []).push(e);
  }
  const nodes: Node[] = [];
  let colIndex = 0;
  for (const items of Object.values(byType)) {
    items.forEach((e, rowIndex) => {
      nodes.push({
        id: e.id,
        type: "entity",
        position: { x: colIndex * 220, y: rowIndex * 100 },
        data: { label: e.label, entity_type: e.entity_type },
      });
    });
    colIndex++;
  }
  return nodes;
}

function buildEdges(edges: Edge[]): RFEdge[] {
  return edges.map(e => ({
    id: e.id,
    source: e.source_id,
    target: e.target_id,
    label: `${e.relationship} (${Math.round(e.confidence * 100)}%)`,
    labelStyle: { fontSize: 10, fill: "#6b7280" },
    markerEnd: { type: MarkerType.ArrowClosed, color: "#94a3b8" },
    style: { stroke: "#94a3b8", strokeWidth: 1.5 },
  }));
}

// ── Canvas component ──────────────────────────────────────────────────────────

export default function GraphCanvas({
  entities,
  edges,
  selectedEntityId,
  onNodeClick,
}: {
  entities: Entity[];
  edges: Edge[];
  selectedEntityId: string | null;
  onNodeClick: (id: string) => void;
}) {
  const initialNodes = useMemo(() => buildNodes(entities), [entities]);
  const initialEdges = useMemo(() => buildEdges(edges), [edges]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [rfEdges, , onEdgesChange] = useEdgesState(initialEdges);

  // Sync nodes when entities change
  useEffect(() => { setNodes(buildNodes(entities)); }, [entities, setNodes]);

  const handleNodeClick = useCallback((_: unknown, node: Node) => {
    onNodeClick(node.id);
  }, [onNodeClick]);

  if (entities.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 text-sm text-center px-8">
        No entities yet. Ask Claude to analyse your health data to build the knowledge graph.
      </div>
    );
  }

  return (
    <div className="flex-1">
      <ReactFlow
        nodes={nodes.map(n => ({
          ...n,
          selected: n.id === selectedEntityId,
        }))}
        edges={rfEdges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
      >
        <Background color="#e5e7eb" gap={20} />
        <Controls />
        <MiniMap
          nodeColor={n => {
            const c = TYPE_COLOR[(n.data as { entity_type: string })?.entity_type];
            return c?.border ?? "#94a3b8";
          }}
          maskColor="rgba(0,0,0,0.04)"
        />
      </ReactFlow>
    </div>
  );
}
