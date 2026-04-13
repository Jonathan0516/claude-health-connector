"""
Cascade: evidence → canonical (day / week / month auto-update).

After evidence rows are written, this module upserts lightweight canonical
summaries at three granularities for each affected (topic, period) pair.

Design constraints
──────────────────
- Day   : built from the rows just inserted — fast, no extra DB query.
- Week  : re-queries ALL evidence in that ISO week so the summary is complete.
- Month : re-queries ALL evidence in that calendar month for the same reason.
- Topic name = derived from tags (e.g. ["lab","blood"] → "lab_blood").
- Summaries are intentionally minimal indexes, NOT LLM analysis.
  They tell Claude "what data exists for this period" so it can decide
  whether to do deeper analysis via create_insight / upsert_canonical.
- auto_generated: true marks these as machine-made; Claude can overwrite
  with richer summaries using the same upsert_canonical tool.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from app.dal import canonical as canonical_dal
from app.dal import evidence as evidence_dal


def trigger(user_id: str, evidence_rows: list[dict]) -> list[dict]:
    """
    Auto-upsert day / week / month canonical entries for affected periods.

    Args:
        user_id:       Owner UUID
        evidence_rows: Rows just inserted into evidence (each must have
                       recorded_at, data_type, value, value_text, unit, tags, id)

    Returns:
        All upserted canonical rows across all three periods.
    """
    if not evidence_rows:
        return []

    affected_dates = {
        _date_of(r.get("recorded_at", ""))
        for r in evidence_rows
    } - {""}

    upserted = []
    upserted += _trigger_day(user_id, evidence_rows)
    upserted += _trigger_period(user_id, affected_dates, "week")
    upserted += _trigger_period(user_id, affected_dates, "month")
    return upserted


# ─────────────────────────────────────────────────────────────────────────────
# Day-level  (uses rows already in memory — no extra query)
# ─────────────────────────────────────────────────────────────────────────────

def _trigger_day(user_id: str, evidence_rows: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in evidence_rows:
        date_str = _date_of(row.get("recorded_at", ""))
        if not date_str:
            continue
        topic = _topic_from_tags(row.get("tags") or [])
        groups[(date_str, topic)].append(row)

    upserted = []
    for (date_str, topic), rows in groups.items():
        result = canonical_dal.upsert_canonical(
            user_id=user_id,
            topic=topic,
            period="day",
            period_start=date_str,
            period_end=date_str,
            summary=_build_summary(rows, period="day"),
            evidence_ids=[r["id"] for r in rows if r.get("id")],
        )
        upserted.append(result)
    return upserted


# ─────────────────────────────────────────────────────────────────────────────
# Week / Month  (re-queries DB for completeness)
# ─────────────────────────────────────────────────────────────────────────────

def _trigger_period(
    user_id: str,
    affected_dates: set[str],
    period: str,            # "week" | "month"
) -> list[dict]:
    """
    For each unique period window touched by affected_dates, re-query all
    evidence in that window and upsert a canonical summary per topic.
    """
    # Deduplicate: many dates may fall in the same week/month
    windows: dict[tuple[str, str], None] = {}
    for date_str in affected_dates:
        start, end = _period_window(date_str, period)
        if start:
            windows[(start, end)] = None

    upserted = []
    for (start, end) in windows:
        # Fetch ALL evidence in this window (not just the newly inserted rows)
        all_rows = evidence_dal.query_evidence(
            user_id=user_id,
            date_from=start,
            date_to=end + "T23:59:59",
            limit=2000,
        )
        if not all_rows:
            continue

        # Group by topic and upsert one canonical per (topic, window)
        by_topic: dict[str, list[dict]] = defaultdict(list)
        for row in all_rows:
            topic = _topic_from_tags(row.get("tags") or [])
            by_topic[topic].append(row)

        for topic, rows in by_topic.items():
            result = canonical_dal.upsert_canonical(
                user_id=user_id,
                topic=topic,
                period=period,
                period_start=start,
                period_end=end,
                summary=_build_summary(rows, period=period),
                evidence_ids=[r["id"] for r in rows if r.get("id")],
            )
            upserted.append(result)

    return upserted


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _date_of(recorded_at: str) -> str:
    """Extract YYYY-MM-DD from ISO datetime. Returns '' on failure."""
    try:
        return recorded_at[:10]
    except Exception:
        return ""


def _period_window(date_str: str, period: str) -> tuple[str, str]:
    """
    Return (period_start, period_end) for the given date and period.

    Week  : ISO week — Monday to Sunday
    Month : calendar month — 1st to last day
    """
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return "", ""

    if period == "week":
        start = d - timedelta(days=d.weekday())          # Monday
        end   = start + timedelta(days=6)                # Sunday
    elif period == "month":
        start = d.replace(day=1)
        # last day: first day of next month minus 1 day
        if d.month == 12:
            end = date(d.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(d.year, d.month + 1, 1) - timedelta(days=1)
    else:
        return "", ""

    return start.isoformat(), end.isoformat()


def _topic_from_tags(tags: list[str]) -> str:
    """
    Derive a canonical topic name from evidence tags.

    Priority order: lab > wearable > manual > inbody
    e.g. ["lab","blood"] → "lab_blood"
         ["wearable","sleep"] → "wearable_sleep"
         []  → "untagged"
    """
    if not tags:
        return "untagged"

    tags_set = set(tags)
    for prefix in ("lab", "wearable", "manual", "inbody"):
        if prefix in tags_set:
            rest = sorted(tags_set - {prefix})
            return f"{prefix}_{'_'.join(rest)}" if rest else prefix

    return "_".join(sorted(tags_set))


def _build_summary(rows: list[dict], period: str) -> dict:
    """
    Build a lightweight index summary for a canonical row.

    {
      "auto_generated": true,
      "period": "week",
      "data_point_count": 42,
      "data_types": ["WBC", "HGB", "weight", ...],
      "latest_values": {
        "WBC":    {"value": 6.2, "unit": "10^3/uL", "recorded_at": "2026-04-10"},
        "weight": {"value": 72.5, "unit": "kg",     "recorded_at": "2026-04-12"},
        ...
      }
    }
    """
    # Keep only the most recent value per data_type
    latest: dict[str, dict] = {}
    for row in rows:
        dt = row.get("data_type", "unknown")
        ts = row.get("recorded_at", "")
        if dt not in latest or ts > latest[dt]["recorded_at"]:
            latest[dt] = {
                "value":       row.get("value"),
                "value_text":  row.get("value_text"),
                "unit":        row.get("unit"),
                "recorded_at": ts[:10],
            }

    return {
        "auto_generated":  True,
        "period":          period,
        "data_point_count": len(rows),
        "data_types":      sorted(latest.keys()),
        "latest_values":   latest,
    }
