"""
Health Connector — MCP Server

Claude Desktop connects here via MCP protocol.
Claude handles all orchestration, memory, and synthesis.
This server is purely a data layer: read + write health data.

Architecture:
  Claude Desktop ←→ MCP Server (this file) ←→ Supabase (Profile + 4-layer DB)

Tools exposed:
  USERS   — list_users, create_user, switch_user
  PROFILE — get_user_context, set_user_profile, set_user_state, end_user_state
  READ    — get_data_overview, query_insights, query_canonical, query_evidence, query_raw
  WRITE   — ingest_evidence, create_insight, upsert_canonical, store_document, ingest_lab_json
"""

import json
import contextvars
from datetime import date
from mcp.server.fastmcp import FastMCP
from app.config import settings
from app.dal import evidence as evidence_dal
from app.dal import canonical as canonical_dal
from app.dal import insights as insights_dal
from app.dal import raw as raw_dal
from app.dal import profile as profile_dal
from app.database import get_db
from app.ingestion import pipeline as ingest_pipeline
from app.dal import users as users_dal

mcp = FastMCP(
    name="Health Connector",
    instructions="""
You have access to a structured personal health database.

## Step 1 — Identify the active user (every conversation)
If the person mentions they are someone other than the default user, call `list_users` to find them,
then `switch_user` to set them as active BEFORE any other tool call.
If you need to register a new person, call `create_user` first, then `switch_user`.
Once the correct user is active, call `get_user_context` to get their profile and states.
Use this as the interpretive frame for ALL subsequent data analysis.
If the user mentions something new about themselves, call `set_user_profile` or `set_user_state` to persist it.

## Step 2 — Call `get_data_overview`
See what data types, topics, and date ranges actually exist.
Use exact names from this overview — never invent data_type or topic names.

## Step 3 — Ingest BEFORE analyzing (any health file or data the user shares)
Whenever the user shares ANY file or data that contains health information,
store it FIRST, then analyze. Never analyze without persisting.

Choose the right ingestion tool based on file type:

| What the user shares | Tool to call |
|----------------------|--------------|
| PDF (lab report, discharge summary, scan report) | Read the PDF natively → extract all metrics → `store_document` |
| Image / photo (blood test slip, InBody printout, prescription, wearable screenshot) | Read the image natively → extract all metrics → `store_document` |
| Structured JSON (lab system export, health app export) | Pass the JSON object directly → `ingest_lab_json` |
| Plain text / manual entry (user types their metrics) | `ingest_evidence` for each metric |

For PDF and image files, you have native multimodal capability — read the file yourself,
extract every health metric you can find (values, units, reference ranges, flags),
then call `store_document` with the full list. Be thorough: capture all numeric values,
abnormal flags, dates, and the document source.

For structured JSON exports, do NOT read them as text — pass the dict directly to
`ingest_lab_json`. The parser handles field mapping automatically.

## Step 4 — Query layers top-down, stop when you have enough
1. **Insights**  — Past high-level analysis: trends, correlations, anomalies.
2. **Canonical** — Per-topic aggregated summaries (day / week / month). Topics are flexible strings.
3. **Evidence**  — Individual normalized data points with exact timestamps and values.
4. **Raw**       — Original source files. Last resort only.

## Step 5 — Save analysis results
After meaningful analysis call `create_insight` to persist findings.
If you derive a useful topic summary call `upsert_canonical`.
""".strip(),
)

# ── User context ──────────────────────────────────────────────────────────────
# stdio mode  : _active_user_id is a simple mutable string; switch_user() sets it.
# HTTP mode   : _request_user_id is a ContextVar populated per-request from
#               the ?user_id= query param, giving each connection its own user.
#               switch_user() is intentionally disabled in HTTP mode.

_active_user_id: str = settings.default_user_id          # stdio / switch_user fallback
_request_user_id: contextvars.ContextVar[str | None] = (  # HTTP per-request override
    contextvars.ContextVar("_request_user_id", default=None)
)


def _uid() -> str:
    """Return the active user UUID for the current request/session."""
    return _request_user_id.get() or _active_user_id


# ─────────────────────────────────────────────────────────────────────────────
# PROFILE tools  (call these before any health data queries)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_user_context() -> dict:
    """
    Returns who this person is and what they're currently doing.
    Call this at the start of every conversation — it provides the interpretive
    frame for all health data (e.g. WBC=6.2 means different things pre- vs post-surgery).

    Returns:
        basics:               Static info — age, sex, height, blood type, notes, etc.
        active_states:        All currently active goals, phases, conditions, and contexts.
        interpretation_hint:  Plain-text framing for Claude to use when reading health data.
    """
    return profile_dal.build_user_context(_uid())


@mcp.tool()
def set_user_profile(
    dob: str | None = None,
    sex: str | None = None,
    height_cm: float | None = None,
    blood_type: str | None = None,
    notes: str | None = None,
    extra: dict | None = None,
) -> dict:
    """
    Set or update the user's basic profile information.
    All fields are optional — only provided fields are updated (partial update safe).

    Args:
        dob:        Date of birth "YYYY-MM-DD"
        sex:        "male" | "female" | "other"
        height_cm:  Height in centimetres
        blood_type: e.g. "A+", "O-"
        notes:      Free-text background context about the person
        extra:      Any additional key-value pairs to store
    """
    basics: dict = {}
    if dob is not None:
        basics["dob"] = dob
    if sex is not None:
        basics["sex"] = sex
    if height_cm is not None:
        basics["height_cm"] = height_cm
    if blood_type is not None:
        basics["blood_type"] = blood_type
    if notes is not None:
        basics["notes"] = notes
    if extra:
        basics.update(extra)

    if not basics:
        return {"error": "No fields provided — pass at least one argument."}

    return profile_dal.set_profile(_uid(), basics)


@mcp.tool()
def set_user_state(
    state_type: str,
    label: str,
    started_on: str,
    detail: dict | None = None,
    ends_on: str | None = None,
) -> dict:
    """
    Record a new active state for the user.
    Multiple states can be active simultaneously (e.g. fat-loss + marathon training).
    States are NOT automatically replaced — call end_user_state to close an old one.

    Args:
        state_type:  "goal" | "phase" | "condition" | "context"
        label:       Free text, e.g. "减脂期", "马拉松备赛", "术后恢复", "高血压管理"
        started_on:  ISO date "YYYY-MM-DD"
        detail:      Flexible JSON with state-specific info, e.g.:
                       goal      → {target_weight_kg: 70, deadline: "2026-07-01"}
                       phase     → {event: "Shanghai Marathon", weekly_mileage_km: 60}
                       condition → {name: "hypertension", medications: ["amlodipine 5mg"]}
        ends_on:     ISO date if already known, otherwise omit (open-ended)
    """
    return profile_dal.add_state(
        user_id=_uid(),
        state_type=state_type,
        label=label,
        started_on=started_on,
        detail=detail,
        ends_on=ends_on,
    )


@mcp.tool()
def end_user_state(state_id: str, ended_on: str) -> dict:
    """
    Mark an existing state as completed / no longer active.
    Use when a goal is achieved, a phase ends, or a condition resolves.

    Args:
        state_id:  UUID of the state row (from get_user_context active_states[].id)
        ended_on:  ISO date "YYYY-MM-DD"
    """
    return profile_dal.end_state(_uid(), state_id, ended_on)


# ─────────────────────────────────────────────────────────────────────────────
# USER MANAGEMENT tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_users() -> list[dict]:
    """
    List all registered users in this Health Connector instance.

    Returns each user's id, display_name, email, and created_at.
    Use this to find a user_id before calling switch_user().
    """
    return users_dal.list_users()


@mcp.tool()
def create_user(display_name: str, email: str | None = None) -> dict:
    """
    Register a new user in the Health Connector.

    Creates a new row in the users table and returns the generated UUID.
    After creating, call switch_user() to set them as active.

    Args:
        display_name: Human-readable name, e.g. "Alice", "陈家希"
        email:        Optional, must be unique if provided
    """
    return users_dal.create_user(display_name=display_name, email=email)


@mcp.tool()
def switch_user(user_id: str | None = None, display_name: str | None = None) -> dict:
    """
    Switch the active user for this session.

    All subsequent tool calls (queries, writes, profile) will operate on
    the switched-to user's data until switch_user() is called again or
    the MCP server restarts (which resets to DEFAULT_USER_ID).

    Provide either user_id (UUID) or display_name (resolved by lookup).
    If both are provided, user_id takes precedence.

    Args:
        user_id:      UUID of the target user
        display_name: Display name to look up (case-insensitive, first match)

    Returns:
        {"active_user_id": "...", "display_name": "..."}
    """
    global _active_user_id

    if user_id:
        user = users_dal.get_user(user_id)
        if not user:
            return {"error": f"User not found: {user_id}"}
    elif display_name:
        user = users_dal.get_user_by_name(display_name)
        if not user:
            return {"error": f"No user found with display_name '{display_name}'"}
    else:
        return {"error": "Provide either user_id or display_name"}

    _active_user_id = user["id"]
    return {
        "active_user_id": _active_user_id,
        "display_name":   user.get("display_name"),
        "message": f"Now operating as '{user.get('display_name')}'. All tool calls will use this user's data.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# READ tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_data_overview() -> dict:
    """
    Returns a complete inventory of all health data stored for this user:
    - evidence_types: which data types exist, their date ranges, and tags
    - canonical_topics: which topics have aggregated summaries and for what periods
    - recent_insights: titles of the most recently generated insights

    Call this first before any other query so you know what data actually exists.
    """
    db = get_db()

    # Evidence: group by data_type
    ev_rows = (
        db.table("evidence")
        .select("data_type, recorded_at, tags")
        .eq("user_id", _uid())
        .order("recorded_at", desc=False)
        .execute()
        .data
    )
    ev_summary: dict[str, dict] = {}
    for row in ev_rows:
        dt = row["data_type"]
        ts = row["recorded_at"]
        tags = set(row.get("tags") or [])
        if dt not in ev_summary:
            ev_summary[dt] = {"earliest": ts, "latest": ts, "tags": tags}
        else:
            ev_summary[dt]["latest"] = ts
            ev_summary[dt]["tags"].update(tags)

    # Canonical: group by topic
    can_rows = (
        db.table("canonical")
        .select("topic, period, period_start, period_end")
        .eq("user_id", _uid())
        .order("period_start", desc=False)
        .execute()
        .data
    )
    can_summary: dict[str, dict] = {}
    for row in can_rows:
        t = row["topic"]
        if t not in can_summary:
            can_summary[t] = {"periods": set(), "earliest": row["period_start"], "latest": row["period_end"]}
        can_summary[t]["periods"].add(row["period"])
        can_summary[t]["latest"] = row["period_end"]

    # Recent insights
    ins_rows = (
        db.table("insights")
        .select("title, insight_type, topics, date_range_start, date_range_end, generated_at")
        .eq("user_id", _uid())
        .order("generated_at", desc=True)
        .limit(5)
        .execute()
        .data
    )

    return {
        "evidence_types": [
            {
                "data_type": dt,
                "earliest": v["earliest"][:10],
                "latest": v["latest"][:10],
                "tags": sorted(v["tags"]),
            }
            for dt, v in ev_summary.items()
        ],
        "canonical_topics": [
            {
                "topic": t,
                "available_periods": sorted(v["periods"]),
                "earliest": v["earliest"],
                "latest": v["latest"],
            }
            for t, v in can_summary.items()
        ],
        "recent_insights": ins_rows,
    }


@mcp.tool()
def query_insights(
    query: str | None = None,
    topics: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    insight_type: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """
    Query stored health insights.

    Prefer passing `query` (natural language) for semantic search — finds relevant
    insights even when topic names don't match exactly.
    Fall back to `topics` filter for strict topic matching.

    Args:
        query:        Natural language description, e.g. "sleep quality trend last week"
        topics:       Exact topic name filter, e.g. ["sleep_quality"]
        date_from:    ISO date "YYYY-MM-DD"
        date_to:      ISO date "YYYY-MM-DD"
        insight_type: "correlation" | "trend" | "anomaly" | "summary"
        limit:        Max results (default 5)
    """
    return insights_dal.query_insights(
        user_id=_uid(),
        query=query,
        topics=topics,
        date_from=date_from,
        date_to=date_to,
        insight_type=insight_type,
        limit=limit,
    )


@mcp.tool()
def query_canonical(
    topic: str | None = None,
    period: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """
    Query aggregated topic summaries (Canonical layer).
    Use topic names exactly as shown in get_data_overview.
    Omit date filters to get all available summaries for a topic.

    Args:
        topic:     e.g. "sleep_quality", "nutrition_daily", "blood_markers"
        period:    "day" | "week" | "month"
        date_from: ISO date "YYYY-MM-DD"
        date_to:   ISO date "YYYY-MM-DD"
    """
    return canonical_dal.query_canonical(
        user_id=_uid(),
        topic=topic,
        period=period,
        date_from=date_from,
        date_to=date_to,
    )


@mcp.tool()
def query_evidence(
    data_types: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    tags: list[str] | None = None,
    limit: int = 100,
) -> list[dict]:
    """
    Query individual normalized data points (Evidence layer).
    Use data_type names exactly as shown in get_data_overview.
    Omit date filters to get the most recent records.

    Args:
        data_types: e.g. ["WBC", "sleep_deep_minutes", "heart_rate"]
        date_from:  ISO datetime "YYYY-MM-DDTHH:MM:SS"
        date_to:    ISO datetime "YYYY-MM-DDTHH:MM:SS"
        tags:       e.g. ["sleep"] | ["lab"] | ["wearable"]
        limit:      Max results (default 100)
    """
    return evidence_dal.query_evidence(
        user_id=_uid(),
        data_types=data_types,
        date_from=date_from,
        date_to=date_to,
        tags=tags,
        limit=limit,
    )


@mcp.tool()
def query_raw(
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """
    Query original ingested data (Raw layer). Last resort only.
    Use when you need to verify the original source of a data point.

    Args:
        source:    "apple_health" | "lab_pdf" | "manual"
        date_from: ISO date
        date_to:   ISO date
    """
    return raw_dal.get_raw(
        user_id=_uid(),
        source=source,
        date_from=date_from,
        date_to=date_to,
    )


# ─────────────────────────────────────────────────────────────────────────────
# WRITE tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def ingest_evidence(
    data_type: str,
    recorded_at: str,
    value: float | None = None,
    value_text: str | None = None,
    unit: str | None = None,
    tags: list[str] | None = None,
    source_note: str | None = None,
) -> dict:
    """
    Add a new health data point to the Evidence layer.
    Call this when the user reports a measurement, lab result, or any health metric.

    Args:
        data_type:   What was measured, e.g. "WBC", "weight", "sleep_deep_minutes"
        recorded_at: When it was measured, ISO datetime "YYYY-MM-DDTHH:MM:SS"
        value:       Numeric value (use this for most measurements)
        value_text:  Text value (use for non-numeric data like "good", "poor")
        unit:        Unit of measurement, e.g. "kg", "bpm", "10^3/uL", "min"
        tags:        Category tags, e.g. ["lab"], ["sleep"], ["wearable"], ["manual"]
        source_note: Optional note about the data source
    """
    return evidence_dal.create_evidence(
        user_id=_uid(),
        data_type=data_type,
        recorded_at=recorded_at,
        value=value,
        value_text=value_text,
        unit=unit,
        tags=tags or ["manual"],
        metadata={"source_note": source_note} if source_note else {},
    )


@mcp.tool()
def create_insight(
    title: str,
    content: str,
    insight_type: str,
    topics: list[str] | None = None,
    date_range_start: str | None = None,
    date_range_end: str | None = None,
    evidence_ids: list[str] | None = None,
    canonical_ids: list[str] | None = None,
) -> dict:
    """
    Persist a health insight to the database for future retrieval.
    Call after generating a meaningful analysis, trend observation, or correlation finding.
    Saved insights will be surfaced in future conversations via semantic search.

    Args:
        title:             Short descriptive title
        content:           Full analysis in Markdown format
        insight_type:      "trend" | "correlation" | "anomaly" | "summary"
        topics:            Related topics, e.g. ["sleep_quality", "blood_markers"]
        date_range_start:  ISO date the insight covers from
        date_range_end:    ISO date the insight covers to
        evidence_ids:      UUIDs of supporting evidence rows
        canonical_ids:     UUIDs of supporting canonical rows
    """
    return insights_dal.create_insight(
        user_id=_uid(),
        title=title,
        content=content,
        insight_type=insight_type,
        topics=topics,
        date_range_start=date_range_start,
        date_range_end=date_range_end,
        evidence_ids=evidence_ids,
        canonical_ids=canonical_ids,
    )


@mcp.tool()
def upsert_canonical(
    topic: str,
    period: str,
    period_start: str,
    period_end: str,
    summary: dict,
    evidence_ids: list[str] | None = None,
) -> dict:
    """
    Create or update a canonical topic summary for a time period.
    Call when you derive a useful aggregated summary worth storing for future retrieval.
    The summary schema is flexible — structure it however makes sense for the topic.

    Args:
        topic:        Free-form topic name, e.g. "sleep_quality", "nutrition_daily"
        period:       "day" | "week" | "month"
        period_start: ISO date "YYYY-MM-DD"
        period_end:   ISO date "YYYY-MM-DD"
        summary:      Flexible JSON object with topic-specific fields
        evidence_ids: UUIDs of evidence rows this summary is based on
    """
    return canonical_dal.upsert_canonical(
        user_id=_uid(),
        topic=topic,
        period=period,
        period_start=period_start,
        period_end=period_end,
        summary=summary,
        evidence_ids=evidence_ids,
    )


@mcp.tool()
def store_document(
    document_date: str,
    source: str,
    document_type: str,
    summary: str,
    tags: list[str],
    values: list[dict],
    file_name: str | None = None,
) -> dict:
    """
    Store a health document that Claude has already read and parsed.

    Claude uses its native multimodal capability to read the PDF or image,
    extracts all health metrics, then calls this tool to persist everything.

    Flow:
      1. raw_data — stores the full parsed JSON as a document record
      2. evidence — bulk inserts one row per extracted metric
      3. canonical — auto-updates day-level summaries for affected dates

    Args:
        document_date:  ISO date "YYYY-MM-DD" from the document itself
        source:         "lab_pdf" | "inbody" | "apple_health" | "manual"
        document_type:  e.g. "blood_test", "body_composition", "sleep_report"
        summary:        One or two sentence summary of findings
        tags:           Category tags e.g. ["lab", "blood"] or ["body", "inbody"]
        values:         List of extracted metrics. Each item:
                        {
                          "data_type":   "WBC",
                          "value":       6.2,          # numeric (or omit)
                          "value_text":  null,          # text if non-numeric
                          "unit":        "10^3/uL",
                          "recorded_at": "2026-04-05T00:00:00",
                          "ref_range":   "4.0-10.0",   # optional
                          "flag":        "H"            # optional, H/L
                        }
        file_name:      Original filename for reference, e.g. "blood_test.pdf"
    """
    return ingest_pipeline.ingest_document(
        user_id=_uid(),
        document_date=document_date,
        source=source,
        document_type=document_type,
        summary=summary,
        tags=tags,
        values=values,
        file_name=file_name,
    )


@mcp.tool()
def ingest_lab_json(
    lab_json: dict,
    extra_tags: list[str] | None = None,
) -> dict:
    """
    Ingest a structured lab result JSON directly (no multimodal reading needed).

    Use this when the user provides a machine-readable JSON export from a lab
    system, hospital portal, or health app. Claude does NOT need to read the
    file — pass the parsed JSON object directly.

    Expected lab_json schema:
        {
          "lab_name": "瑞金医院",          # optional
          "date":     "2026-04-01",        # required — ISO date of the test
          "results": [
            {
              "name":      "WBC",          # becomes data_type
              "value":     6.2,            # numeric value
              "unit":      "10^3/uL",      # optional
              "ref_range": "4.0-10.0",     # optional
              "flag":      "H"             # optional — "H" | "L" | null
            },
            ...
          ]
        }

    The parser is intentionally loose — extra fields are preserved in metadata.
    Use value_text instead of value for non-numeric results (e.g. "阳性").

    Args:
        lab_json:   The lab result JSON object
        extra_tags: Additional tags to merge with ["lab"] default,
                    e.g. ["blood"] → tags become ["lab", "blood"]

    Returns:
        raw_id, evidence_count, cascaded_canonicals, skipped_count, next_steps
    """
    return ingest_pipeline.ingest_lab_json(
        user_id=_uid(),
        raw_json=lab_json,
        extra_tags=extra_tags,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _make_http_app():
    """
    Build the ASGI app for HTTP mode.

    Wraps FastMCP's SSE app with UserIdMiddleware so each connection's
    ?user_id= query param is injected into the ContextVar for that request.

    URL format for testers:
        https://your-server.com/mcp?user_id=<their-uuid>

    The UUID acts as a lightweight access token for internal testing.
    Anyone who knows their UUID can access only their own data.
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    class UserIdMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            uid = request.query_params.get("user_id") or settings.default_user_id
            token = _request_user_id.set(uid)
            try:
                response = await call_next(request)
            finally:
                _request_user_id.reset(token)
            return response

    base_app = mcp.sse_app()
    base_app.add_middleware(UserIdMiddleware)
    return base_app


if __name__ == "__main__":
    import sys
    if "--http" in sys.argv:
        import uvicorn
        port = int(next((sys.argv[i + 1] for i, a in enumerate(sys.argv)
                         if a == "--port" and i + 1 < len(sys.argv)), 8000))
        uvicorn.run(_make_http_app(), host="0.0.0.0", port=port)
    else:
        mcp.run()   # stdio — for Claude Desktop
