-- ─────────────────────────────────────────────────────────────────────────────
-- Profile Layer
-- Sits above the 4-layer health data stack.
-- Answers "who is this person and what state are they in right now"
-- so Claude can interpret all health data in the right context.
-- ─────────────────────────────────────────────────────────────────────────────

-- Static basics: one row per user, upserted as needed
create table if not exists user_profile (
    user_id    uuid primary key references users(id) on delete cascade,
    basics     jsonb not null default '{}',
    -- basics schema (all optional, all flexible):
    -- {
    --   "dob":          "1998-09-15",
    --   "sex":          "male" | "female" | "other",
    --   "height_cm":    175,
    --   "blood_type":   "A+",
    --   "ethnicity":    "...",
    --   "notes":        "free text about the person"
    -- }
    updated_at timestamptz not null default now()
);

-- Time-bounded states: multiple active states can coexist
create table if not exists user_states (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references users(id) on delete cascade,
    state_type  text not null,
    -- "goal"      — what they're actively working toward
    -- "phase"     — a defined training / life / medical phase
    -- "condition" — ongoing health condition or concern
    -- "context"   — any other relevant framing

    label       text not null,
    -- free text: "减脂期" | "马拉松备赛" | "术后恢复" | "慢性病管理" | ...

    detail      jsonb not null default '{}',
    -- completely flexible per label, e.g.:
    -- goal:      {target_weight_kg: 70, current_weight_kg: 74.4, deadline: "2026-07-01"}
    -- phase:     {event: "Shanghai Marathon", weekly_mileage_km: 60}
    -- condition: {name: "hypertension", medications: ["amlodipine 5mg"]}

    started_on  date not null,
    ends_on     date,            -- null = open-ended / still active
    is_active   boolean not null default true,

    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists user_states_user_id_idx    on user_states(user_id);
create index if not exists user_states_active_idx     on user_states(user_id, is_active);
create index if not exists user_states_type_idx       on user_states(user_id, state_type);
