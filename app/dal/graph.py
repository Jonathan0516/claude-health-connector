"""
Graph Layer DAL — entities and edges.

Implements a relational graph stored in Supabase PostgreSQL.
Nodes = entities (biomarkers, symptoms, conditions, interventions, ...)
Edges = directed relationships (causes, correlates_with, resolves, ...)

Cause chain traversal delegates to the get_cause_chain() Postgres RPC
which handles recursion efficiently in the DB.
"""

from __future__ import annotations
from app.database import get_db


# Valid entity types and relationship types (for documentation; not enforced here)
#
# Node creation philosophy:
#   Nodes are NOT a mechanical mirror of every evidence row.
#   They are created during QA/analysis sessions when Claude decides a concept
#   is worth anchoring in the graph. Two patterns:
#
#   1. Stable node — value rarely changes, store directly:
#        entity_type: "biomarker", label: "身高 175cm"
#        properties:  { value: 175, unit: "cm", stable: True, recorded_at: "YYYY-MM-DD" }
#        Examples: 身高, 血型, 基因检测, 过敏史
#
#   2. Trend summary node — aggregate first, then store:
#        entity_type: "biomarker", label: "血压均值 2026-04"
#        properties:  { period: "2026-04", avg_systolic: 130, avg_diastolic: 85,
#                       max: 145, data_points: 28, unit: "mmHg" }
#        Examples: 血压, 心率, HRV, 血糖, 睡眠深度
#        → Query canonical layer first for the period summary, then create the node.
#
# Edges are ONLY created when Claude actively reasons a connection during analysis.
# Never auto-promote evidence rows to nodes at ingest time.
ENTITY_TYPES = (
    "biomarker",    # measurable metric: WBC, HRV, 血压均值 2026-04, 身高 175cm
    "symptom",      # subjective complaint: 疲劳, 头痛, 失眠
    "condition",    # diagnosis or state: 高血压, 贫血, 术后炎症
    "intervention", # treatment or action: 阿莫西林, 低碳饮食, 有氧训练
    "lifestyle",    # environmental factor: 睡眠不足, 高压工作, 久坐
    "event",        # discrete occurrence: 阑尾切除术, 马拉松比赛, 献血
)
RELATIONSHIPS = (
    "causes",          # A directly causes B (strong causal claim)
    "correlates_with", # A and B co-occur or are statistically linked
    "triggered_by",    # A was triggered by B (event → response)
    "worsens",         # A makes B worse
    "resolves",        # A treats or resolves B
    "indicates",       # A is a clinical indicator of B (biomarker → condition)
    "precedes",        # A temporally precedes B (no causality claimed)
    "instantiates",    # trend/stable node → abstract biomarker concept
                       # e.g. "血压均值 2026-04" --instantiates--> "血压"
)


# ─────────────────────────────────────────────────────────────────────────────
# Entities
# ─────────────────────────────────────────────────────────────────────────────

def upsert_entity(
    user_id: str,
    entity_type: str,
    label: str,
    properties: dict | None = None,
) -> dict:
    """
    Create or update an entity node. Safe to call multiple times with the
    same (user_id, entity_type, label) — merges properties on conflict.

    Returns the upserted entity row.
    """
    db = get_db()
    existing = get_entity(user_id, entity_type, label)
    merged_props = {**(existing.get("properties") or {}), **(properties or {})}

    res = (
        db.table("entities")
        .upsert(
            {
                "user_id":     user_id,
                "entity_type": entity_type,
                "label":       label,
                "properties":  merged_props,
                "updated_at":  "now()",
            },
            on_conflict="user_id,entity_type,label",
        )
        .execute()
    )
    return res.data[0]


def get_entity(
    user_id: str,
    entity_type: str,
    label: str,
) -> dict:
    """Look up an entity by type + label. Returns {} if not found."""
    db = get_db()
    res = (
        db.table("entities")
        .select("*")
        .eq("user_id", user_id)
        .eq("entity_type", entity_type)
        .ilike("label", label)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else {}


def search_entities(
    user_id: str,
    query: str | None = None,
    entity_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Search entities by label (case-insensitive substring) and/or type.

    Args:
        query:       Partial label to search, e.g. "WBC" or "炎症"
        entity_type: Filter to one type, e.g. "biomarker"
        limit:       Max results
    """
    db = get_db()
    q = db.table("entities").select("*").eq("user_id", user_id)
    if query:
        q = q.ilike("label", f"%{query}%")
    if entity_type:
        q = q.eq("entity_type", entity_type)
    return q.order("label").limit(limit).execute().data


def list_entities(user_id: str, entity_type: str | None = None) -> list[dict]:
    """List all entities, optionally filtered by type."""
    db = get_db()
    q = db.table("entities").select("id, entity_type, label, properties").eq("user_id", user_id)
    if entity_type:
        q = q.eq("entity_type", entity_type)
    return q.order("entity_type").order("label").execute().data


# ─────────────────────────────────────────────────────────────────────────────
# Edges
# ─────────────────────────────────────────────────────────────────────────────

def upsert_edge(
    user_id: str,
    source_entity_type: str,
    source_label: str,
    target_entity_type: str,
    target_label: str,
    relationship: str,
    confidence: float = 0.7,
    explanation: str | None = None,
    evidence_ids: list[str] | None = None,
    observed_at: str | None = None,
) -> dict:
    """
    Add or update a directed relationship between two entities.
    Entities are auto-created if they don't exist yet.

    source --relationship--> target
    e.g. "术后炎症" --causes--> "WBC升高"

    Returns the upserted edge row with source/target labels resolved.
    """
    db = get_db()

    # Ensure both entities exist
    source = upsert_entity(user_id, source_entity_type, source_label)
    target = upsert_entity(user_id, target_entity_type, target_label)

    res = (
        db.table("edges")
        .upsert(
            {
                "user_id":      user_id,
                "source_id":    source["id"],
                "target_id":    target["id"],
                "relationship": relationship,
                "confidence":   confidence,
                "explanation":  explanation,
                "evidence_ids": evidence_ids or [],
                "observed_at":  observed_at,
                "updated_at":   "now()",
            },
            on_conflict="user_id,source_id,target_id,relationship",
        )
        .execute()
    )
    edge = res.data[0]
    # Enrich response so caller can read source/target labels directly
    edge["source_label"] = source_label
    edge["source_type"]  = source_entity_type
    edge["target_label"] = target_label
    edge["target_type"]  = target_entity_type
    return edge


def get_neighborhood(
    user_id: str,
    entity_type: str,
    label: str,
    relationship: str | None = None,
) -> dict:
    """
    Return all edges directly connected to an entity (both directions).

    Args:
        entity_type: Type of the focal entity
        label:       Label of the focal entity
        relationship: Filter to a specific relationship type

    Returns:
        {
          "entity": {...},
          "outgoing": [{source, relationship, target, confidence, explanation}, ...],
          "incoming": [...]
        }
    """
    db = get_db()
    entity = get_entity(user_id, entity_type, label)
    if not entity:
        return {"entity": None, "outgoing": [], "incoming": []}

    eid = entity["id"]

    def _fetch_edges(col: str) -> list[dict]:
        q = (
            db.table("edges")
            .select("*, source:entities!edges_source_id_fkey(label,entity_type), target:entities!edges_target_id_fkey(label,entity_type)")
            .eq("user_id", user_id)
            .eq(col, eid)
        )
        if relationship:
            q = q.eq("relationship", relationship)
        return q.order("confidence", desc=True).execute().data

    outgoing = _fetch_edges("source_id")
    incoming = _fetch_edges("target_id")

    def _fmt(rows: list[dict]) -> list[dict]:
        out = []
        for r in rows:
            out.append({
                "source":       r.get("source", {}).get("label", ""),
                "source_type":  r.get("source", {}).get("entity_type", ""),
                "relationship": r["relationship"],
                "target":       r.get("target", {}).get("label", ""),
                "target_type":  r.get("target", {}).get("entity_type", ""),
                "confidence":   r["confidence"],
                "explanation":  r.get("explanation"),
            })
        return out

    return {
        "entity":   entity,
        "outgoing": _fmt(outgoing),
        "incoming": _fmt(incoming),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Cause chain traversal (delegates to Postgres recursive CTE)
# ─────────────────────────────────────────────────────────────────────────────

def query_cause_chain(
    user_id: str,
    entity_type: str,
    label: str,
    direction: str = "upstream",   # "upstream" | "downstream"
    max_depth: int = 3,
) -> dict:
    """
    Traverse the graph from a focal entity along causal relationships.

    upstream   → "what caused this?" (follow incoming edges)
    downstream → "what does this cause?" (follow outgoing edges)

    Uses the get_cause_chain() Postgres RPC for efficient recursive traversal.

    Returns:
        {
          "focal_entity": {label, entity_type},
          "direction": "upstream",
          "chain": [
            {depth, source_label, source_type, relationship,
             target_label, target_type, confidence, explanation},
            ...
          ],
          "summary": "plain-text chain for LLM context"
        }
    """
    db = get_db()
    entity = get_entity(user_id, entity_type, label)
    if not entity:
        return {
            "focal_entity": {"label": label, "entity_type": entity_type},
            "direction": direction,
            "chain": [],
            "summary": f"Entity '{label}' ({entity_type}) not found in graph.",
        }

    res = db.rpc("get_cause_chain", {
        "p_user_id":   user_id,
        "p_entity_id": entity["id"],
        "p_direction": direction,
        "p_max_depth": max_depth,
    }).execute()

    chain = res.data or []
    summary = _chain_to_text(label, direction, chain)

    return {
        "focal_entity": {"label": label, "entity_type": entity_type},
        "direction":    direction,
        "chain":        chain,
        "summary":      summary,
    }


def _chain_to_text(focal: str, direction: str, chain: list[dict]) -> str:
    """Convert chain rows into a readable text for LLM context."""
    if not chain:
        return f"No {'upstream causes' if direction == 'upstream' else 'downstream effects'} found for '{focal}'."

    lines = [f"{'Root cause chain' if direction == 'upstream' else 'Effect chain'} for '{focal}':"]
    for row in chain:
        indent = "  " * (row["depth"] - 1)
        conf = f"{int(row['confidence'] * 100)}%"
        lines.append(
            f"{indent}[depth {row['depth']}] "
            f"{row['source_label']} --{row['relationship']}--> {row['target_label']} "
            f"(confidence: {conf})"
        )
        if row.get("explanation"):
            lines.append(f"{indent}  → {row['explanation']}")
    return "\n".join(lines)
