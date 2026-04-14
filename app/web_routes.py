"""
REST API routes for the Health Connector web dashboard.

Mounted at /api/* in the Starlette app (mcp_server._make_http_app).
Authentication: Bearer JWT (same token issued by Google OAuth flow).
The user_id is extracted from the JWT by JWTMiddleware and injected
via the _request_user_id ContextVar — imported from mcp_server at mount time.

Endpoints
─────────
GET  /api/me
GET  /api/profile                PUT  /api/profile
GET  /api/states                 POST /api/states
PUT  /api/states/{id}/end        DELETE /api/states/{id}
GET  /api/overview
GET  /api/insights               DELETE /api/insights/{id}
GET  /api/evidence               DELETE /api/evidence/{id}
GET  /api/canonical              DELETE /api/canonical/{id}
GET  /api/graph/entities         DELETE /api/graph/entities/{id}
GET  /api/graph/edges            DELETE /api/graph/edges/{id}
"""

from __future__ import annotations

import json
import contextvars
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.dal import profile as profile_dal
from app.dal import users as users_dal
from app.dal import evidence as evidence_dal
from app.dal import canonical as canonical_dal
from app.dal import insights as insights_dal
from app.dal import graph as graph_dal
from app.database import get_db

# Injected by mcp_server after import
_request_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_web_request_user_id", default=None
)


def _uid(request: Request) -> str | None:
    """Extract user_id set by JWTMiddleware."""
    return _request_user_id.get()


def _ok(data) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data})


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": msg}, status_code=status)


# ─────────────────────────────────────────────────────────────────────────────
# /api/me
# ─────────────────────────────────────────────────────────────────────────────

async def api_me(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    user = users_dal.get_user(uid)
    if not user:
        return _err("User not found", 404)
    return _ok(user)


# ─────────────────────────────────────────────────────────────────────────────
# /api/profile
# ─────────────────────────────────────────────────────────────────────────────

async def api_get_profile(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    data = profile_dal.get_profile(uid)
    return _ok(data)


async def api_put_profile(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    try:
        body = await request.json()
    except Exception:
        return _err("Invalid JSON body")
    if not isinstance(body, dict):
        return _err("Expected a JSON object")
    result = profile_dal.set_profile(uid, body)
    return _ok(result)


async def api_profile(request: Request) -> JSONResponse:
    if request.method == "GET":
        return await api_get_profile(request)
    if request.method == "PUT":
        return await api_put_profile(request)
    return _err("Method not allowed", 405)


# ─────────────────────────────────────────────────────────────────────────────
# /api/states
# ─────────────────────────────────────────────────────────────────────────────

async def api_get_states(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    active_only = request.query_params.get("active_only", "false").lower() == "true"
    states = profile_dal.get_all_states(uid, include_inactive=not active_only)
    return _ok(states)


async def api_post_state(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    try:
        body = await request.json()
    except Exception:
        return _err("Invalid JSON body")
    required = ("state_type", "label", "started_on")
    for field in required:
        if not body.get(field):
            return _err(f"Missing required field: {field}")
    result = profile_dal.add_state(
        user_id=uid,
        state_type=body["state_type"],
        label=body["label"],
        started_on=body["started_on"],
        detail=body.get("detail"),
        ends_on=body.get("ends_on"),
    )
    return _ok(result)


async def api_states(request: Request) -> JSONResponse:
    if request.method == "GET":
        return await api_get_states(request)
    if request.method == "POST":
        return await api_post_state(request)
    return _err("Method not allowed", 405)


async def api_end_state(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    state_id = request.path_params["id"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    from datetime import date
    ended_on = body.get("ended_on") or str(date.today())
    result = profile_dal.end_state(uid, state_id, ended_on)
    if not result:
        return _err("State not found", 404)
    return _ok(result)


async def api_delete_state(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    state_id = request.path_params["id"]
    db = get_db()
    db.table("user_states").delete().eq("id", state_id).eq("user_id", uid).execute()
    return _ok({"deleted": state_id})


async def api_state_detail(request: Request) -> JSONResponse:
    if request.method == "DELETE":
        return await api_delete_state(request)
    return _err("Method not allowed", 405)


async def api_state_end(request: Request) -> JSONResponse:
    return await api_end_state(request)


# ─────────────────────────────────────────────────────────────────────────────
# /api/overview
# ─────────────────────────────────────────────────────────────────────────────

async def api_overview(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    db = get_db()

    # Evidence summary by data_type
    ev_rows = (
        db.table("evidence")
        .select("data_type, recorded_at")
        .eq("user_id", uid)
        .order("recorded_at", desc=False)
        .execute()
        .data
    )
    ev_summary: dict = {}
    for row in ev_rows:
        dt = row["data_type"]
        if dt not in ev_summary:
            ev_summary[dt] = {"earliest": row["recorded_at"], "latest": row["recorded_at"], "count": 0}
        ev_summary[dt]["latest"] = row["recorded_at"]
        ev_summary[dt]["count"] += 1

    # Canonical summary by topic
    can_rows = (
        db.table("canonical")
        .select("topic, period, period_start, period_end")
        .eq("user_id", uid)
        .order("period_start", desc=False)
        .execute()
        .data
    )
    can_summary: dict = {}
    for row in can_rows:
        t = row["topic"]
        if t not in can_summary:
            can_summary[t] = {"periods": [], "earliest": row["period_start"], "latest": row["period_end"], "count": 0}
        if row["period"] not in can_summary[t]["periods"]:
            can_summary[t]["periods"].append(row["period"])
        can_summary[t]["latest"] = row["period_end"]
        can_summary[t]["count"] += 1

    # Insights count + recent
    ins_rows = (
        db.table("insights")
        .select("id, title, insight_type, topics, generated_at")
        .eq("user_id", uid)
        .order("generated_at", desc=True)
        .limit(5)
        .execute()
        .data
    )
    ins_total = (
        db.table("insights")
        .select("id", count="exact")
        .eq("user_id", uid)
        .execute()
        .count
    ) or 0

    # Graph counts
    entity_count = (
        db.table("entities")
        .select("id", count="exact")
        .eq("user_id", uid)
        .execute()
        .count
    ) or 0
    edge_count = (
        db.table("edges")
        .select("id", count="exact")
        .eq("user_id", uid)
        .execute()
        .count
    ) or 0

    return _ok({
        "evidence": {
            "total_points": sum(v["count"] for v in ev_summary.values()),
            "data_types": ev_summary,
        },
        "canonical": {
            "total_records": sum(v["count"] for v in can_summary.values()),
            "topics": can_summary,
        },
        "insights": {
            "total": ins_total,
            "recent": ins_rows,
        },
        "graph": {
            "entity_count": entity_count,
            "edge_count": edge_count,
        },
    })


# ─────────────────────────────────────────────────────────────────────────────
# /api/insights
# ─────────────────────────────────────────────────────────────────────────────

async def api_get_insights(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    p = request.query_params
    # For the web dashboard, skip semantic search (no OpenAI call on list).
    # Use exact filter mode only.
    rows = insights_dal.query_insights(
        user_id=uid,
        topics=[p["topic"]] if p.get("topic") else None,
        date_from=p.get("date_from"),
        date_to=p.get("date_to"),
        insight_type=p.get("insight_type") or None,
        limit=int(p.get("limit", 20)),
    )
    return _ok(rows)


async def api_delete_insight(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    iid = request.path_params["id"]
    db = get_db()
    db.table("insights").delete().eq("id", iid).eq("user_id", uid).execute()
    return _ok({"deleted": iid})


async def api_insights(request: Request) -> JSONResponse:
    if request.method == "GET":
        return await api_get_insights(request)
    return _err("Method not allowed", 405)


async def api_insight_detail(request: Request) -> JSONResponse:
    if request.method == "DELETE":
        return await api_delete_insight(request)
    return _err("Method not allowed", 405)


# ─────────────────────────────────────────────────────────────────────────────
# /api/evidence
# ─────────────────────────────────────────────────────────────────────────────

async def api_get_evidence(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    p = request.query_params
    data_types = [dt.strip() for dt in p["data_type"].split(",")] if p.get("data_type") else None
    rows = evidence_dal.query_evidence(
        user_id=uid,
        data_types=data_types,
        date_from=p.get("date_from"),
        date_to=p.get("date_to"),
        limit=int(p.get("limit", 100)),
    )
    return _ok(rows)


async def api_delete_evidence(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    eid = request.path_params["id"]
    db = get_db()
    db.table("evidence").delete().eq("id", eid).eq("user_id", uid).execute()
    return _ok({"deleted": eid})


async def api_evidence(request: Request) -> JSONResponse:
    if request.method == "GET":
        return await api_get_evidence(request)
    return _err("Method not allowed", 405)


async def api_evidence_detail(request: Request) -> JSONResponse:
    if request.method == "DELETE":
        return await api_delete_evidence(request)
    return _err("Method not allowed", 405)


# ─────────────────────────────────────────────────────────────────────────────
# /api/canonical
# ─────────────────────────────────────────────────────────────────────────────

async def api_get_canonical(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    p = request.query_params
    rows = canonical_dal.query_canonical(
        user_id=uid,
        topic=p.get("topic") or None,
        period=p.get("period") or None,
        date_from=p.get("date_from"),
        date_to=p.get("date_to"),
        limit=int(p.get("limit", 50)),
    )
    return _ok(rows)


async def api_delete_canonical(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    cid = request.path_params["id"]
    db = get_db()
    db.table("canonical").delete().eq("id", cid).eq("user_id", uid).execute()
    return _ok({"deleted": cid})


async def api_canonical(request: Request) -> JSONResponse:
    if request.method == "GET":
        return await api_get_canonical(request)
    return _err("Method not allowed", 405)


async def api_canonical_detail(request: Request) -> JSONResponse:
    if request.method == "DELETE":
        return await api_delete_canonical(request)
    return _err("Method not allowed", 405)


# ─────────────────────────────────────────────────────────────────────────────
# /api/graph
# ─────────────────────────────────────────────────────────────────────────────

async def api_get_entities(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    entity_type = request.query_params.get("entity_type") or None
    rows = graph_dal.list_entities(uid, entity_type=entity_type)
    return _ok(rows)


async def api_delete_entity(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    eid = request.path_params["id"]
    db = get_db()
    db.table("entities").delete().eq("id", eid).eq("user_id", uid).execute()
    return _ok({"deleted": eid})


async def api_graph_entities(request: Request) -> JSONResponse:
    if request.method == "GET":
        return await api_get_entities(request)
    return _err("Method not allowed", 405)


async def api_graph_entity_detail(request: Request) -> JSONResponse:
    if request.method == "DELETE":
        return await api_delete_entity(request)
    return _err("Method not allowed", 405)


async def api_get_edges(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    db = get_db()
    rows = (
        db.table("edges")
        .select(
            "id, source_id, target_id, relationship, confidence, explanation, observed_at,"
            "source:entities!edges_source_id_fkey(label,entity_type),"
            "target:entities!edges_target_id_fkey(label,entity_type)"
        )
        .eq("user_id", uid)
        .order("confidence", desc=True)
        .execute()
        .data
    )
    return _ok(rows)


async def api_delete_edge(request: Request) -> JSONResponse:
    uid = _uid(request)
    if not uid:
        return _err("Not authenticated", 401)
    eid = request.path_params["id"]
    db = get_db()
    db.table("edges").delete().eq("id", eid).eq("user_id", uid).execute()
    return _ok({"deleted": eid})


async def api_graph_edges(request: Request) -> JSONResponse:
    if request.method == "GET":
        return await api_get_edges(request)
    return _err("Method not allowed", 405)


async def api_graph_edge_detail(request: Request) -> JSONResponse:
    if request.method == "DELETE":
        return await api_delete_edge(request)
    return _err("Method not allowed", 405)


# ─────────────────────────────────────────────────────────────────────────────
# Route list — imported by mcp_server._make_http_app()
# ─────────────────────────────────────────────────────────────────────────────

WEB_API_ROUTES = [
    Route("/api/me",                        api_me),
    Route("/api/profile",                   api_profile,            methods=["GET", "PUT"]),
    Route("/api/states",                    api_states,             methods=["GET", "POST"]),
    Route("/api/states/{id}/end",           api_state_end,          methods=["PUT"]),
    Route("/api/states/{id}",               api_state_detail,       methods=["DELETE"]),
    Route("/api/overview",                  api_overview),
    Route("/api/insights",                  api_insights,           methods=["GET"]),
    Route("/api/insights/{id}",             api_insight_detail,     methods=["DELETE"]),
    Route("/api/evidence",                  api_evidence,           methods=["GET"]),
    Route("/api/evidence/{id}",             api_evidence_detail,    methods=["DELETE"]),
    Route("/api/canonical",                 api_canonical,          methods=["GET"]),
    Route("/api/canonical/{id}",            api_canonical_detail,   methods=["DELETE"]),
    Route("/api/graph/entities",            api_graph_entities,     methods=["GET"]),
    Route("/api/graph/entities/{id}",       api_graph_entity_detail,methods=["DELETE"]),
    Route("/api/graph/edges",               api_graph_edges,        methods=["GET"]),
    Route("/api/graph/edges/{id}",          api_graph_edge_detail,  methods=["DELETE"]),
]
