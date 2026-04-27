-- Enable pgvector
create extension if not exists vector;

-- Add embedding column to insights
alter table insights
    add column if not exists embedding vector(1536);

-- IVFFlat index for cosine similarity (fast approximate search)
create index if not exists insights_embedding_idx
    on insights using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- ─────────────────────────────────────────────────────────────────────────────
-- RPC: search_insights
-- Returns the top-k most semantically similar insights for a user.
-- Optional filters: date range and insight_type.
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function search_insights(
    p_user_id     uuid,
    p_embedding   vector(1536),
    p_limit       int      default 5,
    p_date_from   date     default null,
    p_date_to     date     default null,
    p_insight_type text    default null
)
returns table (
    id               uuid,
    title            text,
    content          text,
    insight_type     text,
    topics           text[],
    date_range_start date,
    date_range_end   date,
    generated_at     timestamptz,
    similarity       float
)
language sql stable
as $$
    select
        i.id,
        i.title,
        i.content,
        i.insight_type,
        i.topics,
        i.date_range_start,
        i.date_range_end,
        i.generated_at,
        1 - (i.embedding <=> p_embedding) as similarity
    from insights i
    where
        i.user_id = p_user_id
        and i.embedding is not null
        and (p_date_from  is null or i.date_range_start >= p_date_from)
        and (p_date_to    is null or i.date_range_end   <= p_date_to)
        and (p_insight_type is null or i.insight_type   = p_insight_type)
    order by i.embedding <=> p_embedding   -- cosine distance ascending
    limit p_limit;
$$;
