"""
Health Connector — MCP Server

Claude Desktop connects here via MCP protocol.
Claude handles all orchestration, memory, and synthesis.
This server is purely a data layer: read + write health data.

Architecture:
  Claude Desktop ←→ MCP Server (this file) ←→ Supabase (Profile + 4-layer DB)

Tools exposed:
  USERS   — list_users, create_user
  PROFILE — get_user_context, set_user_profile, set_user_state, end_user_state
  READ    — get_data_overview, query_insights, query_canonical, query_evidence, query_raw
  GRAPH   — add_entity, add_edge, query_cause_chain, get_entity_neighborhood, search_entities
  WRITE   — ingest_evidence, create_insight, upsert_canonical, store_document, ingest_lab_json
"""

import json
import contextvars
from datetime import date
from mcp.server.fastmcp import FastMCP
from app.config import settings
from app.auth import jwt_utils
from app.auth.routes import AUTH_ROUTES
from app.dal import evidence as evidence_dal
from app.dal import canonical as canonical_dal
from app.dal import insights as insights_dal
from app.dal import raw as raw_dal
from app.dal import profile as profile_dal
from app.database import get_db
from app.ingestion import pipeline as ingest_pipeline
from app.dal import users as users_dal
from app.dal import graph as graph_dal
from app.web_routes import WEB_API_ROUTES
import app.web_routes as _web_routes_module

mcp = FastMCP(
    name="Health Connector",
    stateless_http=True,   # No mcp-session-id tracking — survives server restarts
    instructions="""
You have access to a structured personal health database.

## Step 1 — Load the active user context (every conversation)
The active user is determined automatically from their login. Call `get_user_context` at the start
of every conversation to load their profile and states.
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

## Step 4 — Query layers (Canonical + Graph in parallel, top-down for evidence)

**Canonical layer** — trend summaries by topic and period:
1. `query_insights`  — past high-level analysis, trends, correlations
2. `query_canonical` — aggregated topic summaries (day / week / month)
3. `query_evidence`  — individual data points with exact values and timestamps
4. `query_raw`       — original source files, last resort only

**Graph layer** — knowledge graph for root cause and effect tracing:
- `search_entities`         — find entities before querying the graph
- `get_entity_neighborhood` — see everything connected to one entity (one hop)
- `query_cause_chain`       — traverse causal chains upstream or downstream

Query Canonical AND Graph in parallel when doing analysis — they provide complementary information:
- Canonical answers "what happened and when" (trend data)
- Graph answers "why it happened and what it caused" (causal structure)

For any question involving "why", "what causes", "what's the relationship", or
training/nutrition/symptom analysis: ALWAYS call `search_entities` on the key
concepts first. The graph may already contain decision paths from prior analyses
that should inform and constrain your response. Use those paths as your starting
point before reasoning from general knowledge.

## Step 5 — Maintain the graph: read first, then write only when better

The graph is a **living knowledge base of reasoning conclusions** — not a data mirror.
Nodes and edges are created during analysis to capture what you concluded, not to
replicate what was ingested. Never auto-promote evidence rows to nodes at ingest time.

### 5a — Two node patterns (decide before calling add_entity)

**Stable node** — value rarely changes, store the value directly in the label:
  entity_type: "biomarker", label: "身高 175cm"
  properties:  { "value": 175, "unit": "cm", "stable": true, "recorded_at": "YYYY-MM-DD" }
  Use for: 身高, 体重 (when not tracking trend), 血型, 过敏史, 基因检测结果

**Trend summary node** — aggregate first from canonical, then store the period summary:
  entity_type: "biomarker", label: "血压均值 2026-04"
  properties:  { "period": "2026-04", "avg_systolic": 130, "avg_diastolic": 85,
                 "max": 145, "data_points": 28, "unit": "mmHg" }
  Use for: 血压, 心率, HRV, 血糖, 睡眠深度, 体重趋势, 饮食摘要
  → Call query_canonical first to get the aggregated values, then call add_entity.
  → Label format: "{指标名} {period}" e.g. "静息心率均值 2026-W15", "血糖均值 2026-04"

After creating a trend/stable node, optionally link it to the abstract concept:
  add_edge: "血压均值 2026-04" --instantiates--> "血压"  (so cause chains can traverse periods)

### 5b — Always read before writing
Before finalising any analysis that involves causal or correlational reasoning:
1. Call `search_entities` to find relevant nodes that already exist.
2. Call `get_entity_neighborhood` or `query_cause_chain` on those nodes to see
   what decision paths are already recorded.
3. Evaluate each existing path: is it still the best explanation?

### 5c — Write edges ONLY when the graph improves

| Situation | Action |
|-----------|--------|
| Relationship does not exist yet | `add_entity` + `add_edge` to record the new path |
| Existing edge exists but your confidence is **higher** | Call `add_edge` again — the upsert upgrades confidence and explanation |
| Existing explanation is incomplete or wrong | Call `add_edge` with a corrected explanation |

Do NOT call `add_edge` when the existing path already captures the relationship
at equal or higher confidence — you would degrade rather than improve the graph.

Relationship types:
  "causes"          — A directly causes B (strong causal claim)
  "correlates_with" — A and B co-occur or are statistically linked
  "worsens"         — A makes B worse
  "resolves"        — A treats or resolves B
  "indicates"       — biomarker → condition it points to
  "triggered_by"    — event/state → response
  "precedes"        — temporal link without claiming causality
  "instantiates"    — period/stable node → abstract concept (e.g. "血压均值 2026-04" → "血压")

Confidence guide: 0.5 = weak/speculative, 0.7 = plausible, 0.9 = well-established.

## Step 6 — Save narrative results only when novel
Call `create_insight` to persist a finding only when it is genuinely new or
provides a materially better explanation than existing insights (check with
`query_insights` first). If the finding is already captured, skip.
If you derive a useful aggregated topic summary, call `upsert_canonical`.
""".strip(),
)

# ── User context ──────────────────────────────────────────────────────────────
_request_user_id: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar("_request_user_id", default=None)
)


def _uid() -> str:
    """Return the active user UUID for the current request (from JWT)."""
    uid = _request_user_id.get()
    if not uid:
        raise ValueError("No authenticated user for this request")
    return uid


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
# GRAPH tools  (entities + causal edges)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def add_entity(
    entity_type: str,
    label: str,
    properties: dict | None = None,
) -> dict:
    """
    Add or update an entity node in the health knowledge graph.
    Safe to call multiple times — merges properties on conflict.

    Call this ONLY during analysis/QA — never at ingest time.
    Choose the node pattern before calling:

    STABLE NODE (value rarely changes — store value in label):
        label:      "身高 175cm"  |  "血型 A"  |  "青霉素过敏"
        properties: { "value": 175, "unit": "cm", "stable": true, "recorded_at": "YYYY-MM-DD" }
        Use for:    身高, 血型, 基因检测结果, 过敏史, 手术史

    TREND SUMMARY NODE (aggregate from canonical first, then store period summary):
        label:      "血压均值 2026-04"  |  "静息心率均值 2026-W15"  |  "HRV均值 2026-04"
        properties: { "period": "2026-04", "avg_systolic": 130, "avg_diastolic": 85,
                      "max": 145, "data_points": 28, "unit": "mmHg" }
        Use for:    血压, 心率, HRV, 血糖, 睡眠深度, 体重趋势, 饮食指标
        → Query canonical first to get aggregated values, then call this tool.
        → After creating, link to abstract concept:
          add_edge "血压均值 2026-04" --instantiates--> "血压"

    Entity types:
        "biomarker"    — stable or trend metric: WBC, "血压均值 2026-04", "身高 175cm"
        "symptom"      — subjective complaint: 疲劳, 头痛, 失眠, 食欲不振
        "condition"    — diagnosis or state: 术后炎症, 高血压, 贫血, 低血糖
        "intervention" — treatment or action: 阿莫西林, 低碳饮食, 有氧训练
        "lifestyle"    — environmental factor: 睡眠不足, 高压工作, 久坐
        "event"        — discrete occurrence: 阑尾切除术, 马拉松比赛, 献血

    Args:
        entity_type: One of the types above
        label:       For stable: include value e.g. "身高 175cm".
                     For trend: include period e.g. "血压均值 2026-04".
                     For abstract concepts: short name e.g. "血压", "HRV".
        properties:  See patterns above.
    """
    return graph_dal.upsert_entity(
        user_id=_uid(),
        entity_type=entity_type,
        label=label,
        properties=properties,
    )


@mcp.tool()
def add_edge(
    source_type: str,
    source_label: str,
    relationship: str,
    target_type: str,
    target_label: str,
    confidence: float = 0.7,
    explanation: str | None = None,
    evidence_ids: list[str] | None = None,
    observed_at: str | None = None,
) -> dict:
    """
    Add or update a directed relationship between two entities.
    Entities are auto-created if they don't exist.

    Direction: source --relationship--> target
    Example:   "术后炎症" --causes--> "WBC升高"
               "WBC升高"  --correlates_with--> "疲劳"

    Relationship types:
        "causes"          — A directly causes B (strong causal claim)
        "correlates_with" — A and B co-occur or are statistically linked
        "triggered_by"    — A was triggered by B (event → response)
        "worsens"         — A makes B worse
        "resolves"        — A treats or resolves B
        "indicates"       — A is a clinical indicator of B (biomarker → condition)
        "precedes"        — A temporally precedes B (no causality claimed)
        "instantiates"    — period/stable node → abstract concept
                            e.g. "血压均值 2026-04" --instantiates--> "血压"
                            Enables cross-period cause chain traversal.

    Args:
        source_type:  Entity type of the source node
        source_label: Label of the source node
        relationship: One of the relationship types above
        target_type:  Entity type of the target node
        target_label: Label of the target node
        confidence:   0.0–1.0, your confidence in this relationship
        explanation:  One-sentence rationale for this relationship
        evidence_ids: UUIDs of evidence rows that support this edge
        observed_at:  ISO date when this relationship was observed "YYYY-MM-DD"
    """
    return graph_dal.upsert_edge(
        user_id=_uid(),
        source_entity_type=source_type,
        source_label=source_label,
        target_entity_type=target_type,
        target_label=target_label,
        relationship=relationship,
        confidence=confidence,
        explanation=explanation,
        evidence_ids=evidence_ids,
        observed_at=observed_at,
    )


@mcp.tool()
def query_cause_chain(
    entity_type: str,
    label: str,
    direction: str = "upstream",
    max_depth: int = 3,
) -> dict:
    """
    Traverse the knowledge graph from a focal entity to find causal chains.

    Use this for root cause analysis and effect tracing.

    upstream   → "what caused this?"   — follow incoming causal edges
    downstream → "what does this cause?" — follow outgoing causal edges

    Example queries:
        query_cause_chain("biomarker", "WBC", direction="upstream")
        → 术后炎症 --causes--> WBC升高 (depth 1)
          阑尾切除术 --triggered_by--> 术后炎症 (depth 2)

        query_cause_chain("symptom", "疲劳", direction="upstream")
        → WBC升高 --correlates_with--> 疲劳
          睡眠不足 --worsens--> 疲劳

    Args:
        entity_type: Type of the focal entity
        label:       Label of the focal entity
        direction:   "upstream" (find causes) or "downstream" (find effects)
        max_depth:   How many hops to traverse (default 3, max 5)

    Returns:
        focal_entity, direction, chain (list of edges with depth), summary (plain text)
    """
    return graph_dal.query_cause_chain(
        user_id=_uid(),
        entity_type=entity_type,
        label=label,
        direction=direction,
        max_depth=min(max_depth, 5),
    )


@mcp.tool()
def get_entity_neighborhood(
    entity_type: str,
    label: str,
    relationship: str | None = None,
) -> dict:
    """
    Return all edges directly connected to an entity (one hop, both directions).

    Use this to see everything the graph knows about a specific entity.

    Args:
        entity_type:  Type of the focal entity
        label:        Label of the focal entity
        relationship: Optional filter, e.g. "causes" to see only causal edges

    Returns:
        entity, outgoing edges (what it affects), incoming edges (what affects it)
    """
    return graph_dal.get_neighborhood(
        user_id=_uid(),
        entity_type=entity_type,
        label=label,
        relationship=relationship,
    )


@mcp.tool()
def search_entities(
    query: str | None = None,
    entity_type: str | None = None,
) -> list[dict]:
    """
    Search for entities in the knowledge graph by label or type.

    Use this to find an entity before querying its neighborhood or cause chain.

    Args:
        query:       Partial label to match, e.g. "WBC", "炎症", "疲劳"
        entity_type: Filter to one type, e.g. "biomarker" | "symptom" | "condition"
    """
    return graph_dal.search_entities(
        user_id=_uid(),
        query=query,
        entity_type=entity_type,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _make_http_app():
    """
    Build the ASGI app for HTTP mode.

    Combines:
    - public OAuth routes + web SPA static files
    - /api/* REST routes protected by Bearer JWT
    - MCP SSE routes protected by Bearer JWT
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import BaseRoute, Mount
    from starlette.staticfiles import StaticFiles
    import os

    # Share the ContextVar so web_routes can read the authenticated user_id
    # that JWTMiddleware sets on each request.
    _web_routes_module._request_user_id = _request_user_id

    # Paths that do NOT require a JWT (OAuth flow + web SPA assets)
    _PUBLIC_PREFIXES = (
        "/.well-known/",
        "/authorize",
        "/callback",
        "/token",
        "/register",
        "/me",
        "/app",      # Next.js static export served here
    )

    _CORS_HEADERS = [
        (b"access-control-allow-origin",  b"*"),
        (b"access-control-allow-methods", b"GET, POST, PUT, DELETE, OPTIONS"),
        (b"access-control-allow-headers", b"authorization, content-type"),
    ]

    # Pure ASGI middleware — BaseHTTPMiddleware breaks SSE streaming responses.
    class JWTMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            path   = scope.get("path", "")
            method = scope.get("method", "")

            # Inject CORS headers into every response
            async def send_with_cors(message):
                if message["type"] == "http.response.start":
                    message = dict(message)
                    message["headers"] = list(message.get("headers", [])) + _CORS_HEADERS
                await send(message)

            # OPTIONS preflight — reply immediately, no JWT needed
            if method == "OPTIONS":
                from starlette.responses import Response as PlainResponse
                response = PlainResponse(status_code=204)
                await response(scope, receive, send_with_cors)
                return

            # Public paths bypass JWT check
            if any(path == p or path.startswith(p) for p in _PUBLIC_PREFIXES):
                await self.app(scope, receive, send_with_cors)
                return

            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode()
            if not auth_header.startswith("Bearer "):
                base = settings.base_url.rstrip("/")
                response = JSONResponse(
                    {"error": "Missing Bearer token"},
                    status_code=401,
                    headers={
                        "WWW-Authenticate": (
                            f'Bearer realm="{base}",'
                            f' resource_metadata="{base}/.well-known/oauth-protected-resource"'
                        )
                    },
                )
                await response(scope, receive, send_with_cors)
                return

            try:
                uid = jwt_utils.validate_token(auth_header[7:])
            except Exception as exc:
                response = JSONResponse(
                    {"error": f"Invalid token: {exc}"},
                    status_code=401,
                )
                await response(scope, receive, send_with_cors)
                return

            token = _request_user_id.set(uid)
            try:
                await self.app(scope, receive, send_with_cors)
            finally:
                _request_user_id.reset(token)

    # Use Streamable HTTP transport (MCP 2025-03-26) required by Claude.ai remote MCP.
    # Web API routes and SPA are mounted before the MCP catch-all at "/".
    mcp.settings.streamable_http_path = "/"
    base_app = mcp.streamable_http_app()
    mcp_handler = base_app.routes[0].app  # Mount("/", handler) → extract handler

    # Static files for the Next.js SPA (built output at web/out)
    spa_routes: list[BaseRoute] = []
    spa_dir = os.path.join(os.path.dirname(__file__), "web", "out")
    if os.path.isdir(spa_dir):
        spa_routes = [Mount("/app", app=StaticFiles(directory=spa_dir, html=True))]

    routes: list[BaseRoute] = [
        *AUTH_ROUTES,
        *WEB_API_ROUTES,   # /api/* before MCP catch-all
        *spa_routes,
        Mount("/", app=mcp_handler),
    ]
    combined = Starlette(
        routes=routes,
        lifespan=lambda _app: mcp.session_manager.run(),
    )
    return JWTMiddleware(combined)


if __name__ == "__main__":
    import sys
    if "--http" in sys.argv:
        import uvicorn
        port = int(next((sys.argv[i + 1] for i, a in enumerate(sys.argv)
                         if a == "--port" and i + 1 < len(sys.argv)), 8000))
        uvicorn.run(_make_http_app(), host="0.0.0.0", port=port)
    else:
        mcp.run()   # stdio — for Claude Desktop
