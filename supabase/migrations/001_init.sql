-- Enable uuid generation
create extension if not exists "pgcrypto";

-- ─────────────────────────────────────────
-- Users
-- ─────────────────────────────────────────
create table if not exists users (
    id         uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now()
);

-- ─────────────────────────────────────────
-- Layer 1: Raw Data
-- ─────────────────────────────────────────
create table if not exists raw_data (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references users(id) on delete cascade,
    source      text not null,        -- "apple_health" | "lab_pdf" | "manual" | ...
    source_type text not null,        -- "xml" | "pdf" | "json" | "text"
    content     jsonb not null,       -- raw payload, preserved as-is
    file_name   text,
    metadata    jsonb default '{}',
    ingested_at timestamptz not null default now()
);

create index if not exists raw_data_user_id_idx on raw_data(user_id);
create index if not exists raw_data_source_idx  on raw_data(source);
create index if not exists raw_data_ingested_at_idx on raw_data(ingested_at);

-- ─────────────────────────────────────────
-- Layer 2: Evidence (normalized data points)
-- ─────────────────────────────────────────
create table if not exists evidence (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references users(id) on delete cascade,
    raw_id      uuid references raw_data(id) on delete set null,
    data_type   text not null,        -- "heart_rate" | "WBC" | "sleep_deep_minutes" | ...
    value       numeric,              -- numeric value; null if value_text is used
    value_text  text,                 -- non-numeric values
    unit        text,                 -- "bpm" | "min" | "10^3/uL" | ...
    recorded_at timestamptz not null, -- the time the measurement was taken
    tags        text[] default '{}',  -- ["sleep","wearable"] for flexible filtering
    metadata    jsonb default '{}'
);

create index if not exists evidence_user_id_idx     on evidence(user_id);
create index if not exists evidence_data_type_idx   on evidence(data_type);
create index if not exists evidence_recorded_at_idx on evidence(recorded_at);
create index if not exists evidence_tags_idx        on evidence using gin(tags);

-- ─────────────────────────────────────────
-- Layer 3: Canonical (flexible topic summaries)
-- ─────────────────────────────────────────
create table if not exists canonical (
    id             uuid primary key default gen_random_uuid(),
    user_id        uuid not null references users(id) on delete cascade,
    topic          text not null,          -- free-form: "sleep_quality" | "nutrition_daily" | ...
    period         text not null,          -- "day" | "week" | "month" | "custom"
    period_start   date not null,
    period_end     date not null,
    summary        jsonb not null,         -- LLM-generated structured summary; schema varies by topic
    evidence_ids   uuid[] default '{}',    -- referenced evidence records
    generated_at   timestamptz not null default now(),
    model_version  text,
    unique (user_id, topic, period, period_start)
);

create index if not exists canonical_user_id_idx     on canonical(user_id);
create index if not exists canonical_topic_idx       on canonical(topic);
create index if not exists canonical_period_start_idx on canonical(period_start);

-- ─────────────────────────────────────────
-- Layer 4: Insights (LLM-generated high-level analysis)
-- ─────────────────────────────────────────
create table if not exists insights (
    id               uuid primary key default gen_random_uuid(),
    user_id          uuid not null references users(id) on delete cascade,
    title            text not null,
    content          text not null,        -- Markdown insight body
    insight_type     text not null,        -- "correlation" | "trend" | "anomaly" | "summary"
    topics           text[] default '{}',  -- which canonical topics this insight spans
    date_range_start date,
    date_range_end   date,
    canonical_ids    uuid[] default '{}',
    evidence_ids     uuid[] default '{}',
    generated_at     timestamptz not null default now()
);

create index if not exists insights_user_id_idx      on insights(user_id);
create index if not exists insights_topics_idx       on insights using gin(topics);
create index if not exists insights_date_range_idx   on insights(date_range_start, date_range_end);
