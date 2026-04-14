/**
 * Health Connector API client.
 * Reads JWT from localStorage and attaches it as Bearer token.
 * In production the base URL is the same origin; in dev it's localhost:8000.
 */

export const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "";

// ── Auth helpers ──────────────────────────────────────────────────────────────

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("hc_token");
}

export function setToken(token: string) {
  localStorage.setItem("hc_token", token);
}

export function clearToken() {
  localStorage.removeItem("hc_token");
}

// ── Core fetch wrapper ────────────────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers });

  if (res.status === 401) {
    clearToken();
    throw new Error("UNAUTHORIZED");
  }

  const json = await res.json();
  if (!json.ok) throw new Error(json.error ?? "API error");
  return json.data as T;
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface User {
  id: string;
  display_name: string;
  email: string;
  created_at: string;
}

export interface ProfileBasics {
  dob?: string;
  sex?: string;
  height_cm?: number;
  blood_type?: string;
  notes?: string;
  [key: string]: unknown;
}

export interface UserState {
  id: string;
  state_type: "goal" | "phase" | "condition" | "context";
  label: string;
  detail: Record<string, unknown>;
  started_on: string;
  ends_on: string | null;
  is_active: boolean;
}

export interface NewStatePayload {
  state_type: string;
  label: string;
  started_on: string;
  detail?: Record<string, unknown>;
  ends_on?: string;
}

export interface EvidenceRow {
  id: string;
  data_type: string;
  value: number;
  unit: string;
  recorded_at: string;
  tags: string[];
  source: string;
}

export interface CanonicalRow {
  id: string;
  topic: string;
  period: string;
  period_start: string;
  period_end: string;
  summary: Record<string, unknown>;
}

export interface InsightRow {
  id: string;
  title: string;
  content: string;
  insight_type: string;
  topics: string[];
  date_range_start: string | null;
  date_range_end: string | null;
  generated_at: string;
}

export interface Entity {
  id: string;
  entity_type: string;
  label: string;
  properties: Record<string, unknown>;
}

export interface Edge {
  id: string;
  source_id: string;
  target_id: string;
  relationship: string;
  confidence: number;
  explanation: string | null;
  observed_at: string | null;
  source: { label: string; entity_type: string };
  target: { label: string; entity_type: string };
}

export interface Overview {
  evidence: {
    total_points: number;
    data_types: Record<string, { earliest: string; latest: string; count: number }>;
  };
  canonical: {
    total_records: number;
    topics: Record<string, { periods: string[]; earliest: string; latest: string; count: number }>;
  };
  insights: {
    total: number;
    recent: InsightRow[];
  };
  graph: {
    entity_count: number;
    edge_count: number;
  };
}

// ── API methods ───────────────────────────────────────────────────────────────

export const api = {
  // Auth
  me: () => apiFetch<User>("/api/me"),

  // Profile
  getProfile: () => apiFetch<{ basics: ProfileBasics; updated_at: string }>("/api/profile"),
  updateProfile: (basics: ProfileBasics) =>
    apiFetch<{ basics: ProfileBasics }>("/api/profile", {
      method: "PUT",
      body: JSON.stringify(basics),
    }),

  // States
  getStates: (activeOnly = false) =>
    apiFetch<UserState[]>(`/api/states?active_only=${activeOnly}`),
  addState: (payload: NewStatePayload) =>
    apiFetch<UserState>("/api/states", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  endState: (id: string, ended_on?: string) =>
    apiFetch<UserState>(`/api/states/${id}/end`, {
      method: "PUT",
      body: JSON.stringify({ ended_on }),
    }),
  deleteState: (id: string) =>
    apiFetch<{ deleted: string }>(`/api/states/${id}`, { method: "DELETE" }),

  // Overview
  getOverview: () => apiFetch<Overview>("/api/overview"),

  // Insights
  getInsights: (params?: {
    topic?: string;
    insight_type?: string;
    date_from?: string;
    date_to?: string;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.topic) q.set("topic", params.topic);
    if (params?.insight_type) q.set("insight_type", params.insight_type);
    if (params?.date_from) q.set("date_from", params.date_from);
    if (params?.date_to) q.set("date_to", params.date_to);
    if (params?.limit) q.set("limit", String(params.limit));
    return apiFetch<InsightRow[]>(`/api/insights?${q}`);
  },
  deleteInsight: (id: string) =>
    apiFetch<{ deleted: string }>(`/api/insights/${id}`, { method: "DELETE" }),

  // Evidence
  getEvidence: (params?: {
    data_type?: string;
    date_from?: string;
    date_to?: string;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.data_type) q.set("data_type", params.data_type);
    if (params?.date_from) q.set("date_from", params.date_from);
    if (params?.date_to) q.set("date_to", params.date_to);
    if (params?.limit) q.set("limit", String(params.limit));
    return apiFetch<EvidenceRow[]>(`/api/evidence?${q}`);
  },
  deleteEvidence: (id: string) =>
    apiFetch<{ deleted: string }>(`/api/evidence/${id}`, { method: "DELETE" }),

  // Canonical
  getCanonical: (params?: {
    topic?: string;
    period?: string;
    date_from?: string;
    date_to?: string;
  }) => {
    const q = new URLSearchParams();
    if (params?.topic) q.set("topic", params.topic);
    if (params?.period) q.set("period", params.period);
    if (params?.date_from) q.set("date_from", params.date_from);
    if (params?.date_to) q.set("date_to", params.date_to);
    return apiFetch<CanonicalRow[]>(`/api/canonical?${q}`);
  },
  deleteCanonical: (id: string) =>
    apiFetch<{ deleted: string }>(`/api/canonical/${id}`, { method: "DELETE" }),

  // Graph
  getEntities: (entity_type?: string) => {
    const q = entity_type ? `?entity_type=${entity_type}` : "";
    return apiFetch<Entity[]>(`/api/graph/entities${q}`);
  },
  deleteEntity: (id: string) =>
    apiFetch<{ deleted: string }>(`/api/graph/entities/${id}`, { method: "DELETE" }),

  getEdges: () => apiFetch<Edge[]>("/api/graph/edges"),
  deleteEdge: (id: string) =>
    apiFetch<{ deleted: string }>(`/api/graph/edges/${id}`, { method: "DELETE" }),
};
