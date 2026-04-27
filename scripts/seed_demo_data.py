from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import get_db
from app.dal import canonical as canonical_dal
from app.dal import evidence as evidence_dal
from app.dal import insights as insights_dal
from app.dal import raw as raw_dal


def create_user() -> str:
    db = get_db()
    res = db.table("users").insert({}).execute()
    return res.data[0]["id"]


def seed_raw(user_id: str) -> dict[str, str]:
    wearable = raw_dal.create_raw(
        user_id=user_id,
        source="apple_health",
        source_type="json",
        file_name="apple_health_export_apr_2026.json",
        content={
            "devices": ["Apple Watch", "iPhone"],
            "period": "2026-04-01 to 2026-04-14",
            "metrics": ["sleep", "steps", "heart_rate", "weight"],
        },
        metadata={"source_label": "wearable_sync"},
    )
    lab = raw_dal.create_raw(
        user_id=user_id,
        source="lab_pdf",
        source_type="json",
        file_name="lab_panel_2026-04-05.pdf",
        content={
            "panel": "CBC + metabolic",
            "captured_on": "2026-04-05",
            "markers": ["WBC", "hemoglobin", "fasting_glucose"],
        },
        metadata={"source_label": "quarterly_lab"},
    )
    return {"wearable": wearable["id"], "lab": lab["id"]}


def seed_evidence(user_id: str, raw_ids: dict[str, str]) -> list[dict]:
    start = date(2026, 4, 1)
    rows: list[dict] = []

    sleep_hours = [6.6, 6.9, 7.1, 7.4, 7.2, 7.6, 7.8, 7.5, 7.7, 7.9, 7.4, 7.6, 7.8, 8.0]
    deep_sleep = [38, 41, 44, 47, 46, 51, 55, 49, 53, 57, 48, 50, 56, 58]
    resting_hr = [66, 65, 65, 64, 64, 63, 62, 63, 62, 61, 62, 61, 60, 60]
    steps = [6200, 7100, 8400, 9800, 10200, 11000, 12400, 9500, 8700, 11800, 13200, 12100, 13600, 14200]
    weight_kg = [74.8, 74.6, 74.5, 74.4]

    for offset in range(14):
        current = start + timedelta(days=offset)
        day = current.isoformat()
        rows.extend(
            [
                {
                    "user_id": user_id,
                    "raw_id": raw_ids["wearable"],
                    "data_type": "sleep_total_hours",
                    "recorded_at": f"{day}T07:00:00",
                    "value": sleep_hours[offset],
                    "unit": "hours",
                    "tags": ["sleep", "wearable"],
                    "metadata": {"sleep_window": "night"},
                },
                {
                    "user_id": user_id,
                    "raw_id": raw_ids["wearable"],
                    "data_type": "sleep_deep_minutes",
                    "recorded_at": f"{day}T07:00:00",
                    "value": float(deep_sleep[offset]),
                    "unit": "min",
                    "tags": ["sleep", "wearable"],
                    "metadata": {"sleep_window": "night"},
                },
                {
                    "user_id": user_id,
                    "raw_id": raw_ids["wearable"],
                    "data_type": "resting_heart_rate",
                    "recorded_at": f"{day}T07:30:00",
                    "value": float(resting_hr[offset]),
                    "unit": "bpm",
                    "tags": ["cardio", "wearable"],
                    "metadata": {"measurement_context": "morning"},
                },
                {
                    "user_id": user_id,
                    "raw_id": raw_ids["wearable"],
                    "data_type": "steps",
                    "recorded_at": f"{day}T20:00:00",
                    "value": float(steps[offset]),
                    "unit": "count",
                    "tags": ["exercise", "wearable"],
                    "metadata": {"aggregation": "daily_total"},
                },
            ]
        )

    for idx, value in enumerate(weight_kg):
        current = start + timedelta(days=idx * 4)
        rows.append(
            {
                "user_id": user_id,
                "raw_id": raw_ids["wearable"],
                "data_type": "weight",
                "recorded_at": f"{current.isoformat()}T08:00:00",
                "value": value,
                "unit": "kg",
                "tags": ["body_comp", "wearable"],
                "metadata": {"trend": "weekly"},
            }
        )

    rows.extend(
        [
            {
                "user_id": user_id,
                "raw_id": raw_ids["lab"],
                "data_type": "WBC",
                "recorded_at": "2026-04-05T10:00:00",
                "value": 6.2,
                "unit": "10^3/uL",
                "tags": ["lab", "blood_markers"],
                "metadata": {"panel": "CBC"},
            },
            {
                "user_id": user_id,
                "raw_id": raw_ids["lab"],
                "data_type": "hemoglobin",
                "recorded_at": "2026-04-05T10:00:00",
                "value": 14.1,
                "unit": "g/dL",
                "tags": ["lab", "blood_markers"],
                "metadata": {"panel": "CBC"},
            },
            {
                "user_id": user_id,
                "raw_id": raw_ids["lab"],
                "data_type": "fasting_glucose",
                "recorded_at": "2026-04-05T10:00:00",
                "value": 92.0,
                "unit": "mg/dL",
                "tags": ["lab", "metabolic"],
                "metadata": {"panel": "metabolic"},
            },
        ]
    )

    return evidence_dal.bulk_create_evidence(rows)


def seed_canonical(user_id: str) -> list[dict]:
    rows: list[dict] = []

    sleep_daily = [
        ("2026-04-12", 7.6, 50, 85),
        ("2026-04-13", 7.8, 56, 88),
        ("2026-04-14", 8.0, 58, 90),
    ]
    for day, total_hours, deep_minutes, score in sleep_daily:
        rows.append(
            canonical_dal.upsert_canonical(
                user_id=user_id,
                topic="sleep_quality",
                period="day",
                period_start=day,
                period_end=day,
                summary={
                    "total_sleep_hours": total_hours,
                    "deep_sleep_minutes": deep_minutes,
                    "sleep_score": score,
                    "trend": "improving",
                },
            )
        )

    rows.append(
        canonical_dal.upsert_canonical(
            user_id=user_id,
            topic="sleep_quality",
            period="week",
            period_start="2026-04-08",
            period_end="2026-04-14",
            summary={
                "avg_sleep_hours": 7.7,
                "avg_deep_sleep_minutes": 53,
                "sleep_score": 87,
                "note": "Sleep quantity and deep sleep improved versus the prior week.",
            },
        )
    )
    rows.append(
        canonical_dal.upsert_canonical(
            user_id=user_id,
            topic="exercise_daily",
            period="week",
            period_start="2026-04-08",
            period_end="2026-04-14",
            summary={
                "avg_steps": 11571,
                "days_over_10000_steps": 5,
                "active_minutes_estimate": 49,
                "note": "Activity volume increased in the second week of April.",
            },
        )
    )
    rows.append(
        canonical_dal.upsert_canonical(
            user_id=user_id,
            topic="blood_markers",
            period="month",
            period_start="2026-04-01",
            period_end="2026-04-30",
            summary={
                "WBC": 6.2,
                "hemoglobin": 14.1,
                "fasting_glucose": 92,
                "assessment": "All markers are within typical reference ranges.",
            },
        )
    )

    return rows


def seed_insights(user_id: str) -> list[dict]:
    return [
        insights_dal.create_insight(
            user_id=user_id,
            title="Sleep quality is improving",
            content=(
                "Sleep duration increased from roughly 6.8 hours in early April "
                "to nearly 8 hours by April 14, with deep sleep also trending up."
            ),
            insight_type="trend",
            topics=["sleep_quality"],
            date_range_start="2026-04-01",
            date_range_end="2026-04-14",
        ),
        insights_dal.create_insight(
            user_id=user_id,
            title="Higher activity lines up with lower resting heart rate",
            content=(
                "On days with 10k+ steps, resting heart rate was generally 61-63 bpm, "
                "slightly better than the first week of April."
            ),
            insight_type="correlation",
            topics=["exercise_daily", "cardio"],
            date_range_start="2026-04-01",
            date_range_end="2026-04-14",
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a demo user with mock health data.")
    parser.add_argument(
        "--user-id",
        help="Existing user id to seed. If omitted, a new user is created.",
    )
    args = parser.parse_args()

    user_id = args.user_id or create_user()
    raw_ids = seed_raw(user_id)
    evidence_rows = seed_evidence(user_id, raw_ids)
    canonical_rows = seed_canonical(user_id)
    insight_rows = seed_insights(user_id)

    print(f"user_id={user_id}")
    print(f"raw_rows={len(raw_ids)}")
    print(f"evidence_rows={len(evidence_rows)}")
    print(f"canonical_rows={len(canonical_rows)}")
    print(f"insight_rows={len(insight_rows)}")
    print("suggested_questions=")
    print("- How has my sleep been recently?")
    print("- What was my WBC count on April 5th 2026?")
    print("- Is my resting heart rate improving as my activity increases?")


if __name__ == "__main__":
    main()
