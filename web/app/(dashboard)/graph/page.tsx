"use client";
/**
 * Graph page — React Flow canvas showing entities (nodes) and edges.
 * ReactFlow is loaded dynamically (browser-only).
 */
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, Entity, Edge } from "@/lib/api";
import { Loader2, Trash2, X } from "lucide-react";

// ReactFlow is browser-only — dynamic import with ssr:false
const GraphCanvas = dynamic(() => import("./GraphCanvas"), { ssr: false, loading: () => <CanvasLoading /> });

function CanvasLoading() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <Loader2 className="animate-spin w-5 h-5 text-gray-400" />
    </div>
  );
}

// ── Colour palette per entity_type ───────────────────────────────────────────

export const TYPE_COLOR: Record<string, { bg: string; border: string; text: string; dot: string }> = {
  biomarker:    { bg: "#dbeafe", border: "#3b82f6", text: "#1e40af", dot: "bg-blue-500" },
  symptom:      { bg: "#fed7aa", border: "#f97316", text: "#9a3412", dot: "bg-orange-500" },
  condition:    { bg: "#fecaca", border: "#ef4444", text: "#991b1b", dot: "bg-red-500" },
  intervention: { bg: "#bbf7d0", border: "#22c55e", text: "#14532d", dot: "bg-green-500" },
  lifestyle:    { bg: "#e9d5ff", border: "#a855f7", text: "#6b21a8", dot: "bg-purple-500" },
  event:        { bg: "#f3e8ff", border: "#c084fc", text: "#7c3aed", dot: "bg-violet-500" },
};

export const DEFAULT_COLOR = { bg: "#f1f5f9", border: "#94a3b8", text: "#475569", dot: "bg-gray-400" };

// ── Sidebar ───────────────────────────────────────────────────────────────────

function Sidebar({
  entities,
  selectedId,
  onSelect,
}: {
  entities: Entity[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  const filtered = useMemo(() => entities.filter(e => {
    if (typeFilter && e.entity_type !== typeFilter) return false;
    if (search && !e.label.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  }), [entities, search, typeFilter]);

  const types = useMemo(() => [...new Set(entities.map(e => e.entity_type))].sort(), [entities]);

  return (
    <div className="w-56 shrink-0 bg-white border-r border-gray-200 flex flex-col h-full overflow-hidden">
      <div className="p-3 border-b border-gray-100 flex flex-col gap-2">
        <input
          type="text" placeholder="Search entities…"
          className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={search} onChange={e => setSearch(e.target.value)}
        />
        <select
          className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
        >
          <option value="">All types</option>
          {types.map(t => <option key={t}>{t}</option>)}
        </select>
      </div>

      <div className="flex-1 overflow-y-auto">
        {filtered.map(e => {
          const c = TYPE_COLOR[e.entity_type] ?? DEFAULT_COLOR;
          return (
            <button
              key={e.id}
              onClick={() => onSelect(e.id)}
              className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-gray-50 border-b border-gray-50 transition-colors ${selectedId === e.id ? "bg-blue-50" : ""}`}
            >
              <span className={`w-2 h-2 rounded-full shrink-0 ${c.dot}`} />
              <div className="min-w-0">
                <div className="font-medium text-gray-900 truncate">{e.label}</div>
                <div className="text-gray-400">{e.entity_type}</div>
              </div>
            </button>
          );
        })}
        {filtered.length === 0 && <p className="text-xs text-gray-400 px-3 py-4">No entities.</p>}
      </div>

      <div className="p-3 border-t border-gray-100">
        <div className="text-xs text-gray-500 mb-1.5 font-medium">Legend</div>
        {Object.entries(TYPE_COLOR).map(([type, c]) => (
          <div key={type} className="flex items-center gap-1.5 text-xs text-gray-600 mb-0.5">
            <span className={`w-2 h-2 rounded-full ${c.dot}`} />
            {type}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function DetailPanel({
  entity, edges, onDeleteEntity, onDeleteEdge, onClose,
}: {
  entity: Entity;
  edges: Edge[];
  onDeleteEntity: (id: string) => void;
  onDeleteEdge: (id: string) => void;
  onClose: () => void;
}) {
  const connected = edges.filter(e => e.source_id === entity.id || e.target_id === entity.id);
  const c = TYPE_COLOR[entity.entity_type] ?? DEFAULT_COLOR;

  return (
    <div className="w-64 shrink-0 bg-white border-l border-gray-200 flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <div>
          <div className="text-xs font-medium px-1.5 py-0.5 rounded" style={{ background: c.bg, color: c.text }}>
            {entity.entity_type}
          </div>
          <div className="text-sm font-semibold text-gray-900 mt-1">{entity.label}</div>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
      </div>

      {Object.keys(entity.properties).length > 0 && (
        <div className="px-4 py-3 border-b border-gray-100">
          <div className="text-xs font-medium text-gray-500 mb-1.5">Properties</div>
          <pre className="text-xs text-gray-600 whitespace-pre-wrap">{JSON.stringify(entity.properties, null, 2)}</pre>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-4 py-3">
        <div className="text-xs font-medium text-gray-500 mb-2">Edges ({connected.length})</div>
        {connected.length === 0 ? (
          <p className="text-xs text-gray-400">No edges.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {connected.map(e => {
              const isOut = e.source_id === entity.id;
              const other = isOut ? e.target : e.source;
              return (
                <div key={e.id} className="p-2 rounded-lg bg-gray-50 text-xs flex items-start gap-2">
                  <div className="flex-1">
                    <span className="text-gray-500">{isOut ? "→" : "←"}</span>
                    <span className="font-medium text-gray-800 ml-1">{other?.label}</span>
                    <div className="text-gray-500 mt-0.5">{e.relationship} · {Math.round(e.confidence * 100)}%</div>
                    {e.explanation && <div className="text-gray-400 mt-0.5 italic">{e.explanation}</div>}
                  </div>
                  <button onClick={() => onDeleteEdge(e.id)} className="text-red-400 hover:text-red-600 shrink-0 mt-0.5">
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="p-4 border-t border-gray-100">
        <button
          onClick={() => onDeleteEntity(entity.id)}
          className="w-full flex items-center justify-center gap-1.5 text-xs text-red-500 hover:text-red-600 border border-red-200 rounded-lg py-1.5 hover:bg-red-50 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" /> Delete entity
        </button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function GraphPage() {
  const qc = useQueryClient();
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);

  const { data: entities = [], isLoading: loadingE } = useQuery({
    queryKey: ["graph-entities"],
    queryFn: () => api.getEntities(),
  });
  const { data: edges = [], isLoading: loadingG } = useQuery({
    queryKey: ["graph-edges"],
    queryFn: api.getEdges,
  });

  const deleteEntity = useMutation({
    mutationFn: api.deleteEntity,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["graph-entities"] });
      qc.invalidateQueries({ queryKey: ["graph-edges"] });
      setSelectedEntityId(null);
    },
  });

  const deleteEdge = useMutation({
    mutationFn: api.deleteEdge,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["graph-edges"] }),
  });

  const selectedEntity = useMemo(
    () => entities.find(e => e.id === selectedEntityId) ?? null,
    [entities, selectedEntityId]
  );

  const isLoading = loadingE || loadingG;

  return (
    <div className="h-screen flex flex-col">
      <div className="px-6 py-4 border-b border-gray-200 bg-white flex items-center gap-3 shrink-0">
        <h1 className="text-xl font-bold text-gray-900">Graph</h1>
        {!isLoading && (
          <span className="text-sm text-gray-400">{entities.length} entities · {edges.length} edges</span>
        )}
      </div>

      <div className="flex-1 flex overflow-hidden">
        <Sidebar entities={entities} selectedId={selectedEntityId} onSelect={setSelectedEntityId} />

        {isLoading ? (
          <CanvasLoading />
        ) : (
          <GraphCanvas
            entities={entities}
            edges={edges}
            selectedEntityId={selectedEntityId}
            onNodeClick={setSelectedEntityId}
          />
        )}

        {selectedEntity && (
          <DetailPanel
            entity={selectedEntity}
            edges={edges}
            onDeleteEntity={id => deleteEntity.mutate(id)}
            onDeleteEdge={id => deleteEdge.mutate(id)}
            onClose={() => setSelectedEntityId(null)}
          />
        )}
      </div>
    </div>
  );
}
