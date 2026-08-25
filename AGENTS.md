# AGENTS.md — MCP Tour De Control

Guidance for AI coding agents working in this repository. Assumes no prior knowledge of the project.

## Project Overview

MCP Tour De Control is a web platform for automating tasks through MCP (Model Context Protocol) servers:

1. A user writes a natural-language **prompt** in the UI and selects MCP servers.
2. The backend fetches the servers' tool lists and asks an LLM (OpenAI, Anthropic, or Google) to generate a **Python script** that uses `fastmcp.Client` to call those tools.
3. Scripts are versioned, stored in PostgreSQL, and executed on **cron schedules** (APScheduler, in-process) in subprocesses. Results land in an **Executions/Reports** view.
4. Scripts are "hybrid": they only call the LLM at runtime when reasoning is needed (secrets are injected via env vars, never hardcoded).

On top of that core loop there are three more features:

- **Stress Call**: SIP load testing. A dedicated MCP server (`sipp-stress/`) wraps the SIPp binary; the backend drives it through the MCP protocol and polls SIP/RTP metrics (ASR, PDD, CPS, jitter, MOS...).
- **Chat**: a conversational assistant (its system prompt is in French — it answers in French) that can call MCP tools live and generate scripts, streamed over SSE.
- **Activity**: director dashboard. One shared Drive folder is walked daily; every Google Doc and Sheet inside it is exported to text, diffed line-by-line against the previous run, and the daily added/removed counts feed a GitHub-style contribution grid. Only the latest text is stored, so history stays complete while storage stays bounded.

Authoritative design docs live in `docs/superpowers/specs/` and implementation plans in `docs/superpowers/plans/`. Read those before large changes.

## Repository Layout

Three independently buildable components plus a compose file:

```
├── backend/          FastAPI app (Python) — the control plane
│   ├── app/
│   │   ├── main.py         FastAPI entry, lifespan (scheduler start, cron restore, sipp-stress auto-registration)
│   │   ├── config.py       pydantic-settings: DATABASE_URL, ENCRYPTION_KEY, DEFAULT_SCRIPT_TIMEOUT, SIPP_MCP_URL
│   │   ├── database.py     async SQLAlchemy engine/session
│   │   ├── models/         SQLAlchemy models (one file per entity, all exported from models/__init__.py)
│   │   ├── schemas/        Pydantic schemas
│   │   ├── routers/        FastAPI routers, all prefixed /api/v1/<resource>
│   │   ├── services/       llm_service, mcp_service, script_executor, scheduler_service,
│   │   │                   stress_test_service, chat_service
│   │   └── utils/          crypto.py (Fernet), prompt_builder.py
│   ├── alembic/            migrations (env.py reads DATABASE_URL env var, imports app.models)
│   ├── tests/              pytest suite (needs a local Postgres, see below)
│   ├── test_mcp_server.py  standalone FastMCP server with 4 dummy tools for end-to-end testing
│   └── requirements.txt    pinned deps (no pyproject.toml)
├── frontend/         React SPA
│   ├── src/pages/          one file per tab: Prompts, Reports, StressCall, Chat, Activity, Config
│   ├── src/components/     grouped by feature (Chat/, Config/, Prompts/, Reports/, StressCall/, Layout/, ui/)
│   ├── src/lib/api.ts      ALL backend calls + shared TypeScript interfaces live here
│   └── vite.config.ts      dev server on :3000, proxies /api → http://localhost:8000
├── sipp-stress/      FastMCP server wrapping SIPp (separate deployable)
│   ├── mcp_server.py       tools: start_test, stop_test, get_status, get_metrics, get_rtp_stats,
│   │                       list_scenarios, list_tests — streamable-http on $MCP_PORT (default 9090)
│   ├── sipp_runner.py      spawns/manages SIPp subprocesses, results under /tmp/sipp
│   ├── metrics_parser.py   parses SIPp CSV dumps
│   ├── rtp_analyzer.py     RTP quality metrics
│   ├── media/              generate_pcap.sh + wav_to_pcap.py (build-time RTP pcap generation)
│   ├── scenarios/          SIPp XML scenarios (basic_call, short_call, cancel_call, reinvite_call, receiver)
│   └── tests/              parser unit tests (pure Python, no SIPp needed)
└── docker-compose.yml      postgres + backend + sipp-stress + frontend (all `restart: unless-stopped`)
```

## Tech Stack

| Layer      | Technology |
|------------|------------|
| Backend    | Python, FastAPI, SQLAlchemy 2 (async, asyncpg), Alembic, APScheduler 3 (SQLAlchemyJobStore persisted in Postgres), FastMCP client, structlog, cryptography (Fernet) |
| LLMs       | openai, anthropic, google-generativeai SDKs; provider/model/key stored in the singleton `config` row |
| Frontend   | React 19, TypeScript, Vite 8, Tailwind CSS 4, TanStack Query, react-router-dom 7, oxlint |
| sipp-stress| Python, FastMCP server (streamable-http), SIPp (`sip-tester` Debian package), sox/ffmpeg for media |
| Database   | PostgreSQL 16 |
| Deploy     | Docker Compose |

Runtime topology: browser → nginx (frontend, :80/:443, basic auth, proxies `/api/`) → backend (:8000) → Postgres; backend → sipp-stress MCP server (:9090, `network_mode: host` in compose, reached from the backend container via `host.docker.internal`). In dev: Vite on :3000 proxies `/api` to a locally-running uvicorn on :8000; CORS only allows `http://localhost:3000`.

## Build, Run, Test Commands

### Full stack (Docker)

```bash
docker compose up --build
```

The backend container runs `alembic upgrade head` then uvicorn automatically. The frontend container expects TLS certs in `./certs/` (gitignored) for port 443.

### Backend (local dev)

```bash
cd backend
python -m venv venv && venv/bin/pip install -r requirements.txt
# needs a reachable Postgres (docker compose up postgres) and a valid ENCRYPTION_KEY (Fernet key)
venv/bin/uvicorn app.main:app --reload          # http://localhost:8000, /health for liveness

# Migrations — PYTHONPATH must include the backend dir (env.py imports app.models):
PYTHONPATH=. venv/bin/alembic upgrade head
PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "describe change"
```

Config via env vars or `backend/.env` (see `backend/.env.example`): `DATABASE_URL`, `ENCRYPTION_KEY` (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`), `DEFAULT_SCRIPT_TIMEOUT` (default 300s), `SIPP_MCP_URL`.

**`alembic revision --autogenerate` gotcha:** in this repo it reliably proposes dropping `apscheduler_jobs` and `ix_chat_message_conversation_id` — both wrong, strip them from every generated migration before committing it. `apscheduler_jobs` belongs to APScheduler's runtime jobstore, not the app's declared models; dropping it destroys every persisted cron job. This has bitten three separate tasks — check the generated migration by hand every time.

### Backend tests

```bash
cd backend
venv/bin/python -m pytest tests/ -v
```

**Prerequisite:** a Postgres at `localhost:5432` (user `mcp` / password `mcp_secret`) with a database named `mcp_control_test`. `tests/conftest.py` creates all tables before each test and drops them after; `pytest.ini` sets `asyncio_mode = auto`. `test_crypto.py` sets its own `ENCRYPTION_KEY` before importing app modules.

### Frontend

```bash
cd frontend
npm ci
npm run dev      # vite dev server on :3000
npm run build    # tsc -b && vite build (type check is part of the build)
npm run lint     # oxlint (config: .oxlintrc.json, plugins react/typescript/oxc)
```

There is no frontend test suite — `npm run lint` and `npm run build` are the checks.

### sipp-stress

```bash
cd sipp-stress
python3 -m pytest tests/        # 7 tests, pure parsing logic, no SIPp binary required
python3 mcp_server.py           # running the server itself requires SIPp installed (use its Docker image)
```

**SIPp constraints** (the Docker image ships Debian `sip-tester` = SIPp 3.6.1):

- Only options valid in 3.6.1: use `-error_file` (not `-ef`), `-trace_rtt -rtt_freq 1` (no `-rtf`; the RTT file lands in the process CWD and is renamed to `uac_rtt.csv` by the runner), `-rate_interval 1s` (not `-rate_increase_interval`).
- `<pause milliseconds="[fieldN]"/>` is NOT substituted by 3.6.1 — scenarios use a bare `<pause/>` and the runner sets per-call duration via `-d call_duration`.
- Assigned-but-unused scenario variables (e.g. `assign_to="remote_sdp"` never referenced) are fatal in 3.6.1 — do not reintroduce dead `ereg` captures.
- `play_pcap_audio` needs real libpcap RTP captures; `media/wav_to_pcap.py` (stdlib) builds them from the sox-generated A-law WAVs at image build time.

**Port allocation on the prod host** (Asterisk has priority — SIPp must never overlap):

- SIPp signaling: UAC `5070`, UAS `5080` (Asterisk owns `5060`).
- SIPp RTP: UAS base `21000`, UAC base `26000` (~4 ports/call) — clear of Asterisk RTP `10000-20000`, AVA ExternalMedia `18080-18099`, ephemeral `32768+`.
- SIPp processes run under `nice -n 10` so Asterisk keeps CPU priority during tests.

## Production server

The stack is deployed at `46.225.115.154` (Hetzner, Ubuntu 26.04, 2 vCPU / 4 GB), repo at `/opt/mcp-tour-de-control`, SSH `root@46.225.115.154`. Deploy = `scp` changed files there + `docker compose build <svc> && docker compose up -d <svc>`.

The same host also runs (installed Aug 2026, NOT part of this repo):

- **Asterisk 22.5.2** (apt) — ARI on `127.0.0.1:8088` (user `ava`, password in `/root/.ava_ari_password`), SIP UDP `5060`, dialplan: ext `1000` and `service` in `[default]` → `[from-ai-agent]` → `Stasis(asterisk-ai-voice-agent)`. PJSIP endpoints: `sipp-local` (identify 127.0.0.1, for local SIPp tests), softphone ext `6001`.
- **AVA (Asterisk AI Voice Agent)** at `/opt/ava` (compose project `asterisk-ai-voice-agent`): `ai_engine` (health/metrics loopback-only `:15000`, AudioSocket `127.0.0.1:8090`) and `admin_ui`. The admin UI is bound to docker0 only (`172.17.0.1:3003`) and exposed through the main nginx at `https://tour.alcall.net:8443` (basic auth on the app shell, same `.htpasswd`; `/api/` skips basic auth and relies on AVA's JWT, because the SPA's `Authorization: Bearer` header would clobber the Basic credentials — linked as "AVA Admin ↗" in the main UI nav) — it is NOT publicly reachable on 3003. `local_ai_server` is stopped on purpose (cloud providers only, RAM budget).

## Conventions

- **Python**: async SQLAlchemy 2.0 style; routers declare `APIRouter(prefix="/api/v1/<resource>")`; business logic goes in `app/services/`, not in routers; logging via `structlog.get_logger()`; settings only through `app.config.settings`.
- **Models/schemas/routers/services are split per entity**, one file each, and every model must be exported from `app/models/__init__.py` (Alembic autogenerate depends on it).
- **Database changes** require an Alembic migration (`alembic revision --autogenerate`); never edit models without one.
- **TypeScript**: all HTTP calls and shared interfaces are centralized in `frontend/src/lib/api.ts` — add new endpoints there, not ad-hoc `fetch` in components. UI is a tab-based SPA (`src/App.tsx` routes). Build with `tsc -b` must stay clean.
- **Commits**: history follows Conventional Commits (`feat(chat): ...`, `fix(chat): ...`).
- **Language**: code, comments, docs and UI are in English. Exception: the chat assistant's system prompt (`chat_service.py`) is French and the assistant answers users in French — preserve that behavior.
- The project was built with a spec/plan workflow; when adding a feature, check `docs/superpowers/specs/` for the existing design docs first.

## Security Considerations

- **Secrets at rest**: the LLM API key (`config.api_key`) and MCP server API keys (`mcp_server.api_key`) are Fernet-encrypted with `ENCRYPTION_KEY` (`app/utils/crypto.py`). API reads only expose `api_key_set: bool`, never the value. Keep it that way.
- **Arbitrary code execution by design**: generated scripts run as `python -c <code>` subprocesses of the backend (`script_executor.py`), inheriting its environment plus decrypted secrets injected as `LLM_API_KEY` / `MCP_API_KEY_<SERVER_NAME>`. Anyone able to create prompts can execute arbitrary Python on the host. There is no sandbox — do not expose the API without authentication.
- **Document text is stored unencrypted** (`document_content.text`), unlike every other sensitive value in this database. Combined with `ScriptExecutor._build_env`'s `os.environ.copy()`, which hands every LLM-generated subprocess `DATABASE_URL` and `ENCRYPTION_KEY`, a generated script can read the full text of every tracked document. Arbitrary execution was already by design here, but the Activity feature widened what it reaches: the database used to hold parsed indicators, it now holds document bodies. **Deferred decision (2026-08-25):** either Fernet-encrypt `document_content.text`, or restrict the environment passed to generated scripts instead of copying it wholesale, or accept it knowingly. Not yet decided — raise it with the owner before the next feature touches either area.
- **Authentication**: the FastAPI backend itself has none; access control is nginx basic auth (`.htpasswd`) + TLS in the frontend container. The default Fernet key in `docker-compose.yml`/`backend/.env.example` is a placeholder — override `ENCRYPTION_KEY` in real deployments.
- `.env` files and `certs/` are gitignored; do not commit secrets.
- Script execution has a configurable timeout (`DEFAULT_SCRIPT_TIMEOUT`, default 300s); scheduler jobs use `coalesce=True`, `max_instances=1`, `misfire_grace_time=3600`.
