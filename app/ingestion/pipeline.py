"""
Unified ingestion pipeline.

Single entry point for all file types. Orchestrates:
  1. Upload original file to Supabase Storage (optional, skipped if no file_path)
  2. Store raw record (with file_url reference)
  3. Bulk-insert evidence rows
  4. Auto-trigger day-level canonical cascade

Usage patterns
──────────────

A) Claude reads a PDF/image natively, extracts values, then calls the MCP tool:
   → pipeline.ingest_document(user_id, document_date, source, document_type,
                              summary, tags, values, file_path=None)
     (file_path is optional; pass it if the user has a local copy to back up)

B) Structured lab JSON (Claude passes the parsed dict to the MCP tool):
   → pipeline.ingest_lab_json(user_id, raw_json, file_path=None)
     Internally calls parsers.lab_json.parse(), then ingest_document().
"""

from __future__ import annotations

import os
from typing import Any

from app.dal import raw as raw_dal
from app.dal import evidence as evidence_dal
from app.ingestion import cascade
from app.ingestion.parsers import lab_json as lab_json_parser


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def ingest_document(
    user_id: str,
    document_date: str,
    source: str,
    document_type: str,
    summary: str,
    tags: list[str],
    values: list[dict],
    file_path: str | None = None,
    file_name: str | None = None,
) -> dict:
    """
    Store a parsed health document.

    Args:
        user_id:       Owner UUID
        document_date: ISO date "YYYY-MM-DD" from the document
        source:        "lab_pdf" | "lab_json" | "apple_health" | "inbody" | "manual"
        document_type: "blood_test" | "body_composition" | "sleep_report" | ...
        summary:       One-two sentence summary of findings
        tags:          Category tags e.g. ["lab", "blood"]
        values:        List of extracted metrics:
                       [{data_type, value, value_text, unit, recorded_at,
                         ref_range (opt), flag (opt)}]
        file_path:     Local path to original file — uploaded to Storage if provided
        file_name:     Override filename for storage path

    Returns:
        {raw_id, evidence_count, cascaded_canonicals, storage_path, next_steps}
    """
    storage_path = _maybe_upload(user_id, file_path, source, file_name)

    raw_row = raw_dal.create_raw(
        user_id=user_id,
        source=source,
        source_type=document_type,
        file_name=file_name or (os.path.basename(file_path) if file_path else None),
        content={
            "document_date": document_date,
            "document_type": document_type,
            "summary":       summary,
            "tags":          tags,
            "values":        values,
        },
        metadata={"file_url": storage_path} if storage_path else {},
    )
    raw_id = raw_row["id"]

    evidence_rows_to_insert = [
        {
            "user_id":    user_id,
            "raw_id":     raw_id,
            "data_type":  v["data_type"],
            "value":      v.get("value"),
            "value_text": v.get("value_text"),
            "unit":       v.get("unit"),
            "recorded_at": v["recorded_at"],
            "tags":       tags,
            "metadata": {
                k: v[k] for k in ("ref_range", "flag") if v.get(k) is not None
            },
        }
        for v in values
    ]
    inserted = evidence_dal.bulk_create_evidence(evidence_rows_to_insert)

    cascaded = cascade.trigger(user_id, inserted)

    return {
        "raw_id":               raw_id,
        "storage_path":         storage_path,
        "evidence_count":       len(inserted),
        "cascaded_canonicals":  [c.get("topic") + " @ " + c.get("period_start", "")
                                  for c in cascaded],
        "extracted_types":      [v["data_type"] for v in values],
        "next_steps": (
            "Day-level canonicals auto-updated. "
            "Call create_insight() if there are notable findings, "
            "or upsert_canonical() for a richer topic summary."
        ),
    }


def ingest_lab_json(
    user_id: str,
    raw_json: dict,
    file_path: str | None = None,
    file_name: str | None = None,
    extra_tags: list[str] | None = None,
) -> dict:
    """
    Parse and ingest a structured lab result JSON.

    Args:
        user_id:    Owner UUID
        raw_json:   Lab JSON dict (see parsers/lab_json.py for schema)
        file_path:  Optional local path to the original .json file for backup
        file_name:  Override filename
        extra_tags: Additional tags to merge with ["lab"] default

    Returns:
        Same as ingest_document(), plus "skipped" count from parser.
    """
    parsed = lab_json_parser.parse(raw_json)

    tags = list({"lab"} | set(extra_tags or []))

    # Convert parser rows → values format expected by ingest_document
    values = [
        {
            "data_type":   row["data_type"],
            "value":       row["value"],
            "value_text":  row["value_text"],
            "unit":        row["unit"],
            "recorded_at": row["recorded_at"],
            **({k: row["metadata"][k] for k in ("ref_range", "flag")
                if k in row["metadata"]}),
        }
        for row in parsed["rows"]
    ]

    summary_parts = [f"Lab results from {parsed['document_date']}"]
    if parsed["lab_name"]:
        summary_parts.append(f"({parsed['lab_name']})")
    summary_parts.append(f"{len(values)} metrics parsed.")
    if parsed["skipped"]:
        summary_parts.append(f"{len(parsed['skipped'])} items skipped.")

    result = ingest_document(
        user_id=user_id,
        document_date=parsed["document_date"],
        source="lab_json",
        document_type="blood_test",
        summary=" ".join(summary_parts),
        tags=tags,
        values=values,
        file_path=file_path,
        file_name=file_name,
    )
    result["skipped_count"] = len(parsed["skipped"])
    result["skipped"] = parsed["skipped"]
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _maybe_upload(
    user_id: str,
    file_path: str | None,
    source: str,
    file_name: str | None,
) -> str | None:
    """Upload to Storage if a local file_path is provided. Returns storage_path or None."""
    if not file_path:
        return None
    try:
        from app.ingestion import storage
        return storage.upload_file(
            user_id=user_id,
            file_path=file_path,
            source=source,
            file_name=file_name,
        )
    except Exception as exc:
        # Storage upload failure is non-fatal — log and continue
        import warnings
        warnings.warn(f"Storage upload failed (continuing without backup): {exc}")
        return None
