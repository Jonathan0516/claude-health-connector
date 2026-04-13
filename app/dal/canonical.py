from __future__ import annotations
from app.database import get_db


def upsert_canonical(
    user_id: str,
    topic: str,
    period: str,
    period_start: str,
    period_end: str,
    summary: dict,
    evidence_ids: list[str] | None = None,
    model_version: str | None = None,
) -> dict:
    db = get_db()
    row = {
        "user_id": user_id,
        "topic": topic,
        "period": period,
        "period_start": period_start,
        "period_end": period_end,
        "summary": summary,
        "evidence_ids": evidence_ids or [],
        "model_version": model_version,
    }
    # upsert on unique(user_id, topic, period, period_start)
    res = (
        db.table("canonical")
        .upsert(row, on_conflict="user_id,topic,period,period_start")
        .execute()
    )
    return res.data[0]


def query_canonical(
    user_id: str,
    topic: str | None = None,
    period: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
) -> list[dict]:
    db = get_db()
    q = db.table("canonical").select("*").eq("user_id", user_id)
    if topic:
        q = q.eq("topic", topic)
    if period:
        q = q.eq("period", period)
    if date_from:
        q = q.gte("period_start", date_from)
    if date_to:
        q = q.lte("period_end", date_to)
    res = q.order("period_start", desc=True).limit(limit).execute()
    return res.data


def list_topics(user_id: str) -> list[str]:
    db = get_db()
    res = (
        db.table("canonical")
        .select("topic")
        .eq("user_id", user_id)
        .execute()
    )
    seen = set()
    topics = []
    for row in res.data:
        t = row["topic"]
        if t not in seen:
            seen.add(t)
            topics.append(t)
    return topics
