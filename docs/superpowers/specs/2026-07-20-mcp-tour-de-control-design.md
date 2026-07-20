# MCP Tour De Control — Design Spec

**Date:** 2026-07-20
**Status:** Approved

## Overview

MCP Tour De Control is a web platform that lets users write prompts, which an LLM converts into Python scripts that execute on cron schedules. Scripts use FastMCP Client to call local MCP servers. The LLM is invoked once at script generation time (and optionally at execution time for reasoning steps), minimizing token usage.

## Architecture

Monolith: FastAPI backend + React frontend + PostgreSQL, with APScheduler integrated in the backend process.

```
React UI (3 tabs) ←→ FastAPI Backend ←→ PostgreSQL
                         ↕
                    APScheduler (in-process)
                         ↕
                    Script Executor (subprocess)
                         ↕
                    MCP Servers (local, stdio subprocess)
```

### Core Flow

1. User writes a prompt in the UI and selects MCP servers to use
2. Backend connects to selected MCP servers, retrieves available tools via `list_tools()`
3. Backend calls the LLM with the prompt + tools context → LLM generates a Python script
4. Script is stored in PostgreSQL, cron job registered in APScheduler
5. On each cron tick, the script runs in an isolated subprocess
6. Script uses `fastmcp.Client` (stdio) to call MCP servers, optionally calls LLM for reasoning steps
7. Results stored in PostgreSQL → visible in the Reports tab

### Hybrid Scripts (Token Economy)

Scripts are "hybrid" — they only call the LLM when the output requires reasoning (summarization, analysis, classification). Data fetching and transformation is pure Python. The LLM at generation time decides which steps need reasoning.

The script reads `os.environ["LLM_API_KEY"]` — sensitive values are never hardcoded.

## Data Model

### config (singleton)

| Column       | Type      | Notes                |
|-------------|-----------|----------------------|
| id          | UUID PK   |                      |
| llm_provider| VARCHAR   | openai, anthropic... |
| llm_model   | VARCHAR   | gpt-4, claude-3...   |
| api_key     | VARCHAR   | encrypted at rest    |
| updated_at  | TIMESTAMP |                      |

### mcp_server

| Column    | Type      | Notes                          |
|-----------|-----------|--------------------------------|
| id        | UUID PK   |                                |
| name      | VARCHAR   |                                |
| transport | VARCHAR   | stdio or http                  |
| command   | VARCHAR   | e.g. python jira_mcp.py        |
| args      | JSONB     |                                |
| env       | JSONB     | environment variables          |
| url       | VARCHAR   | if http transport              |
| enabled   | BOOLEAN   |                                |
| created_at| TIMESTAMP |                                |

### prompt

| Column      | Type      | Notes                     |
|-------------|-----------|---------------------------|
| id          | UUID PK   |                           |
| name        | VARCHAR   |                           |
| description | TEXT      |                           |
| prompt_text | TEXT      |                           |
| cron_expr   | VARCHAR   | e.g. 0 8 * * *           |
| enabled     | BOOLEAN   |                           |
| created_at  | TIMESTAMP |                           |
| updated_at  | TIMESTAMP |                           |

### script

| Column    | Type      | Notes                              |
|-----------|-----------|------------------------------------|
| id        | UUID PK   |                                    |
| prompt_id | UUID FK   | → prompt                           |
| version   | INTEGER   |                                    |
| code      | TEXT      | generated Python code              |
| needs_llm | BOOLEAN   | flag set at generation time        |
| llm_steps | JSONB     | detail of steps requiring LLM      |
| created_at| TIMESTAMP |                                    |

### execution

| Column      | Type      | Notes                           |
|-------------|-----------|---------------------------------|
| id          | UUID PK   |                                 |
| script_id   | UUID FK   | → script                        |
| status      | VARCHAR   | running, success, failed, timeout|
| started_at  | TIMESTAMP |                                 |
| finished_at | TIMESTAMP |                                 |
| output      | TEXT      | raw result                      |
| llm_output  | TEXT      | LLM summary if applicable       |
| tokens_used | INTEGER   | 0 if no LLM call                |
| error       | TEXT      | if failed                       |
| duration_ms | INTEGER   |                                 |

### Relations

- `prompt` 1→N `script` (each regeneration creates a new version)
- `script` 1→N `execution` (each cron tick = one execution)

## API

```
PREFIX: /api/v1

Config:
  GET    /config
  PUT    /config

MCP Servers:
  GET    /mcp-servers
  POST   /mcp-servers
  GET    /mcp-servers/:id
  PUT    /mcp-servers/:id
  DELETE /mcp-servers/:id
  POST   /mcp-servers/:id/test       → tests connection, returns available tools

Prompts:
  GET    /prompts
  POST   /prompts                     → creates prompt + triggers script generation
  GET    /prompts/:id
  PUT    /prompts/:id
  DELETE /prompts/:id
  PUT    /prompts/:id/toggle          → enable/disable cron
  POST   /prompts/:id/regenerate      → regenerate script (new version)

Scripts:
  GET    /prompts/:id/scripts         → list script versions
  GET    /scripts/:id
  POST   /scripts/:id/run             → manual execution

Executions:
  GET    /executions                   → paginated, filterable
  GET    /executions/:id
  GET    /prompts/:id/executions
```

## Frontend

- **Stack:** React 18, TypeScript, Vite, React Router, TanStack Query, Tailwind CSS
- **3 tabs:** Prompts, Reports, Config
- **Prompts tab:** List prompts with cron status, create/edit form with cron picker, script preview with syntax highlighting, run/regenerate buttons
- **Reports tab:** Filterable table of executions with status badges, click for detail (output, logs, tokens, duration)
- **Config tab:** LLM provider/model/API key form, MCP server list with add/edit/delete/test

## Scheduler

APScheduler (AsyncIOScheduler) with SQLAlchemy PostgreSQL jobstore.

- `coalesce=True` — after downtime, execute once not N times
- `max_instances=1` — no parallel execution of the same prompt
- `misfire_grace_time=3600` — 1h grace for missed jobs
- Jobs persist in PostgreSQL — survive server restarts

## Script Execution

- Each execution runs in an isolated subprocess: `subprocess.run(["python", "-c", code], ...)`
- Timeout configurable per prompt (default 5 min)
- Sensitive values injected via environment variables
- Script outputs JSON: `{output, llm_used, tokens}`
- Backend parses stdout, stores result in `execution` table

## Script Generation

- Backend builds a system prompt containing: available MCP servers, their tools with signatures, instructions for hybrid execution
- LLM generates a Python script using `fastmcp.Client`
- Backend validates syntax via `ast.parse()`, retries once on failure
- Script stored with version number

## Error Handling

| Case                        | Behavior                                          |
|-----------------------------|---------------------------------------------------|
| LLM generation fails        | Prompt saved without script, user can retry        |
| Generated script invalid    | Re-prompt once with error, then flag as invalid    |
| Script timeout              | subprocess killed, execution status=timeout        |
| Script crash                | stderr captured, execution status=failed           |
| MCP server unreachable      | Script fails with ConnectionError, captured        |
| LLM API fails during exec   | Script catches error, execution status=failed      |
| Server restart              | APScheduler reloads jobs from PostgreSQL            |
| MCP server deleted           | Warning in UI, script fails at next run            |
| Prompt edited                | Script NOT auto-regenerated, user clicks Regenerate|
| New script version           | Cron switches to new version immediately            |
| API key changed              | Takes effect at next run (env var injection)        |

## Project Structure

```
MCP-Tour-De-Control/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models/          (SQLAlchemy)
│   │   ├── schemas/         (Pydantic)
│   │   ├── routers/         (FastAPI routes)
│   │   ├── services/        (llm, mcp, executor, scheduler)
│   │   └── utils/           (crypto, prompt_builder)
│   ├── alembic/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   └── lib/
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

## Deployment

Docker Compose with 3 services: postgres (16), backend (FastAPI on 8000), frontend (React on 3000).

## Tech Stack Summary

| Layer      | Technology                                    |
|------------|-----------------------------------------------|
| Frontend   | React 18, TypeScript, Vite, Tailwind, TanStack Query |
| Backend    | FastAPI, SQLAlchemy, Alembic, APScheduler     |
| MCP        | FastMCP (Client + Server)                     |
| Database   | PostgreSQL 16                                 |
| Deployment | Docker Compose                                |
| Logging    | structlog (JSON)                              |
