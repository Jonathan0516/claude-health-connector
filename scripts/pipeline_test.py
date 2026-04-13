"""
Health Connector — Pipeline Diagnostic Test
============================================
Simulates the full 3-phase query pipeline and prints verbose monitoring output
so you can see exactly what happens at each step.

Usage:
    python scripts/pipeline_test.py
    python scripts/pipeline_test.py "为什么我最近睡眠质量下降了？"
    python scripts/pipeline_test.py "WBC result in April"
"""

import sys
import json
import time
import textwrap
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

from pydantic import BaseModel, Field
from openai import OpenAI

# Add project root to path so app.* imports work
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import settings
from app.dal import evidence as evidence_dal
from app.dal import canonical as canonical_dal
from app.dal import insights as insights_dal
from app.dal import raw as raw_dal
from app.database import get_db

# ─── ANSI colours ─────────────────────────────────────────────────────────────

BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
MAGENTA= "\033[35m"
RESET  = "\033[0m"

def header(phase: str, title: str) -> None:
    bar = "─" * 70
    print(f"\n{CYAN}{bar}{RESET}")
    print(f"{BOLD}{CYAN}  {phase}  |  {title}{RESET}")
    print(f"{CYAN}{bar}{RESET}")

def log(label: str, value, colour: str = RESET) -> None:
    label_str = f"{BOLD}{label:<20}{RESET}"
    if isinstance(value, (dict, list)):
        value_str = json.dumps(value, ensure_ascii=False, indent=2)
        lines = value_str.splitlines()
        print(f"  {label_str}  {colour}{lines[0]}{RESET}")
        for line in lines[1:]:
            print(f"  {' ' * 22}{colour}{line}{RESET}")
    else:
        print(f"  {label_str}  {colour}{value}{RESET}")

def ok(msg: str)    -> None: print(f"  {GREEN}✓ {msg}{RESET}")
def warn(msg: str)  -> None: print(f"  {YELLOW}⚠ {msg}{RESET}")
def err(msg: str)   -> None: print(f"  {RED}✗ {msg}{RESET}")
def dim(msg: str)   -> None: print(f"  {DIM}{msg}{RESET}")

def elapsed(start: float) -> str:
    return f"{(time.perf_counter() - start) * 1000:.0f}ms"

# ─── Pydantic schema for Phase 1 structured output ────────────────────────────

class HealthIntent(BaseModel):
    topics: list[str] = Field(
        default_factory=list,
        description="Canonical topic names from overview (e.g. sleep_quality). Empty list if none match."
    )
    data_types: list[str] = Field(
        default_factory=list,
        description="Evidence data_type names from overview (e.g. WBC, sleep_total_hours). Empty list if none match."
    )
    date_from: str | None = Field(
        default=None,
        description="ISO date YYYY-MM-DD. The start of the date range the user is asking about."
    )
    date_to: str | None = Field(
        default=None,
        description="ISO date YYYY-MM-DD. The end of the date range the user is asking about."
    )
    semantic_query: str = Field(
        description="Natural-language description to use for embedding-based insight search."
    )
    depth_needed: Literal["insights", "canonical", "evidence", "raw"] = Field(
        description=(
            "Minimum data depth required to answer this question.\n"
            "  insights  — high-level history is enough\n"
            "  canonical — topic summaries needed\n"
            "  evidence  — individual data points / lab results needed\n"
            "  raw       — original source files needed (last resort)"
        )
    )
    reasoning: str = Field(
        description="One sentence explaining why this depth was chosen."
    )

# ─── Main pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(user_question: str) -> None:
    print(f"\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}  HEALTH CONNECTOR — PIPELINE DIAGNOSTIC{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")
    print(f"\n  {BOLD}User question:{RESET}  {MAGENTA}{user_question}{RESET}")
    print(f"  {BOLD}Timestamp:{RESET}      {datetime.now().isoformat()}")

    openai_client = OpenAI(api_key=settings.openai_api_key)
    user_id = settings.default_user_id

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 0 — get_data_overview  (needed by Phase 1)
    # ──────────────────────────────────────────────────────────────────────────
    header("PHASE 0", "get_data_overview()")
    t0 = time.perf_counter()
    try:
        db = get_db()

        ev_rows = (
            db.table("evidence")
            .select("data_type, recorded_at, tags")
            .eq("user_id", user_id)
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

        can_rows = (
            db.table("canonical")
            .select("topic, period, period_start, period_end")
            .eq("user_id", user_id)
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

        ins_rows = (
            db.table("insights")
            .select("title, insight_type, topics, date_range_start, date_range_end, generated_at")
            .eq("user_id", user_id)
            .order("generated_at", desc=True)
            .limit(5)
            .execute()
            .data
        )

        overview = {
            "evidence_types": [
                {"data_type": dt, "earliest": v["earliest"][:10], "latest": v["latest"][:10], "tags": sorted(v["tags"])}
                for dt, v in ev_summary.items()
            ],
            "canonical_topics": [
                {"topic": t, "available_periods": sorted(v["periods"]), "earliest": v["earliest"], "latest": v["latest"]}
                for t, v in can_summary.items()
            ],
            "recent_insights": ins_rows,
        }

        ok(f"Done ({elapsed(t0)})")
        log("evidence_types", [r["data_type"] for r in overview["evidence_types"]], DIM)
        log("canonical_topics", [r["topic"] for r in overview["canonical_topics"]], DIM)
        log("recent_insights", len(overview["recent_insights"]), DIM)

    except Exception as e:
        err(f"get_data_overview failed: {e}")
        raise

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 1 — Intent Parser  (OpenAI structured output)
    # ──────────────────────────────────────────────────────────────────────────
    header("PHASE 1", "Intent Parser  →  HealthIntent")
    t1 = time.perf_counter()

    today = datetime.now().strftime("%Y-%m-%d")
    overview_summary = (
        f"Available evidence types: {[r['data_type'] for r in overview['evidence_types']]}\n"
        f"Available canonical topics: {[r['topic'] for r in overview['canonical_topics']]}\n"
        f"Today's date: {today}"
    )

    system_prompt = textwrap.dedent(f"""
        You are a health data query intent parser.
        Your job is to extract a structured HealthIntent from the user's question.

        Use ONLY the exact names listed in the overview below — never invent new ones.
        Resolve relative dates (e.g. "last week", "最近几天") relative to today ({today}).

        {overview_summary}
    """).strip()

    try:
        dim(f"Calling OpenAI structured output (gpt-4o)…")
        resp = openai_client.beta.chat.completions.parse(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_question},
            ],
            response_format=HealthIntent,
        )
        intent: HealthIntent = resp.choices[0].message.parsed
        ok(f"Parsed ({elapsed(t1)})")
        log("topics",         intent.topics or "(none)", YELLOW)
        log("data_types",     intent.data_types or "(none)", YELLOW)
        log("date_from",      intent.date_from or "(none)", YELLOW)
        log("date_to",        intent.date_to or "(none)", YELLOW)
        log("semantic_query", intent.semantic_query, YELLOW)
        log("depth_needed",   intent.depth_needed, GREEN)
        log("reasoning",      intent.reasoning, DIM)

    except Exception as e:
        err(f"Intent parsing failed: {e}")
        raise

    DEPTH_ORDER = ["insights", "canonical", "evidence", "raw"]

    def depth_gte(a: str, b: str) -> bool:
        """True if depth a is at least as deep as b."""
        return DEPTH_ORDER.index(a) >= DEPTH_ORDER.index(b)

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 2 — Retriever  (parallel DB calls, no LLM)
    # ──────────────────────────────────────────────────────────────────────────
    header("PHASE 2", "Retriever  →  RetrievedContext  (parallel)")

    retrieved: dict[str, list[dict]] = {
        "insights":  [],
        "canonical": [],
        "evidence":  [],
        "raw":       [],
    }
    phase2_timings: dict[str, str] = {}

    def fetch_insights() -> list[dict]:
        t = time.perf_counter()
        result = insights_dal.query_insights(
            user_id=user_id,
            query=intent.semantic_query,
            date_from=intent.date_from,
            date_to=intent.date_to,
            limit=5,
        )
        phase2_timings["insights"] = elapsed(t)
        return result

    def fetch_canonical_for_topic(topic: str) -> list[dict]:
        return canonical_dal.query_canonical(
            user_id=user_id,
            topic=topic,
            date_from=intent.date_from,
            date_to=intent.date_to,
        )

    def fetch_canonical() -> list[dict]:
        t = time.perf_counter()
        if not depth_gte(intent.depth_needed, "canonical"):
            phase2_timings["canonical"] = "skipped (depth < canonical)"
            return []
        if not intent.topics:
            phase2_timings["canonical"] = "skipped (no topics)"
            return []
        results = []
        for topic in intent.topics:
            rows = fetch_canonical_for_topic(topic)
            results.extend(rows)
        phase2_timings["canonical"] = elapsed(t)
        return results

    def fetch_evidence() -> list[dict]:
        t = time.perf_counter()
        if not depth_gte(intent.depth_needed, "evidence"):
            phase2_timings["evidence"] = "skipped (depth < evidence)"
            return []
        if not intent.data_types:
            phase2_timings["evidence"] = "skipped (no data_types)"
            return []
        result = evidence_dal.query_evidence(
            user_id=user_id,
            data_types=intent.data_types,
            date_from=intent.date_from,
            date_to=intent.date_to,
            limit=50,
        )
        phase2_timings["evidence"] = elapsed(t)
        return result

    def fetch_raw() -> list[dict]:
        t = time.perf_counter()
        if not depth_gte(intent.depth_needed, "raw"):
            phase2_timings["raw"] = "skipped (depth < raw)"
            return []
        result = raw_dal.get_raw(
            user_id=user_id,
            date_from=intent.date_from,
            date_to=intent.date_to,
        )
        phase2_timings["raw"] = elapsed(t)
        return result

    t2 = time.perf_counter()
    tasks = {
        "insights":  fetch_insights,
        "canonical": fetch_canonical,
        "evidence":  fetch_evidence,
        "raw":       fetch_raw,
    }

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        errors: dict[str, str] = {}
        for future in as_completed(futures):
            name = futures[future]
            try:
                retrieved[name] = future.result()
            except Exception as exc:
                errors[name] = str(exc)
                err(f"  Fetch '{name}' failed: {exc}")

    ok(f"All fetches done ({elapsed(t2)} wall-clock)")
    print()

    for layer in ["insights", "canonical", "evidence", "raw"]:
        timing = phase2_timings.get(layer, "?")
        rows = retrieved[layer]
        if "skipped" in timing:
            dim(f"  [{layer:<10}]  {timing}")
        elif layer in errors:
            err(f"  [{layer:<10}]  ERROR: {errors[layer]}")
        else:
            colour = GREEN if rows else YELLOW
            count_str = f"{len(rows)} row(s)"
            print(f"  {colour}[{layer:<10}]{RESET}  {count_str:<12}  {DIM}({timing}){RESET}")
            if rows:
                # Print a brief preview of each row
                for i, row in enumerate(rows[:3]):
                    preview = _row_preview(layer, row)
                    dim(f"              #{i+1}  {preview}")
                if len(rows) > 3:
                    dim(f"              … and {len(rows) - 3} more")

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 3 — Synthesizer  (LLM with write tools available)
    # ──────────────────────────────────────────────────────────────────────────
    header("PHASE 3", "Synthesizer  →  Final Answer")
    t3 = time.perf_counter()

    context_parts = []

    if retrieved["insights"]:
        context_parts.append("### Stored Insights (semantic search results)")
        for ins in retrieved["insights"]:
            context_parts.append(
                f"**{ins.get('title', '(no title)')}** [{ins.get('insight_type','')}]\n"
                f"{ins.get('content','')}"
            )

    if retrieved["canonical"]:
        context_parts.append("### Canonical Topic Summaries")
        for can in retrieved["canonical"]:
            context_parts.append(
                f"**{can.get('topic','')}** | {can.get('period','')} "
                f"({can.get('period_start','')} → {can.get('period_end','')})\n"
                f"{json.dumps(can.get('summary', {}), ensure_ascii=False)}"
            )

    if retrieved["evidence"]:
        context_parts.append("### Evidence Data Points")
        for ev in retrieved["evidence"]:
            val = ev.get("value") if ev.get("value") is not None else ev.get("value_text", "")
            context_parts.append(
                f"- {ev.get('data_type','')} = {val} {ev.get('unit','')}  "
                f"@ {ev.get('recorded_at','')[:10]}  "
                f"tags={ev.get('tags', [])}"
            )

    if retrieved["raw"]:
        context_parts.append("### Raw Source Data")
        for r in retrieved["raw"][:2]:
            context_parts.append(
                f"- source={r.get('source','')}  file={r.get('file_name','')}  "
                f"ingested={r.get('ingested_at','')[:10]}"
            )

    context_str = "\n\n".join(context_parts) if context_parts else "(No data found for this query)"

    synth_system = textwrap.dedent("""
        You are a personal health assistant with access to a user's health database.
        The retrieved context below was fetched specifically for the user's question.
        Base your answer on this context only — do not invent data.
        Cite specific values, dates, or insight titles when relevant.
        If the data is insufficient, say so clearly and suggest what additional data would help.
    """).strip()

    synth_user = f"""
User question: {user_question}

--- Retrieved Context ---
{context_str}
--- End of Context ---
    """.strip()

    dim("Calling OpenAI for synthesis…")
    dim(f"Context size: {len(context_str)} chars, {len(context_str.splitlines())} lines")

    try:
        synth_resp = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": synth_system},
                {"role": "user",   "content": synth_user},
            ],
            max_tokens=800,
        )
        answer = synth_resp.choices[0].message.content
        ok(f"Synthesis done ({elapsed(t3)})")

        print(f"\n{BOLD}{'─'*70}{RESET}")
        print(f"{BOLD}  FINAL ANSWER{RESET}")
        print(f"{BOLD}{'─'*70}{RESET}\n")
        for line in (answer or "").splitlines():
            print(f"  {line}")

    except Exception as e:
        err(f"Synthesis failed: {e}")
        raise

    # ──────────────────────────────────────────────────────────────────────────
    # Summary
    # ──────────────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}{'='*70}{RESET}")
    total = elapsed(time.perf_counter() - (t0 - time.perf_counter() + t0))
    print(f"{BOLD}  PIPELINE COMPLETE{RESET}")
    print(f"  Phase 0 (overview):   {elapsed(t0)}")
    print(f"  Phase 1 (intent):     {elapsed(t1)}")
    print(f"  Phase 2 (retrieval):  {elapsed(t2)}  (wall-clock, parallel)")
    print(f"  Phase 3 (synthesis):  {elapsed(t3)}")
    print(f"{BOLD}{'='*70}{RESET}\n")


# ─── Row preview helpers ──────────────────────────────────────────────────────

def _row_preview(layer: str, row: dict) -> str:
    if layer == "insights":
        return f"[{row.get('insight_type','')}] {row.get('title','')[:60]}"
    elif layer == "canonical":
        return (
            f"{row.get('topic','')} | {row.get('period','')} "
            f"{row.get('period_start','')[:10]} → {row.get('period_end','')[:10]}"
        )
    elif layer == "evidence":
        val = row.get("value") if row.get("value") is not None else row.get("value_text", "")
        return f"{row.get('data_type','')} = {val} {row.get('unit','')} @ {str(row.get('recorded_at',''))[:10]}"
    elif layer == "raw":
        return f"{row.get('source','')} | {row.get('file_name','')}"
    return str(row)[:80]


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "How has my sleep quality been this week?"
    run_pipeline(question)
