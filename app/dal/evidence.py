from __future__ import annotations
from app.database import get_db


def create_evidence(
    user_id: str,
    data_type: str,
    recorded_at: str,
    value: float | None = None,
    value_text: str | None = None,
    unit: str | None = None,
    raw_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict | None = None,
) -> dict:
    db = get_db()
    row = {
        "user_id": user_id,
        "data_type": data_type,
        "recorded_at": recorded_at,
        "value": value,
        "value_text": value_text,
        "unit": unit,
        "raw_id": raw_id,
        "tags": tags or [],
        "metadata": metadata or {},
    }
    res = db.table("evidence").insert(row).execute()
    return res.data[0]


def bulk_create_evidence(rows: list[dict]) -> list[dict]:
    db = get_db()
    res = db.table("evidence").insert(rows).execute()
    return res.data


def query_evidence(
    user_id: str,
    data_types: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    tags: list[str] | None = None,
    limit: int = 200,
) -> list[dict]:
    db = get_db()
    q = db.table("evidence").select("*").eq("user_id", user_id)
    if data_types:
        q = q.in_("data_type", data_types)
    if date_from:
        q = q.gte("recorded_at", date_from)
    if date_to:
        q = q.lte("recorded_at", date_to)
    # Supabase JS-style contains for array column
    if tags:
        q = q.contains("tags", tags)
    res = q.order("recorded_at", desc=True).limit(limit).execute()
    return res.data
