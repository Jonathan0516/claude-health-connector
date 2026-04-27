"""
User management DAL.

Handles creation and lookup of users in the `users` table.
All health data tables reference users.id as user_id.
"""

from __future__ import annotations
from app.database import get_db


def create_user(display_name: str, email: str | None = None) -> dict:
    """
    Create a new user. Returns the new user row including the generated UUID.

    Args:
        display_name: Human-readable name, e.g. "Alice", "陈家希"
        email:        Optional email (must be unique if provided)
    """
    db = get_db()
    row: dict = {"display_name": display_name}
    if email:
        row["email"] = email
    res = db.table("users").insert(row).execute()
    return res.data[0]


def get_user(user_id: str) -> dict | None:
    """Look up a user by UUID. Returns None if not found."""
    db = get_db()
    res = (
        db.table("users")
        .select("id, display_name, email, created_at")
        .eq("id", user_id)
        .execute()
    )
    return res.data[0] if res.data else None


def get_user_by_name(display_name: str) -> dict | None:
    """
    Look up a user by display_name (case-insensitive, first match).
    Useful for Claude to resolve "Alice" → UUID.
    """
    db = get_db()
    res = (
        db.table("users")
        .select("id, display_name, email, created_at")
        .ilike("display_name", display_name)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def list_users() -> list[dict]:
    """Return all registered users (id, display_name, email, created_at)."""
    db = get_db()
    res = (
        db.table("users")
        .select("id, display_name, email, created_at")
        .order("created_at", desc=False)
        .execute()
    )
    return res.data


def update_user(user_id: str, display_name: str | None = None, email: str | None = None) -> dict:
    """Update display_name or email for an existing user."""
    db = get_db()
    updates: dict = {"updated_at": "now()"}
    if display_name is not None:
        updates["display_name"] = display_name
    if email is not None:
        updates["email"] = email
    res = (
        db.table("users")
        .update(updates)
        .eq("id", user_id)
        .execute()
    )
    return res.data[0] if res.data else {}
