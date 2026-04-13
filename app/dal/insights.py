from __future__ import annotations
from openai import OpenAI
from app.database import get_db
from app.config import settings

_openai: OpenAI | None = None


def _get_openai() -> OpenAI:
    global _openai
    if _openai is None:
        _openai = OpenAI(api_key=settings.openai_api_key)
    return _openai


def _embed(text: str) -> list[float]:
    res = _get_openai().embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return res.data[0].embedding


def create_insight(
    user_id: str,
    title: str,
    content: str,
    insight_type: str,
    topics: list[str] | None = None,
    date_range_start: str | None = None,
    date_range_end: str | None = None,
    canonical_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
) -> dict:
    db = get_db()

    # Embed title + content for semantic search
    embedding = _embed(f"{title}\n{content}")

    row = {
        "user_id": user_id,
        "title": title,
        "content": content,
        "insight_type": insight_type,
        "topics": topics or [],
        "date_range_start": date_range_start,
        "date_range_end": date_range_end,
        "canonical_ids": canonical_ids or [],
        "evidence_ids": evidence_ids or [],
        "embedding": embedding,
    }
    res = db.table("insights").insert(row).execute()
    return res.data[0]


def query_insights(
    user_id: str,
    query: str | None = None,        # semantic search query (preferred)
    topics: list[str] | None = None,  # fallback: exact topic filter
    date_from: str | None = None,
    date_to: str | None = None,
    insight_type: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """
    Two modes:
    - query provided  → semantic vector search (cosine similarity)
    - query absent    → exact filter on topics / date / type
    """
    db = get_db()

    if query:
        return _semantic_search(
            db, user_id, query,
            date_from=date_from,
            date_to=date_to,
            insight_type=insight_type,
            limit=limit,
        )

    # Fallback: exact filter
    q = db.table("insights").select("id,title,content,insight_type,topics,date_range_start,date_range_end,generated_at").eq("user_id", user_id)
    if topics:
        q = q.contains("topics", topics)
    if insight_type:
        q = q.eq("insight_type", insight_type)
    if date_from:
        q = q.gte("date_range_start", date_from)
    if date_to:
        q = q.lte("date_range_end", date_to)
    res = q.order("generated_at", desc=True).limit(limit).execute()
    return res.data


def _semantic_search(
    db,
    user_id: str,
    query: str,
    date_from: str | None,
    date_to: str | None,
    insight_type: str | None,
    limit: int,
) -> list[dict]:
    embedding = _embed(query)

    # Supabase rpc call to a postgres function that does the vector search
    params: dict = {
        "p_user_id": user_id,
        "p_embedding": embedding,
        "p_limit": limit,
    }
    if date_from:
        params["p_date_from"] = date_from
    if date_to:
        params["p_date_to"] = date_to
    if insight_type:
        params["p_insight_type"] = insight_type

    res = db.rpc("search_insights", params).execute()
    return res.data
