# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`AGENTS.md` is the authoritative reference for repository layout, the production server (Asterisk / AVA / nginx topology), and the SIPp 3.6.1 constraints. Read it before touching `sipp-stress/` or deploying. This file covers commands and the cross-file architecture; do not duplicate AGENTS.md content here.

## Commands

```bash
# Full stack
docker compose up --build          # backend runs `alembic upgrade head` then uvicorn

# Backend (from backend/, venv/ already exists)
venv/bin/uvicorn app.main:app --reload            # :8000, /health
PYTHONPATH=. venv/bin/alembic upgrade head        # PYTHONPATH is required (env.py imports app.models)
PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "..."
venv/bin/python -m pytest tests/ -v
venv/bin/python -m pytest tests/test_scheduler_service.py::test_name -v   # single test

# Frontend (from frontend/)
npm run dev      # :3000, proxies /api → localhost:8000
npm run build    # tsc -b && vite build — the type check
npm run lint     # oxlint

# sipp-stress (from sipp-stress/)
python3 -m pytest tests/          # pure parsing tests, no SIPp binary needed
```

Backend tests need a live Postgres at `localhost:5432` (`mcp`/`mcp_secret`) with a `mcp_control_test` database; `tests/conftest.py` creates and drops the tables per test. `pytest.ini` sets `asyncio_mode = auto`. There is no frontend test suite — lint + build are the checks.

Backend env (`backend/.env` or process env): `DATABASE_URL`, `ENCRYPTION_KEY` (Fernet, generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`), `DEFAULT_SCRIPT_TIMEOUT`, `SIPP_MCP_URL`.

## Architecture

### Prompt → script → execution (the core loop)

1. `POST /api/v1/prompts` (`routers/prompts.py`) requires a `Config` row with an `api_key`; for each selected MCP server it calls `McpService.get_server_tools()`, which opens a real FastMCP client connection and lists tools.
2. `utils/prompt_builder.build_generation_prompt()` renders those tools plus hard rules into a system prompt: use `fastmcp.Client`, read secrets from `LLM_API_KEY` / `MCP_API_KEY_<SERVER_NAME>`, wrap in `async main()`, and **print exactly one JSON line** `{"output", "llm_used", "tokens"}` as the last stdout line.
3. `LlmService.generate_script()` dispatches per provider (openai / anthropic / google — different SDKs, never mixed), strips markdown fences, `ast.parse()`-validates, retries once on `SyntaxError`, then sets `needs_llm` by string-matching `LLM_USAGE_MARKERS` in the generated code.
4. Scripts are immutable and versioned per prompt (`Script.version`); `POST /prompts/{id}/regenerate` appends `max(version)+1` rather than mutating. Nothing reads anything but the highest version.
5. `ScriptExecutor.run()` spawns `python -c <code>` as a subprocess with `os.environ` plus decrypted secrets, waits with `DEFAULT_SCRIPT_TIMEOUT`, and parses **the last stdout line** as JSON (falling back to raw stdout). Status is one of `running`/`success`/`failed`/`timeout` on the `Execution` row.

This is arbitrary code execution by design — there is no sandbox, and the subprocess inherits the backend's environment. The API has no auth of its own; nginx basic auth is the only gate.

### Scheduling

`scheduler_service` is a module-level singleton created at import time, backed by an APScheduler `SQLAlchemyJobStore` on a **sync** URL derived from `DATABASE_URL` (`+asyncpg` stripped); it falls back to an in-memory jobstore if the DB is unreachable, which is what makes tests importable. Job ids are `prompt_{uuid}`. Prompt CRUD keeps the scheduler in sync inline (create → `add_job`, cron change → `reschedule_job`, toggle → `pause_job`/`resume_job`, delete → `remove_job`), and `main.py`'s lifespan re-adds jobs for every enabled prompt with a cron on startup. Jobs run with `coalesce=True`, `max_instances=1`, `misfire_grace_time=3600`.

`main.py` lifespan also auto-registers (or URL-updates) an MCP server row named `sipp-stress` pointing at `SIPP_MCP_URL` — don't create it by hand.

### Chat

`POST /chat/conversations/{id}/messages` returns a `StreamingResponse` of SSE frames built by `_sse()` in `chat_service.py`; event names are `text`, `tool_call`, `tool_result`, `error`, `done`. Tool definitions come from every enabled MCP server, flattened into one namespace (`tool_name → server` map), with `_clean_schema()` stripping `default`/`additionalProperties`/`anyOf`/`title` because Gemini rejects them. History is capped at `MAX_HISTORY` messages and tool results at `MAX_TOOL_RESULT_LEN`. The system prompt is French and the assistant answers in French — preserve that.

### Stress Call

`StressTestService` talks to the sipp-stress MCP server over `SIPP_MCP_URL` (`start_test`/`stop_test`), stores the returned `remote_test_id`, and spawns an `asyncio` background polling task tracked in the module-level `_polling_tasks` dict that writes `StressTestMetrics` snapshots. Those tasks are in-process only: a backend restart loses them, leaving tests stuck in `running`.

## Conventions

- Business logic lives in `app/services/`; routers stay thin and declare `APIRouter(prefix="/api/v1/<resource>")`. Async SQLAlchemy 2.0 style, `structlog.get_logger()`, settings only via `app.config.settings`.
- One file per entity across `models/`, `schemas/`, `routers/`, `services/`. Every model must be exported from `app/models/__init__.py` or Alembic autogenerate misses it. Model changes require a migration.
- MCP tool dicts use the snake_case key `input_schema` (from the `McpToolInfo` schema), not the MCP wire name `inputSchema`.
- All frontend HTTP calls and shared TypeScript interfaces go in `frontend/src/lib/api.ts` — no ad-hoc `fetch` in components. Routes are declared in `src/App.tsx` under a single `AppShell` layout, one page per tab.
- `Config` and MCP server API keys are Fernet-encrypted (`utils/crypto.py`); the API must only ever expose `api_key_set: bool`, never the value.
- Conventional Commits (`feat(chat): ...`). Code, comments, docs and UI in English — the chat assistant's French output is the one exception.
- Design specs live in `docs/superpowers/specs/` and plans in `docs/superpowers/plans/`; check them before large changes.
