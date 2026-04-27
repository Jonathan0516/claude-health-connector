-- Migration 006: Graph Layer — entities + edges
-- Implements a relational graph stored in PostgreSQL.
-- Supports multi-hop cause chain queries via recursive CTE.
-- Run in Supabase SQL Editor.

-- ─────────────────────────────────────────────────────────────────────────────
-- Entities (graph nodes)
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists entities (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references users(id) on delete cascade,

    -- What kind of thing is this?
    entity_type text not null,
    -- "biomarker"    — WBC, HGB, creatinine, HRV, weight
    -- "symptom"      — 疲劳, 头痛, 失眠, 食欲不振
    -- "condition"    — 术后炎症, 高血压, 贫血
    -- "intervention" — 阿莫西林, 低碳饮食, 有氧训练
    -- "lifestyle"    — 睡眠不足, 高压工作, 久坐
    -- "event"        — 阑尾切除术, 马拉松比赛, 献血

    label       text not null,     -- canonical display name, e.g. "WBC", "术后炎症反应"
    properties  jsonb default '{}',-- flexible: unit, normal_range, icd_code, etc.
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),

    unique (user_id, entity_type, label)
);

create index if not exists entities_user_id_idx    on entities(user_id);
create index if not exists entities_type_idx       on entities(entity_type);
create index if not exists entities_label_idx      on entities(label);

-- ─────────────────────────────────────────────────────────────────────────────
-- Edges (graph relationships)
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists edges (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references users(id) on delete cascade,

    source_id    uuid not null references entities(id) on delete cascade,
    target_id    uuid not null references entities(id) on delete cascade,

    -- Directed: source → relationship → target
    -- e.g. "术后炎症" --causes--> "WBC升高"
    --      "WBC升高"  --correlates_with--> "疲劳"
    relationship text not null,
    -- "causes"          — A directly causes B
    -- "correlates_with" — A and B co-occur / statistically linked
    -- "triggered_by"    — A was triggered by B (reverse of causes, for events)
    -- "worsens"         — A makes B worse
    -- "resolves"        — A resolves / treats B
    -- "indicates"       — A is a clinical indicator of B
    -- "precedes"        — A temporally precedes B (no causality claimed)

    confidence   float not null default 0.7
                     check (confidence >= 0 and confidence <= 1),
    explanation  text,             -- LLM-generated one-sentence rationale
    evidence_ids uuid[] default '{}', -- supporting evidence row UUIDs
    observed_at  date,             -- when was this relationship active/observed

    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),

    -- Prevent duplicate edges of the same type between the same pair
    unique (user_id, source_id, target_id, relationship)
);

create index if not exists edges_user_id_idx   on edges(user_id);
create index if not exists edges_source_idx    on edges(source_id);
create index if not exists edges_target_idx    on edges(target_id);
create index if not exists edges_relation_idx  on edges(relationship);

-- ─────────────────────────────────────────────────────────────────────────────
-- Recursive cause chain RPC (up to 5 hops)
-- Called from query_cause_chain MCP tool for efficient DB-side traversal.
--
-- direction = 'upstream'   → find what caused this entity  (follow source←target)
-- direction = 'downstream' → find what this entity causes  (follow source→target)
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function get_cause_chain(
    p_user_id    uuid,
    p_entity_id  uuid,
    p_direction  text,    -- 'upstream' | 'downstream'
    p_max_depth  int default 3
)
returns table (
    depth        int,
    source_id    uuid,
    source_label text,
    source_type  text,
    target_id    uuid,
    target_label text,
    target_type  text,
    relationship text,
    confidence   float,
    explanation  text
)
language sql stable as $$
    with recursive chain as (
        -- Seed: direct neighbours of the starting entity
        select
            1 as depth,
            e.source_id,
            es.label  as source_label,
            es.entity_type as source_type,
            e.target_id,
            et.label  as target_label,
            et.entity_type as target_type,
            e.relationship,
            e.confidence,
            e.explanation,
            -- track visited to prevent cycles
            array[case when p_direction = 'upstream' then e.source_id else e.target_id end] as visited
        from edges e
        join entities es on es.id = e.source_id
        join entities et on et.id = e.target_id
        where e.user_id = p_user_id
          and (
            (p_direction = 'upstream'   and e.target_id  = p_entity_id) or
            (p_direction = 'downstream' and e.source_id  = p_entity_id)
          )

        union all

        -- Recurse: follow the chain further
        select
            c.depth + 1,
            e.source_id,
            es.label,
            es.entity_type,
            e.target_id,
            et.label,
            et.entity_type,
            e.relationship,
            e.confidence,
            e.explanation,
            c.visited || case when p_direction = 'upstream' then e.source_id else e.target_id end
        from edges e
        join entities es on es.id = e.source_id
        join entities et on et.id = e.target_id
        join chain c on (
            (p_direction = 'upstream'   and e.target_id  = c.source_id) or
            (p_direction = 'downstream' and e.source_id  = c.target_id)
        )
        where e.user_id = p_user_id
          and c.depth < p_max_depth
          and not (case when p_direction = 'upstream' then e.source_id else e.target_id end = any(c.visited))
    )
    select depth, source_id, source_label, source_type,
           target_id, target_label, target_type,
           relationship, confidence, explanation
    from chain
    order by depth, confidence desc;
$$;
