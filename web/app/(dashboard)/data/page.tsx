"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, InsightRow, EvidenceRow, CanonicalRow } from "@/lib/api";
import { Loader2, Trash2, ChevronDown, ChevronUp } from "lucide-react";
import { format } from "date-fns";

// ── UI atoms ──────────────────────────────────────────────────────────────────

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`bg-white border border-gray-200 rounded-xl p-5 ${className}`}>{children}</div>;
}

function Tab({
  label, active, onClick,
}: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
        active ? "bg-white text-gray-900 shadow-sm border border-gray-200" : "text-gray-500 hover:text-gray-700"
      }`}
    >
      {label}
    </button>
  );
}

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      <div className="text-sm font-medium text-gray-700 mt-0.5">{label}</div>
      {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  );
}

// ── Overview tab ─────────────────────────────────────────────────────────────

function OverviewTab() {
  const { data, isLoading } = useQuery({ queryKey: ["overview"], queryFn: api.getOverview });

  if (isLoading) return <Loader2 className="animate-spin w-5 h-5 text-gray-400 mt-4" />;
  if (!data) return null;

  return (
    <div className="flex flex-col gap-6">
      {/* Summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Evidence points" value={data.evidence.total_points} />
        <StatCard label="Canonical records" value={data.canonical.total_records} />
        <StatCard label="Insights" value={data.insights.total} />
        <StatCard label="Graph nodes / edges"
          value={`${data.graph.entity_count} / ${data.graph.edge_count}`} />
      </div>

      {/* Evidence types */}
      <Card>
        <h3 className="text-sm font-semibold text-gray-700 mb-3">Evidence data types</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-gray-500 border-b border-gray-100">
              <th className="text-left pb-2 font-medium">Type</th>
              <th className="text-right pb-2 font-medium">Count</th>
              <th className="text-right pb-2 font-medium">Earliest</th>
              <th className="text-right pb-2 font-medium">Latest</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.evidence.data_types).map(([dt, v]) => (
              <tr key={dt} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="py-1.5 font-mono text-xs text-gray-800">{dt}</td>
                <td className="py-1.5 text-right text-gray-600">{v.count}</td>
                <td className="py-1.5 text-right text-gray-400">{v.earliest?.slice(0, 10)}</td>
                <td className="py-1.5 text-right text-gray-400">{v.latest?.slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {/* Recent insights */}
      <Card>
        <h3 className="text-sm font-semibold text-gray-700 mb-3">Recent insights</h3>
        {data.insights.recent.length === 0 ? (
          <p className="text-sm text-gray-400">No insights yet.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {data.insights.recent.map((ins) => (
              <li key={ins.id} className="flex items-start gap-3 p-3 rounded-lg bg-gray-50">
                <span className="text-xs px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded font-medium shrink-0">
                  {ins.insight_type}
                </span>
                <span className="text-sm text-gray-800 font-medium">{ins.title}</span>
                <span className="ml-auto text-xs text-gray-400 shrink-0">
                  {format(new Date(ins.generated_at), "yyyy-MM-dd")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// ── Insights tab ──────────────────────────────────────────────────────────────

function InsightsTab() {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [filter, setFilter] = useState({ topic: "", insight_type: "", limit: 20 });

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ["insights", filter],
    queryFn: () => api.getInsights({
      topic: filter.topic || undefined,
      insight_type: filter.insight_type || undefined,
      limit: filter.limit,
    }),
  });

  const del = useMutation({
    mutationFn: api.deleteInsight,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["insights"] }); qc.invalidateQueries({ queryKey: ["overview"] }); },
  });

  return (
    <div className="flex flex-col gap-4">
      {/* Filters */}
      <div className="flex gap-3">
        <input
          type="text" placeholder="Filter by topic"
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-48"
          value={filter.topic}
          onChange={e => setFilter(f => ({ ...f, topic: e.target.value }))}
        />
        <input
          type="text" placeholder="Insight type"
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-40"
          value={filter.insight_type}
          onChange={e => setFilter(f => ({ ...f, insight_type: e.target.value }))}
        />
      </div>

      {isLoading ? (
        <Loader2 className="animate-spin w-5 h-5 text-gray-400" />
      ) : rows.length === 0 ? (
        <p className="text-sm text-gray-400">No insights found.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {rows.map((row: InsightRow) => (
            <Card key={row.id} className="!p-0 overflow-hidden">
              <div
                className="flex items-start gap-3 p-4 cursor-pointer hover:bg-gray-50 transition-colors"
                onClick={() => setExpanded(expanded === row.id ? null : row.id)}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded font-medium">{row.insight_type}</span>
                    {row.topics.map(t => (
                      <span key={t} className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded">{t}</span>
                    ))}
                    <span className="ml-auto text-xs text-gray-400 shrink-0">
                      {format(new Date(row.generated_at), "yyyy-MM-dd")}
                    </span>
                  </div>
                  <p className="text-sm font-medium text-gray-900 mt-1">{row.title}</p>
                </div>
                <div className="flex items-center gap-1 shrink-0 ml-2">
                  {expanded === row.id ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
                </div>
              </div>
              {expanded === row.id && (
                <div className="border-t border-gray-100 px-4 py-3 bg-gray-50">
                  <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{row.content}</p>
                  <button
                    onClick={() => del.mutate(row.id)}
                    className="mt-3 flex items-center gap-1 text-xs text-red-500 hover:text-red-600"
                  >
                    <Trash2 className="w-3.5 h-3.5" /> Delete insight
                  </button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Evidence tab ──────────────────────────────────────────────────────────────

function EvidenceTab() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState({ data_type: "", date_from: "", date_to: "", limit: 100 });

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ["evidence", filter],
    queryFn: () => api.getEvidence({
      data_type: filter.data_type || undefined,
      date_from: filter.date_from || undefined,
      date_to: filter.date_to || undefined,
      limit: filter.limit,
    }),
  });

  const del = useMutation({
    mutationFn: api.deleteEvidence,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["evidence"] }); qc.invalidateQueries({ queryKey: ["overview"] }); },
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-3">
        <input
          type="text" placeholder="data_type (e.g. WBC)"
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-48"
          value={filter.data_type}
          onChange={e => setFilter(f => ({ ...f, data_type: e.target.value }))}
        />
        <input type="date" className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={filter.date_from} onChange={e => setFilter(f => ({ ...f, date_from: e.target.value }))} />
        <input type="date" className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={filter.date_to} onChange={e => setFilter(f => ({ ...f, date_to: e.target.value }))} />
      </div>

      {isLoading ? (
        <Loader2 className="animate-spin w-5 h-5 text-gray-400" />
      ) : rows.length === 0 ? (
        <p className="text-sm text-gray-400">No evidence found.</p>
      ) : (
        <Card className="!p-0 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-200 bg-gray-50">
                <th className="text-left px-4 py-2.5 font-medium">Type</th>
                <th className="text-right px-4 py-2.5 font-medium">Value</th>
                <th className="text-left px-4 py-2.5 font-medium">Unit</th>
                <th className="text-left px-4 py-2.5 font-medium">Date</th>
                <th className="text-left px-4 py-2.5 font-medium">Source</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row: EvidenceRow) => (
                <tr key={row.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-2 font-mono text-xs text-gray-800">{row.data_type}</td>
                  <td className="px-4 py-2 text-right font-medium text-gray-900">{row.value}</td>
                  <td className="px-4 py-2 text-gray-500">{row.unit}</td>
                  <td className="px-4 py-2 text-gray-500">{row.recorded_at?.slice(0, 10)}</td>
                  <td className="px-4 py-2 text-gray-400 text-xs max-w-32 truncate">{row.source}</td>
                  <td className="px-4 py-2">
                    <button onClick={() => del.mutate(row.id)} className="text-red-400 hover:text-red-600">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

// ── Canonical tab ─────────────────────────────────────────────────────────────

function CanonicalTab() {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [filter, setFilter] = useState({ topic: "", period: "" });

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ["canonical", filter],
    queryFn: () => api.getCanonical({
      topic: filter.topic || undefined,
      period: filter.period || undefined,
    }),
  });

  const del = useMutation({
    mutationFn: api.deleteCanonical,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["canonical"] }); qc.invalidateQueries({ queryKey: ["overview"] }); },
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-3">
        <input
          type="text" placeholder="Topic"
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-48"
          value={filter.topic} onChange={e => setFilter(f => ({ ...f, topic: e.target.value }))}
        />
        <select
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={filter.period} onChange={e => setFilter(f => ({ ...f, period: e.target.value }))}
        >
          <option value="">All periods</option>
          <option value="day">Day</option>
          <option value="week">Week</option>
          <option value="month">Month</option>
        </select>
      </div>

      {isLoading ? (
        <Loader2 className="animate-spin w-5 h-5 text-gray-400" />
      ) : rows.length === 0 ? (
        <p className="text-sm text-gray-400">No canonical records found.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {rows.map((row: CanonicalRow) => (
            <Card key={row.id} className="!p-0 overflow-hidden">
              <div
                className="flex items-center gap-3 p-4 cursor-pointer hover:bg-gray-50 transition-colors"
                onClick={() => setExpanded(expanded === row.id ? null : row.id)}
              >
                <span className="text-xs px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded font-medium">{row.period}</span>
                <span className="text-sm font-medium text-gray-900">{row.topic}</span>
                <span className="text-xs text-gray-400 ml-auto shrink-0">
                  {row.period_start?.slice(0, 10)} → {row.period_end?.slice(0, 10)}
                </span>
                {expanded === row.id ? <ChevronUp className="w-4 h-4 text-gray-400 shrink-0" /> : <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />}
              </div>
              {expanded === row.id && (
                <div className="border-t border-gray-100 px-4 py-3 bg-gray-50">
                  <pre className="text-xs text-gray-700 whitespace-pre-wrap overflow-auto max-h-64">
                    {JSON.stringify(row.summary, null, 2)}
                  </pre>
                  <button
                    onClick={() => del.mutate(row.id)}
                    className="mt-3 flex items-center gap-1 text-xs text-red-500 hover:text-red-600"
                  >
                    <Trash2 className="w-3.5 h-3.5" /> Delete record
                  </button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const TABS = ["Overview", "Insights", "Evidence", "Canonical"] as const;
type TabName = typeof TABS[number];

export default function DataPage() {
  const [activeTab, setActiveTab] = useState<TabName>("Overview");

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Data</h1>

      <div className="flex items-center gap-1 p-1 bg-gray-100 rounded-xl mb-6 w-fit">
        {TABS.map(t => (
          <Tab key={t} label={t} active={activeTab === t} onClick={() => setActiveTab(t)} />
        ))}
      </div>

      {activeTab === "Overview"  && <OverviewTab />}
      {activeTab === "Insights"  && <InsightsTab />}
      {activeTab === "Evidence"  && <EvidenceTab />}
      {activeTab === "Canonical" && <CanonicalTab />}
    </div>
  );
}
