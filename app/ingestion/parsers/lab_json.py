"""
Lab JSON parser.

Accepts structured lab result JSON and converts it to evidence rows
ready for bulk insert.

Expected input schema
─────────────────────
{
  "lab_name":    "瑞金医院",          # optional
  "date":        "2026-04-01",        # required — ISO date of the test
  "patient":     {...},               # optional, ignored (no PII stored in evidence)
  "results": [
    {
      "name":      "WBC",             # required — becomes data_type
      "value":     6.2,               # numeric value (float/int), OR
      "value_text": "阳性",           # text value if non-numeric — use one or the other
      "unit":      "10^3/uL",         # optional
      "ref_range": "4.0-10.0",        # optional — stored in metadata
      "flag":      "H"                # optional — "H" | "L" | null
    },
    ...
  ]
}

The schema is intentionally loose:
- Extra keys in top-level or result items are preserved in metadata
- "name" is used as data_type verbatim — no remapping here
- Missing value + value_text → row is skipped with a warning
"""

from __future__ import annotations

import warnings
from typing import Any


class LabJsonParseError(ValueError):
    """Raised when the JSON structure is invalid."""


def parse(raw_json: dict) -> dict:
    """
    Parse a lab result JSON into a normalised ingest payload.

    Returns:
        {
          "document_date": "2026-04-01",
          "lab_name":      "瑞金医院",
          "rows": [
            {
              "data_type":  "WBC",
              "value":      6.2,
              "value_text": None,
              "unit":       "10^3/uL",
              "recorded_at": "2026-04-01T00:00:00",
              "metadata":   {"ref_range": "4.0-10.0", "flag": "H"}
            },
            ...
          ],
          "skipped": [...]   # items that couldn't be parsed
        }

    Raises:
        LabJsonParseError: if required fields are missing
    """
    _require(raw_json, "results", kind="list")
    _require(raw_json, "date", kind="str")

    document_date: str = raw_json["date"].strip()
    recorded_at_base = f"{document_date}T00:00:00"
    lab_name: str = raw_json.get("lab_name", "")

    rows: list[dict] = []
    skipped: list[dict] = []

    for item in raw_json["results"]:
        name = (item.get("name") or "").strip()
        if not name:
            skipped.append({"item": item, "reason": "missing 'name'"})
            continue

        numeric_val = _coerce_numeric(item.get("value"))
        text_val = item.get("value_text")

        if numeric_val is None and not text_val:
            skipped.append({"item": item, "reason": "no value or value_text"})
            continue

        metadata: dict[str, Any] = {}
        if item.get("ref_range"):
            metadata["ref_range"] = item["ref_range"]
        if item.get("flag"):
            metadata["flag"] = item["flag"]
        # preserve any extra keys
        known = {"name", "value", "value_text", "unit", "ref_range", "flag"}
        for k, v in item.items():
            if k not in known:
                metadata[k] = v

        rows.append({
            "data_type":   name,
            "value":       numeric_val,
            "value_text":  str(text_val) if text_val is not None else None,
            "unit":        item.get("unit"),
            "recorded_at": recorded_at_base,
            "metadata":    metadata,
        })

    if skipped:
        warnings.warn(
            f"lab_json parser skipped {len(skipped)} item(s): "
            + ", ".join(s["reason"] for s in skipped),
            stacklevel=2,
        )

    return {
        "document_date": document_date,
        "lab_name":      lab_name,
        "rows":          rows,
        "skipped":       skipped,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _require(obj: dict, key: str, kind: str) -> None:
    if key not in obj or obj[key] is None:
        raise LabJsonParseError(f"Missing required field: '{key}'")
    if kind == "list" and not isinstance(obj[key], list):
        raise LabJsonParseError(f"Field '{key}' must be a list")
    if kind == "str" and not isinstance(obj[key], str):
        raise LabJsonParseError(f"Field '{key}' must be a string")


def _coerce_numeric(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
