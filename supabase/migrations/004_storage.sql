-- Migration 004: Add storage support
-- Run in Supabase SQL Editor after creating the "health-files" Storage bucket.

-- raw_data: file_url is now stored in metadata->>'file_url' (no schema change needed).
-- This migration creates a helper view and index for easy file lookup.

-- Index to find raw records that have an associated file backup
create index if not exists raw_data_has_file_idx
    on raw_data ((metadata->>'file_url'))
    where metadata->>'file_url' is not null;

-- Convenience: which raw records have file backups?
create or replace view raw_data_with_files as
select
    id,
    user_id,
    source,
    source_type,
    file_name,
    metadata->>'file_url' as storage_path,
    ingested_at
from raw_data
where metadata->>'file_url' is not null;
