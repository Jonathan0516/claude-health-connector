-- Migration 005: Multi-user support
-- Run in Supabase SQL Editor.

-- ─────────────────────────────────────────────────────────────────────────────
-- Extend users table with display name
-- ─────────────────────────────────────────────────────────────────────────────
alter table users
    add column if not exists display_name text,
    add column if not exists email        text unique,
    add column if not exists updated_at   timestamptz default now();

-- Backfill existing user with a default display name
update users set display_name = 'Default User' where display_name is null;

-- ─────────────────────────────────────────────────────────────────────────────
-- Row Level Security (RLS)
-- With the service role key the server bypasses RLS, so this is
-- a safety net for future web/mobile clients using user-scoped JWT tokens.
-- ─────────────────────────────────────────────────────────────────────────────
alter table raw_data      enable row level security;
alter table evidence      enable row level security;
alter table canonical     enable row level security;
alter table insights      enable row level security;
alter table user_profile  enable row level security;
alter table user_states   enable row level security;

-- Service role (our MCP server) bypasses RLS — no policy needed for it.
-- Add policies here when adding a user-facing web client with anon/user JWTs.
