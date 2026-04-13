"""
Supabase Storage integration.

Bucket: health-files (private)
Path:   {user_id}/{year}/{source}/{filename}

Requires the bucket to be created in Supabase Dashboard first:
  Storage → New bucket → "health-files" → Private
"""

from __future__ import annotations

import os
from pathlib import Path
from app.database import get_db


BUCKET = "health-files"


def upload_file(
    user_id: str,
    file_path: str,
    source: str,
    file_name: str | None = None,
) -> str:
    """
    Upload a local file to Supabase Storage.

    Args:
        user_id:   Owner's UUID
        file_path: Absolute local path to the file
        source:    e.g. "lab_pdf" | "lab_json" | "apple_health" | "inbody"
        file_name: Override filename; defaults to basename of file_path

    Returns:
        storage_path: The bucket-relative path, e.g.
                      "{user_id}/2026/lab_pdf/blood_test.pdf"
                      Store this in raw_data.file_url.
    """
    db = get_db()
    path = Path(file_path)
    name = file_name or path.name
    year = __import__("datetime").date.today().year
    storage_path = f"{user_id}/{year}/{source}/{name}"

    with open(file_path, "rb") as f:
        data = f.read()

    mime = _guess_mime(path.suffix)
    db.storage.from_(BUCKET).upload(
        path=storage_path,
        file=data,
        file_options={"content-type": mime, "upsert": "true"},
    )
    return storage_path


def download_file(storage_path: str) -> bytes:
    """Download a file from Storage by its storage_path."""
    db = get_db()
    return db.storage.from_(BUCKET).download(storage_path)


def get_signed_url(storage_path: str, expires_in: int = 3600) -> str:
    """Get a temporary signed URL for accessing a private file."""
    db = get_db()
    res = db.storage.from_(BUCKET).create_signed_url(storage_path, expires_in)
    return res["signedURL"]


def _guess_mime(suffix: str) -> str:
    mapping = {
        ".pdf":  "application/pdf",
        ".json": "application/json",
        ".xml":  "application/xml",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png":  "image/png",
        ".csv":  "text/csv",
    }
    return mapping.get(suffix.lower(), "application/octet-stream")
