from __future__ import annotations
from typing import Any
from uuid import UUID
from app.database import get_db


def create_raw(
    user_id: str,
    source: str,
    source_type: str,
    content: dict,
    file_name: str | None = None,
    metadata: dict | None = None,
) -> dict:
    db = get_db()
    row = {
        "user_id": user_id,
        "source": source,
        "source_type": source_type,
        "content": content,
        "file_name": file_name,
        "metadata": metadata or {},
    }
    res = db.table("raw_data").insert(row).execute()
    return res.data[0]


def get_raw(
    user_id: str,
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
) -> list[dict]:
    db = get_db()
    q = db.table("raw_data").select("*").eq("user_id", user_id)
    if source:
        q = q.eq("source", source)
    if date_from:
        q = q.gte("ingested_at", date_from)
    if date_to:
        q = q.lte("ingested_at", date_to)
    res = q.order("ingested_at", desc=True).limit(limit).execute()
    return res.data


def delete_raw(raw_id: str) -> None:
    db = get_db()
    db.table("raw_data").delete().eq("id", raw_id).execute()
