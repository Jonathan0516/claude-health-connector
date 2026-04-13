from __future__ import annotations
from app.database import get_db


# ─────────────────────────────────────────────────────────────────────────────
# user_profile — static basics
# ─────────────────────────────────────────────────────────────────────────────

def get_profile(user_id: str) -> dict:
    """Return the user's basic profile, or {} if not yet set."""
    db = get_db()
    res = db.table("user_profile").select("basics, updated_at").eq("user_id", user_id).execute()
    if not res.data:
        return {}
    return res.data[0]


def set_profile(user_id: str, basics: dict) -> dict:
    """
    Upsert user basics. Merges with existing data so partial updates are safe.
    e.g. set_profile(uid, {"height_cm": 175}) won't erase existing dob.
    """
    db = get_db()
    existing = get_profile(user_id)
    merged = {**(existing.get("basics") or {}), **basics}

    res = (
        db.table("user_profile")
        .upsert(
            {"user_id": user_id, "basics": merged, "updated_at": "now()"},
            on_conflict="user_id",
        )
        .execute()
    )
    return res.data[0]


# ─────────────────────────────────────────────────────────────────────────────
# user_states — time-bounded states
# ─────────────────────────────────────────────────────────────────────────────

def get_active_states(user_id: str) -> list[dict]:
    """Return all currently active states, ordered by start date."""
    db = get_db()
    res = (
        db.table("user_states")
        .select("id, state_type, label, detail, started_on, ends_on")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .order("started_on", desc=False)
        .execute()
    )
    return res.data


def add_state(
    user_id: str,
    state_type: str,
    label: str,
    started_on: str,
    detail: dict | None = None,
    ends_on: str | None = None,
) -> dict:
    """Add a new active state. Does NOT deactivate existing states."""
    db = get_db()
    res = (
        db.table("user_states")
        .insert({
            "user_id": user_id,
            "state_type": state_type,
            "label": label,
            "detail": detail or {},
            "started_on": started_on,
            "ends_on": ends_on,
            "is_active": True,
        })
        .execute()
    )
    return res.data[0]


def end_state(user_id: str, state_id: str, ended_on: str) -> dict:
    """Mark a state as inactive and record its end date."""
    db = get_db()
    res = (
        db.table("user_states")
        .update({"is_active": False, "ends_on": ended_on, "updated_at": "now()"})
        .eq("id", state_id)
        .eq("user_id", user_id)
        .execute()
    )
    return res.data[0] if res.data else {}


def get_all_states(user_id: str, include_inactive: bool = False) -> list[dict]:
    """Return state history, optionally including past states."""
    db = get_db()
    q = (
        db.table("user_states")
        .select("id, state_type, label, detail, started_on, ends_on, is_active")
        .eq("user_id", user_id)
        .order("started_on", desc=True)
    )
    if not include_inactive:
        q = q.eq("is_active", True)
    return q.execute().data


# ─────────────────────────────────────────────────────────────────────────────
# Combined context — what get_user_context MCP tool calls
# ─────────────────────────────────────────────────────────────────────────────

def build_user_context(user_id: str) -> dict:
    """
    Returns profile basics + active states + a plain-text interpretation hint
    for Claude to frame all health data analysis.
    """
    profile = get_profile(user_id)
    basics = profile.get("basics") or {}
    states = get_active_states(user_id)

    hint = _build_hint(basics, states)

    return {
        "basics": basics,
        "active_states": states,
        "interpretation_hint": hint,
    }


def _build_hint(basics: dict, states: list[dict]) -> str:
    parts: list[str] = []

    # Basic identity line
    identity_parts: list[str] = []
    if basics.get("sex"):
        identity_parts.append(basics["sex"])
    if basics.get("dob"):
        from datetime import date
        try:
            dob = date.fromisoformat(basics["dob"])
            age = (date.today() - dob).days // 365
            identity_parts.append(f"{age} years old")
        except ValueError:
            pass
    if basics.get("height_cm"):
        identity_parts.append(f"{basics['height_cm']} cm")
    if basics.get("blood_type"):
        identity_parts.append(f"blood type {basics['blood_type']}")

    if identity_parts:
        parts.append("User: " + ", ".join(identity_parts) + ".")

    if basics.get("notes"):
        parts.append(f"Background: {basics['notes']}")

    # Active states
    if states:
        state_lines = []
        for s in states:
            line = f"[{s['state_type']}] {s['label']} (since {s['started_on']}"
            if s.get("ends_on"):
                line += f", until {s['ends_on']}"
            line += ")"
            if s.get("detail"):
                detail_str = ", ".join(f"{k}={v}" for k, v in s["detail"].items())
                line += f": {detail_str}"
            state_lines.append(line)
        parts.append("Active states:\n" + "\n".join(f"  • {l}" for l in state_lines))
        parts.append(
            "Interpret all health metrics in light of these states. "
            "For example, elevated WBC may be expected post-surgery; "
            "caloric and recovery data are especially relevant during training phases."
        )
    else:
        parts.append("No active states recorded — interpret metrics using general reference ranges.")

    return "\n".join(parts)
