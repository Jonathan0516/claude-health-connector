"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ProfileBasics, UserState, NewStatePayload } from "@/lib/api";
import { Plus, Pencil, Check, X, Loader2, CircleDot, CheckCircle2 } from "lucide-react";
import { format } from "date-fns";

// ── Shared UI atoms ───────────────────────────────────────────────────────────

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white border border-gray-200 rounded-xl p-5 ${className}`}>
      {children}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="text-base font-semibold text-gray-900 mb-4">{children}</h2>;
}

// ── Profile basics panel ──────────────────────────────────────────────────────

function ProfilePanel() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["profile"],
    queryFn: api.getProfile,
  });

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<ProfileBasics>({});

  function startEdit() {
    setForm(data?.basics ?? {});
    setEditing(true);
  }

  const save = useMutation({
    mutationFn: (basics: ProfileBasics) => api.updateProfile(basics),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile"] });
      setEditing(false);
    },
  });

  if (isLoading) return <Card><Loader2 className="animate-spin w-5 h-5 text-gray-400" /></Card>;

  const b = data?.basics ?? {};

  const fields: { key: keyof ProfileBasics; label: string; type?: string; placeholder?: string }[] = [
    { key: "dob",        label: "Date of Birth",  type: "date" },
    { key: "sex",        label: "Sex",             placeholder: "male / female / other" },
    { key: "height_cm",  label: "Height (cm)",     type: "number" },
    { key: "blood_type", label: "Blood Type",      placeholder: "A+ / O-" },
    { key: "notes",      label: "Notes",           placeholder: "Free-text background context" },
  ];

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <SectionTitle>Basic Info</SectionTitle>
        {!editing && (
          <button onClick={startEdit} className="flex items-center gap-1.5 text-sm text-blue-600 hover:text-blue-700">
            <Pencil className="w-3.5 h-3.5" /> Edit
          </button>
        )}
      </div>

      {editing ? (
        <div className="flex flex-col gap-3">
          {fields.map(({ key, label, type, placeholder }) => (
            <div key={key}>
              <label className="text-xs font-medium text-gray-500 mb-1 block">{label}</label>
              {key === "notes" ? (
                <textarea
                  rows={3}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={(form[key] as string) ?? ""}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                  placeholder={placeholder}
                />
              ) : (
                <input
                  type={type ?? "text"}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={(form[key] as string | number) ?? ""}
                  onChange={e => setForm(f => ({
                    ...f,
                    [key]: type === "number" ? parseFloat(e.target.value) || "" : e.target.value,
                  }))}
                  placeholder={placeholder}
                />
              )}
            </div>
          ))}

          <div className="flex gap-2 mt-1">
            <button
              onClick={() => save.mutate(form)}
              disabled={save.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              {save.isPending ? <Loader2 className="animate-spin w-3.5 h-3.5" /> : <Check className="w-3.5 h-3.5" />}
              Save
            </button>
            <button
              onClick={() => setEditing(false)}
              className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50"
            >
              <X className="w-3.5 h-3.5" /> Cancel
            </button>
          </div>
        </div>
      ) : (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
          {fields.map(({ key, label }) => (
            <div key={key} className={key === "notes" ? "col-span-2" : ""}>
              <dt className="text-xs font-medium text-gray-500">{label}</dt>
              <dd className="text-sm text-gray-900 mt-0.5">
                {b[key] != null ? String(b[key]) : <span className="text-gray-400">—</span>}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  );
}

// ── States panel ──────────────────────────────────────────────────────────────

const STATE_TYPE_COLOR: Record<string, string> = {
  goal:      "bg-blue-100 text-blue-800",
  phase:     "bg-purple-100 text-purple-800",
  condition: "bg-red-100 text-red-800",
  context:   "bg-gray-100 text-gray-700",
};

const STATE_TYPES = ["goal", "phase", "condition", "context"];

function StatesBadge({ type }: { type: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STATE_TYPE_COLOR[type] ?? "bg-gray-100 text-gray-700"}`}>
      {type}
    </span>
  );
}

function AddStateForm({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<NewStatePayload>({
    state_type: "goal",
    label: "",
    started_on: new Date().toISOString().split("T")[0],
  });

  const add = useMutation({
    mutationFn: api.addState,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["states"] });
      onClose();
    },
  });

  return (
    <div className="mt-4 border border-dashed border-gray-300 rounded-xl p-4 flex flex-col gap-3">
      <h3 className="text-sm font-medium text-gray-700">New State</h3>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">Type</label>
          <select
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={form.state_type}
            onChange={e => setForm(f => ({ ...f, state_type: e.target.value }))}
          >
            {STATE_TYPES.map(t => <option key={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">Started on</label>
          <input
            type="date"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={form.started_on}
            onChange={e => setForm(f => ({ ...f, started_on: e.target.value }))}
          />
        </div>
      </div>

      <div>
        <label className="text-xs text-gray-500 mb-1 block">Label</label>
        <input
          type="text"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="e.g. 减脂期 / 术后恢复 / 马拉松备赛"
          value={form.label}
          onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
        />
      </div>

      <div>
        <label className="text-xs text-gray-500 mb-1 block">Ends on (optional)</label>
        <input
          type="date"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={form.ends_on ?? ""}
          onChange={e => setForm(f => ({ ...f, ends_on: e.target.value || undefined }))}
        />
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => add.mutate(form)}
          disabled={!form.label || add.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {add.isPending ? <Loader2 className="animate-spin w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
          Add
        </button>
        <button onClick={onClose} className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50">
          Cancel
        </button>
      </div>
    </div>
  );
}

function StatesPanel() {
  const qc = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [showInactive, setShowInactive] = useState(false);

  const { data: states = [], isLoading } = useQuery({
    queryKey: ["states", showInactive],
    queryFn: () => api.getStates(!showInactive), // activeOnly = !showInactive
  });

  const endState = useMutation({
    mutationFn: (id: string) => api.endState(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["states"] }),
  });

  const deleteState = useMutation({
    mutationFn: (id: string) => api.deleteState(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["states"] }),
  });

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <SectionTitle>States</SectionTitle>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={e => setShowInactive(e.target.checked)}
              className="rounded"
            />
            Show history
          </label>
          <button
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-1 text-sm text-blue-600 hover:text-blue-700"
          >
            <Plus className="w-3.5 h-3.5" /> Add
          </button>
        </div>
      </div>

      {isLoading ? (
        <Loader2 className="animate-spin w-5 h-5 text-gray-400" />
      ) : states.length === 0 ? (
        <p className="text-sm text-gray-400">No states recorded.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {states.map((s: UserState) => (
            <li
              key={s.id}
              className={`flex items-start gap-3 p-3 rounded-lg border ${s.is_active ? "border-gray-200 bg-gray-50" : "border-gray-100 bg-white opacity-60"}`}
            >
              <div className="mt-0.5 shrink-0">
                {s.is_active
                  ? <CircleDot className="w-4 h-4 text-blue-500" />
                  : <CheckCircle2 className="w-4 h-4 text-green-500" />}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <StatesBadge type={s.state_type} />
                  <span className="text-sm font-medium text-gray-900">{s.label}</span>
                </div>
                <div className="text-xs text-gray-400 mt-0.5">
                  {format(new Date(s.started_on), "yyyy-MM-dd")}
                  {s.ends_on ? ` → ${format(new Date(s.ends_on), "yyyy-MM-dd")}` : " → now"}
                </div>
                {Object.keys(s.detail).length > 0 && (
                  <div className="text-xs text-gray-500 mt-1 font-mono">
                    {JSON.stringify(s.detail)}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-1 shrink-0">
                {s.is_active && (
                  <button
                    onClick={() => endState.mutate(s.id)}
                    className="text-xs px-2 py-1 rounded-md border border-gray-200 text-gray-500 hover:bg-white hover:text-gray-700 transition-colors"
                    title="Mark as ended"
                  >
                    End
                  </button>
                )}
                <button
                  onClick={() => deleteState.mutate(s.id)}
                  className="text-xs px-2 py-1 rounded-md border border-red-100 text-red-400 hover:bg-red-50 transition-colors"
                  title="Delete"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {showAdd && <AddStateForm onClose={() => setShowAdd(false)} />}
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ProfilePage() {
  return (
    <div className="p-8 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Profile</h1>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <ProfilePanel />
        <StatesPanel />
      </div>
    </div>
  );
}
