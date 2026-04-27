# Claude Health Connector

A personal health data backend that connects Claude to a structured, multi-layer health database via the Model Context Protocol (MCP).

## How it works

Claude acts as the intelligent layer — reading documents, reasoning over data, and deciding what to store. This server is a pure data layer: it exposes read/write tools over MCP and persists everything in Supabase.

```
Claude Desktop / Claude.ai
        │  MCP (Streamable HTTP)
        ▼
Health Connector (FastMCP server)
        │
        ▼
Supabase (PostgreSQL + Storage)
  ├── Raw documents       — original files, PDFs, images
  ├── Evidence            — individual time-stamped metric readings
  ├── Canonical           — auto-aggregated day/week/month summaries
  ├── Insights            — Claude-authored analysis and correlations
  └── Graph               — causal graph (biomarkers → symptoms → conditions)
```

**Ingestion flow:**
1. User shares a lab PDF, blood test image, or JSON export with Claude
2. Claude reads the file natively, extracts every metric, and calls the appropriate ingest tool
3. The pipeline stores the raw document, inserts evidence rows, and triggers a canonical cascade
4. Subsequent queries hit the canonical and graph layers first for fast trend analysis

**Auth:** Google OAuth 2.0 + PKCE → JWT. Claude.ai connects as a remote MCP server using a bearer token issued after login.

**Graph layer:** Entities (biomarkers, symptoms, conditions, interventions) and directed edges (causes, correlates\_with, resolves) are created when Claude reasons a connection during analysis — never auto-generated at ingest time. Cause-chain traversal uses a recursive Postgres RPC for efficiency.

## Quick Start

### 1. Prerequisites

- Python 3.10+
- A [Supabase](https://supabase.com) project
- Google OAuth credentials (for remote access)

### 2. Install

```bash
git clone https://github.com/your-org/claude-health-connector.git
cd claude-health-connector
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
```

Fill in `.env`:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
BASE_URL=https://your-domain.com/health-mcp
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
JWT_SECRET=<run: python -c "import secrets; print(secrets.token_hex(32))">
```

### 4. Run database migrations

Apply the SQL files in order via the Supabase dashboard or CLI:

```
supabase/migrations/001_init.sql
supabase/migrations/002_vector_search.sql
supabase/migrations/003_profile.sql
supabase/migrations/004_storage.sql
supabase/migrations/005_users.sql
supabase/migrations/006_graph.sql
```

### 5. Start the server

```bash
python mcp_server.py
```

The MCP endpoint is available at `{BASE_URL}/mcp`.

### 6. Connect Claude

In Claude.ai → Settings → Integrations, add a new MCP server:

```
URL: https://your-domain.com/health-mcp/mcp
Auth: OAuth (click Connect and log in with Google)
```

Claude will automatically load your user context and health data at the start of each conversation.

## MCP Tools

| Category | Tools |
|----------|-------|
| Users | `list_users`, `create_user` |
| Profile | `get_user_context`, `set_user_profile`, `set_user_state`, `end_user_state` |
| Read | `get_data_overview`, `query_insights`, `query_canonical`, `query_evidence`, `query_raw` |
| Graph | `add_entity`, `add_edge`, `query_cause_chain`, `get_entity_neighborhood`, `search_entities` |
| Write | `ingest_evidence`, `create_insight`, `upsert_canonical`, `store_document`, `ingest_lab_json` |

## Tech Stack

- **[FastMCP](https://github.com/jlowin/fastmcp)** — MCP server framework
- **[Supabase](https://supabase.com)** — PostgreSQL database + file storage
- **Google OAuth 2.0 + JWT** — authentication
- **Next.js** — web dashboard (`/web`)
