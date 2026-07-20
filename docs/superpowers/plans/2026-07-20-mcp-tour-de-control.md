# MCP Tour De Control — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a web platform where users write prompts that an LLM converts into Python scripts, which execute on cron schedules against local MCP servers.

**Architecture:** FastAPI monolith with APScheduler in-process, React frontend with 3 tabs (Prompts, Reports, Config), PostgreSQL for persistence. Scripts run in isolated subprocesses using `fastmcp.Client` to call local MCP servers via stdio.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (async), Alembic, APScheduler 3.x, FastMCP, structlog | React 18, TypeScript, Vite, Tailwind CSS 4, TanStack Query, React Router 7 | PostgreSQL 16, Docker Compose

## Global Constraints

- Python 3.12+, Node 20+
- All backend async (asyncpg, async SQLAlchemy)
- API prefix: `/api/v1`
- All IDs are UUIDs
- No authentication (mono-user)
- API keys encrypted at rest in database (Fernet symmetric encryption)
- Scripts execute in isolated subprocesses with 5 min default timeout
- Sensitive values passed to subprocesses via environment variables, never hardcoded

---

### Task 1: Backend project scaffold + database models + migrations

**Files:**
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/config.py`
- Create: `backend/app/database.py`
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/config.py`
- Create: `backend/app/models/mcp_server.py`
- Create: `backend/app/models/prompt.py`
- Create: `backend/app/models/script.py`
- Create: `backend/app/models/execution.py`
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/routers/__init__.py`
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/utils/__init__.py`
- Create: `backend/requirements.txt`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/.gitkeep`
- Create: `docker-compose.yml`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_models.py`

**Interfaces:**
- Produces: SQLAlchemy models `Config`, `McpServer`, `Prompt`, `Script`, `Execution` importable from `app.models`
- Produces: `get_async_session()` async generator from `app.database`
- Produces: `settings` singleton from `app.config` with `DATABASE_URL`, `ENCRYPTION_KEY`

- [ ] **Step 1: Create `backend/requirements.txt`**

```
fastapi==0.115.12
uvicorn[standard]==0.34.3
sqlalchemy[asyncio]==2.0.41
asyncpg==0.31.0
alembic==1.16.2
apscheduler==3.11.0
fastmcp>=2.0.0
httpx==0.28.1
openai==1.86.0
anthropic==0.52.0
cryptography==45.0.3
structlog==25.4.0
pydantic==2.11.3
pydantic-settings==2.9.1
python-dotenv==1.1.0
pytest==8.4.1
pytest-asyncio==1.0.0
```

- [ ] **Step 2: Create `backend/app/config.py`**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control"
    ENCRYPTION_KEY: str = "generate-a-fernet-key-here"
    DEFAULT_SCRIPT_TIMEOUT: int = 300

    model_config = {"env_file": ".env"}


settings = Settings()
```

- [ ] **Step 3: Create `backend/app/database.py`**

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
```

- [ ] **Step 4: Create all SQLAlchemy models**

`backend/app/models/config.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Config(Base):
    __tablename__ = "config"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    llm_provider: Mapped[str] = mapped_column(String(50), default="openai")
    llm_model: Mapped[str] = mapped_column(String(100), default="gpt-4")
    api_key: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
```

`backend/app/models/mcp_server.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.config import Base


class McpServer(Base):
    __tablename__ = "mcp_server"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    transport: Mapped[str] = mapped_column(String(10))  # "stdio" or "http"
    command: Mapped[str | None] = mapped_column(String(500), nullable=True)
    args: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    env: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
```

`backend/app/models/prompt.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base


class Prompt(Base):
    __tablename__ = "prompt"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_text: Mapped[str] = mapped_column(Text)
    cron_expr: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    scripts: Mapped[list["Script"]] = relationship(back_populates="prompt", cascade="all, delete-orphan")
```

`backend/app/models/script.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, Text, Integer, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base


class Script(Base):
    __tablename__ = "script"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prompt.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(Text)
    needs_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_steps: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    prompt: Mapped["Prompt"] = relationship(back_populates="scripts")
    executions: Mapped[list["Execution"]] = relationship(back_populates="script", cascade="all, delete-orphan")
```

`backend/app/models/execution.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base


class Execution(Base):
    __tablename__ = "execution"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    script_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("script.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20))  # running, success, failed, timeout
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    script: Mapped["Script"] = relationship(back_populates="executions")
```

`backend/app/models/__init__.py`:
```python
from app.models.config import Base, Config
from app.models.mcp_server import McpServer
from app.models.prompt import Prompt
from app.models.script import Script
from app.models.execution import Execution

__all__ = ["Base", "Config", "McpServer", "Prompt", "Script", "Execution"]
```

- [ ] **Step 5: Create `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: mcp_control
      POSTGRES_USER: mcp
      POSTGRES_PASSWORD: mcp_secret
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

- [ ] **Step 6: Start PostgreSQL and set up Alembic**

```bash
docker-compose up -d postgres
```

`backend/alembic.ini`:
```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control

[loggers]
keys = root

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

`backend/alembic/env.py`:
```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(config.get_main_option("sqlalchemy.url"))
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`backend/alembic/script.py.mako`:
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

Run:
```bash
cd backend && alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

- [ ] **Step 7: Create minimal `backend/app/main.py`**

```python
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting MCP Tour De Control")
    yield
    log.info("Shutting down MCP Tour De Control")


app = FastAPI(title="MCP Tour De Control", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 8: Write and run model tests**

`backend/tests/conftest.py`:
```python
import asyncio
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base

TEST_DATABASE_URL = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control_test"
engine = create_async_engine(TEST_DATABASE_URL)
test_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    async with test_session() as s:
        yield s
```

`backend/tests/test_models.py`:
```python
import pytest
from app.models import Config, McpServer, Prompt, Script, Execution


@pytest.mark.asyncio
async def test_create_config(session):
    config = Config(llm_provider="openai", llm_model="gpt-4", api_key="test-key")
    session.add(config)
    await session.commit()
    await session.refresh(config)
    assert config.id is not None
    assert config.llm_provider == "openai"


@pytest.mark.asyncio
async def test_create_mcp_server(session):
    server = McpServer(name="test-server", transport="stdio", command="python", args=["server.py"])
    session.add(server)
    await session.commit()
    await session.refresh(server)
    assert server.id is not None
    assert server.enabled is True


@pytest.mark.asyncio
async def test_create_prompt_with_script(session):
    prompt = Prompt(name="Test Prompt", prompt_text="Do something", cron_expr="0 8 * * *")
    session.add(prompt)
    await session.commit()
    await session.refresh(prompt)

    script = Script(prompt_id=prompt.id, version=1, code="print('hello')", needs_llm=False)
    session.add(script)
    await session.commit()
    await session.refresh(script)
    assert script.prompt_id == prompt.id


@pytest.mark.asyncio
async def test_create_execution(session):
    prompt = Prompt(name="Test", prompt_text="Test", cron_expr="0 * * * *")
    session.add(prompt)
    await session.commit()

    script = Script(prompt_id=prompt.id, version=1, code="pass", needs_llm=False)
    session.add(script)
    await session.commit()

    execution = Execution(script_id=script.id, status="success", output="done", tokens_used=0, duration_ms=100)
    session.add(execution)
    await session.commit()
    await session.refresh(execution)
    assert execution.status == "success"
    assert execution.tokens_used == 0
```

Create test DB, then run:
```bash
docker-compose exec postgres psql -U mcp -c "CREATE DATABASE mcp_control_test;"
cd backend && python -m pytest tests/test_models.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/ docker-compose.yml
git commit -m "feat: backend scaffold with database models, migrations, and tests"
```

---

### Task 2: Pydantic schemas + utility modules

**Files:**
- Create: `backend/app/schemas/config.py`
- Create: `backend/app/schemas/mcp_server.py`
- Create: `backend/app/schemas/prompt.py`
- Create: `backend/app/schemas/script.py`
- Create: `backend/app/schemas/execution.py`
- Create: `backend/app/utils/crypto.py`
- Create: `backend/app/utils/prompt_builder.py`
- Create: `backend/app/utils/__init__.py`
- Create: `backend/tests/test_crypto.py`
- Create: `backend/tests/test_prompt_builder.py`

**Interfaces:**
- Consumes: nothing (standalone)
- Produces: Pydantic schemas `ConfigRead`, `ConfigUpdate`, `McpServerCreate`, `McpServerRead`, `McpServerUpdate`, `PromptCreate`, `PromptRead`, `PromptUpdate`, `ScriptRead`, `ExecutionRead`
- Produces: `encrypt_value(plaintext: str) -> str`, `decrypt_value(ciphertext: str) -> str` from `app.utils.crypto`
- Produces: `build_generation_prompt(user_prompt: str, mcp_servers: list[dict]) -> str` from `app.utils.prompt_builder`

- [ ] **Step 1: Write failing tests for crypto**

`backend/tests/test_crypto.py`:
```python
import os
import pytest

os.environ["ENCRYPTION_KEY"] = "dGVzdC1rZXktMzItYnl0ZXMtbG9uZy4uLi4="  # test key

from app.utils.crypto import encrypt_value, decrypt_value, generate_key


def test_encrypt_decrypt_roundtrip():
    original = "sk-test-api-key-12345"
    encrypted = encrypt_value(original)
    assert encrypted != original
    decrypted = decrypt_value(encrypted)
    assert decrypted == original


def test_encrypt_produces_different_ciphertexts():
    value = "same-value"
    a = encrypt_value(value)
    b = encrypt_value(value)
    assert a != b  # Fernet uses random IV


def test_generate_key_returns_valid_key():
    key = generate_key()
    assert isinstance(key, str)
    assert len(key) > 20
```

- [ ] **Step 2: Run tests — expect FAIL (module not found)**

```bash
cd backend && python -m pytest tests/test_crypto.py -v
```

- [ ] **Step 3: Implement crypto utility**

`backend/app/utils/crypto.py`:
```python
from cryptography.fernet import Fernet

from app.config import settings


def _get_fernet() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def generate_key() -> str:
    return Fernet.generate_key().decode()
```

- [ ] **Step 4: Run crypto tests — expect PASS**

```bash
cd backend && python -m pytest tests/test_crypto.py -v
```

- [ ] **Step 5: Write failing tests for prompt_builder**

`backend/tests/test_prompt_builder.py`:
```python
from app.utils.prompt_builder import build_generation_prompt


def test_build_prompt_includes_user_prompt():
    result = build_generation_prompt("Fetch open Jira tickets", [])
    assert "Fetch open Jira tickets" in result


def test_build_prompt_includes_mcp_server_tools():
    servers = [
        {
            "name": "jira-server",
            "transport": "stdio",
            "command": "python",
            "args": ["jira_mcp.py"],
            "tools": [
                {"name": "get_tickets", "description": "Get tickets", "inputSchema": {"properties": {"status": {"type": "string"}}}}
            ],
        }
    ]
    result = build_generation_prompt("Fetch tickets", servers)
    assert "jira-server" in result
    assert "get_tickets" in result


def test_build_prompt_includes_hybrid_instructions():
    result = build_generation_prompt("Summarize data", [])
    assert "os.environ" in result
    assert "LLM_API_KEY" in result
```

- [ ] **Step 6: Run tests — expect FAIL**

```bash
cd backend && python -m pytest tests/test_prompt_builder.py -v
```

- [ ] **Step 7: Implement prompt_builder**

`backend/app/utils/prompt_builder.py`:
```python
import json


def build_generation_prompt(user_prompt: str, mcp_servers: list[dict]) -> str:
    servers_section = ""
    if mcp_servers:
        for server in mcp_servers:
            servers_section += f"\n### {server['name']} (transport: {server['transport']})\n"
            if server["transport"] == "stdio":
                servers_section += f"Command: {server['command']} {' '.join(server.get('args', []))}\n"
            else:
                servers_section += f"URL: {server.get('url', 'N/A')}\n"
            if server.get("tools"):
                servers_section += "Tools:\n"
                for tool in server["tools"]:
                    schema_str = json.dumps(tool.get("inputSchema", {}), indent=2)
                    servers_section += f"- `{tool['name']}`: {tool.get('description', '')} — input: {schema_str}\n"

    return f"""You are a Python script generator for MCP Tour De Control.

Generate a Python script that accomplishes the following task:
{user_prompt}

## Available MCP Servers
{servers_section if servers_section else "No MCP servers configured."}

## Rules

1. Use `fastmcp.Client` to connect to MCP servers. For stdio transport:
   ```python
   from fastmcp import Client
   async with Client("stdio", command="<command>", args=[...]) as client:
       result = await client.call_tool("<tool_name>", {{"arg": "value"}})
   ```

2. If a step requires reasoning (summarization, analysis, classification), use the LLM API:
   ```python
   import os
   from openai import OpenAI
   llm = OpenAI(api_key=os.environ["LLM_API_KEY"])
   ```
   Read the provider from `os.environ["LLM_PROVIDER"]` and model from `os.environ["LLM_MODEL"]`.

3. For steps that produce deterministic output (filtering, formatting, counting), use pure Python.

4. The script MUST print a single JSON line to stdout at the end:
   ```python
   import json
   print(json.dumps({{"output": "<result>", "llm_used": True/False, "tokens": <int>}}))
   ```

5. Wrap everything in an async main() and call asyncio.run(main()).

6. Handle errors gracefully — catch exceptions and include them in the output JSON.

Generate ONLY the Python code, no markdown fences, no explanation."""
```

- [ ] **Step 8: Run tests — expect PASS**

```bash
cd backend && python -m pytest tests/test_prompt_builder.py -v
```

- [ ] **Step 9: Create all Pydantic schemas**

`backend/app/schemas/config.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class ConfigRead(BaseModel):
    id: uuid.UUID
    llm_provider: str
    llm_model: str
    api_key_set: bool  # never expose the key, just whether it's set
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConfigUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    api_key: str | None = None  # plaintext, will be encrypted before storage
```

`backend/app/schemas/mcp_server.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class McpServerCreate(BaseModel):
    name: str
    transport: str  # "stdio" or "http"
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    enabled: bool = True


class McpServerRead(BaseModel):
    id: uuid.UUID
    name: str
    transport: str
    command: str | None
    args: list[str] | None
    env: dict[str, str] | None
    url: str | None
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class McpServerUpdate(BaseModel):
    name: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    enabled: bool | None = None


class McpToolInfo(BaseModel):
    name: str
    description: str | None = None
    input_schema: dict | None = None


class McpTestResult(BaseModel):
    success: bool
    tools: list[McpToolInfo] = []
    error: str | None = None
```

`backend/app/schemas/prompt.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class PromptCreate(BaseModel):
    name: str
    description: str | None = None
    prompt_text: str
    cron_expr: str | None = None
    enabled: bool = True
    mcp_server_ids: list[uuid.UUID]  # which servers to use for script generation


class PromptRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    prompt_text: str
    cron_expr: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    latest_script_version: int | None = None
    needs_llm: bool | None = None

    model_config = {"from_attributes": True}


class PromptUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    prompt_text: str | None = None
    cron_expr: str | None = None
```

`backend/app/schemas/script.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class ScriptRead(BaseModel):
    id: uuid.UUID
    prompt_id: uuid.UUID
    version: int
    code: str
    needs_llm: bool
    llm_steps: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
```

`backend/app/schemas/execution.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class ExecutionRead(BaseModel):
    id: uuid.UUID
    script_id: uuid.UUID
    status: str
    started_at: datetime
    finished_at: datetime | None
    output: str | None
    llm_output: str | None
    tokens_used: int
    error: str | None
    duration_ms: int | None
    # Joined fields for convenience
    prompt_name: str | None = None
    script_version: int | None = None

    model_config = {"from_attributes": True}


class ExecutionListParams(BaseModel):
    status: str | None = None
    prompt_id: uuid.UUID | None = None
    limit: int = 50
    offset: int = 0
```

`backend/app/schemas/__init__.py`:
```python
from app.schemas.config import ConfigRead, ConfigUpdate
from app.schemas.mcp_server import McpServerCreate, McpServerRead, McpServerUpdate, McpTestResult, McpToolInfo
from app.schemas.prompt import PromptCreate, PromptRead, PromptUpdate
from app.schemas.script import ScriptRead
from app.schemas.execution import ExecutionRead, ExecutionListParams

__all__ = [
    "ConfigRead", "ConfigUpdate",
    "McpServerCreate", "McpServerRead", "McpServerUpdate", "McpTestResult", "McpToolInfo",
    "PromptCreate", "PromptRead", "PromptUpdate",
    "ScriptRead",
    "ExecutionRead", "ExecutionListParams",
]
```

- [ ] **Step 10: Commit**

```bash
git add backend/app/schemas/ backend/app/utils/ backend/tests/test_crypto.py backend/tests/test_prompt_builder.py
git commit -m "feat: add Pydantic schemas, crypto utility, and prompt builder"
```

---

### Task 3: Config & MCP Servers API routes

**Files:**
- Create: `backend/app/routers/config.py`
- Create: `backend/app/routers/mcp_servers.py`
- Create: `backend/app/services/mcp_service.py`
- Modify: `backend/app/main.py` — register routers
- Create: `backend/tests/test_api_config.py`
- Create: `backend/tests/test_api_mcp_servers.py`

**Interfaces:**
- Consumes: `Config` model, `McpServer` model, `get_async_session()`, schemas from Task 2, `encrypt_value()`/`decrypt_value()` from Task 2
- Produces: `GET/PUT /api/v1/config` endpoints
- Produces: `CRUD + POST test /api/v1/mcp-servers` endpoints
- Produces: `McpService.test_connection(server: McpServer) -> McpTestResult` from `app.services.mcp_service`

- [ ] **Step 1: Write failing test for config API**

`backend/tests/test_api_config.py`:
```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_get_config_returns_default():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "llm_provider" in data
    assert "api_key_set" in data
    assert "api_key" not in data  # key must never be exposed


@pytest.mark.asyncio
async def test_update_config():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/api/v1/config", json={"llm_provider": "anthropic", "llm_model": "claude-3"})
    assert resp.status_code == 200
    assert resp.json()["llm_provider"] == "anthropic"
```

- [ ] **Step 2: Run test — expect FAIL (404)**

```bash
cd backend && python -m pytest tests/test_api_config.py -v
```

- [ ] **Step 3: Implement config router**

`backend/app/routers/config.py`:
```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Config
from app.schemas import ConfigRead, ConfigUpdate
from app.utils.crypto import encrypt_value

router = APIRouter(prefix="/api/v1/config", tags=["config"])


async def _get_or_create_config(session: AsyncSession) -> Config:
    result = await session.execute(select(Config).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        config = Config()
        session.add(config)
        await session.commit()
        await session.refresh(config)
    return config


@router.get("", response_model=ConfigRead)
async def get_config(session: AsyncSession = Depends(get_async_session)):
    config = await _get_or_create_config(session)
    return ConfigRead(
        id=config.id,
        llm_provider=config.llm_provider,
        llm_model=config.llm_model,
        api_key_set=bool(config.api_key),
        updated_at=config.updated_at,
    )


@router.put("", response_model=ConfigRead)
async def update_config(data: ConfigUpdate, session: AsyncSession = Depends(get_async_session)):
    config = await _get_or_create_config(session)
    if data.llm_provider is not None:
        config.llm_provider = data.llm_provider
    if data.llm_model is not None:
        config.llm_model = data.llm_model
    if data.api_key is not None:
        config.api_key = encrypt_value(data.api_key)
    await session.commit()
    await session.refresh(config)
    return ConfigRead(
        id=config.id,
        llm_provider=config.llm_provider,
        llm_model=config.llm_model,
        api_key_set=bool(config.api_key),
        updated_at=config.updated_at,
    )
```

- [ ] **Step 4: Implement MCP service**

`backend/app/services/mcp_service.py`:
```python
import structlog
from fastmcp import Client

from app.models import McpServer
from app.schemas import McpTestResult, McpToolInfo

log = structlog.get_logger()


class McpService:
    @staticmethod
    async def test_connection(server: McpServer) -> McpTestResult:
        try:
            if server.transport == "stdio":
                async with Client("stdio", command=server.command, args=server.args or []) as client:
                    tools = await client.list_tools()
                    return McpTestResult(
                        success=True,
                        tools=[
                            McpToolInfo(
                                name=t.name,
                                description=t.description,
                                input_schema=t.inputSchema if hasattr(t, "inputSchema") else None,
                            )
                            for t in tools
                        ],
                    )
            elif server.transport == "http":
                async with Client(server.url) as client:
                    tools = await client.list_tools()
                    return McpTestResult(
                        success=True,
                        tools=[
                            McpToolInfo(
                                name=t.name,
                                description=t.description,
                                input_schema=t.inputSchema if hasattr(t, "inputSchema") else None,
                            )
                            for t in tools
                        ],
                    )
            else:
                return McpTestResult(success=False, error=f"Unknown transport: {server.transport}")
        except Exception as e:
            log.error("MCP connection test failed", server=server.name, error=str(e))
            return McpTestResult(success=False, error=str(e))

    @staticmethod
    async def get_server_tools(server: McpServer) -> list[dict]:
        result = await McpService.test_connection(server)
        if result.success:
            return [t.model_dump() for t in result.tools]
        return []
```

- [ ] **Step 5: Implement MCP servers router**

`backend/app/routers/mcp_servers.py`:
```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import McpServer
from app.schemas import McpServerCreate, McpServerRead, McpServerUpdate, McpTestResult
from app.services.mcp_service import McpService

router = APIRouter(prefix="/api/v1/mcp-servers", tags=["mcp-servers"])


@router.get("", response_model=list[McpServerRead])
async def list_servers(session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(select(McpServer).order_by(McpServer.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=McpServerRead, status_code=201)
async def create_server(data: McpServerCreate, session: AsyncSession = Depends(get_async_session)):
    server = McpServer(**data.model_dump())
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server


@router.get("/{server_id}", response_model=McpServerRead)
async def get_server(server_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    server = await session.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


@router.put("/{server_id}", response_model=McpServerRead)
async def update_server(server_id: uuid.UUID, data: McpServerUpdate, session: AsyncSession = Depends(get_async_session)):
    server = await session.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(server, field, value)
    await session.commit()
    await session.refresh(server)
    return server


@router.delete("/{server_id}", status_code=204)
async def delete_server(server_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    server = await session.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await session.delete(server)
    await session.commit()


@router.post("/{server_id}/test", response_model=McpTestResult)
async def test_server(server_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    server = await session.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return await McpService.test_connection(server)
```

- [ ] **Step 6: Register routers in main.py**

Add to `backend/app/main.py` after CORS middleware:
```python
from app.routers import config as config_router
from app.routers import mcp_servers as mcp_servers_router

app.include_router(config_router.router)
app.include_router(mcp_servers_router.router)
```

- [ ] **Step 7: Write and run MCP servers API test**

`backend/tests/test_api_mcp_servers.py`:
```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_create_and_list_mcp_server():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/mcp-servers", json={
            "name": "test-server",
            "transport": "stdio",
            "command": "python",
            "args": ["server.py"],
        })
        assert resp.status_code == 201
        server_id = resp.json()["id"]

        resp = await client.get("/api/v1/mcp-servers")
        assert resp.status_code == 200
        assert any(s["id"] == server_id for s in resp.json())


@pytest.mark.asyncio
async def test_update_mcp_server():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/mcp-servers", json={
            "name": "old-name",
            "transport": "stdio",
            "command": "python",
        })
        server_id = resp.json()["id"]

        resp = await client.put(f"/api/v1/mcp-servers/{server_id}", json={"name": "new-name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "new-name"


@pytest.mark.asyncio
async def test_delete_mcp_server():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/mcp-servers", json={
            "name": "to-delete",
            "transport": "stdio",
            "command": "python",
        })
        server_id = resp.json()["id"]

        resp = await client.delete(f"/api/v1/mcp-servers/{server_id}")
        assert resp.status_code == 204

        resp = await client.get(f"/api/v1/mcp-servers/{server_id}")
        assert resp.status_code == 404
```

Run:
```bash
cd backend && python -m pytest tests/test_api_config.py tests/test_api_mcp_servers.py -v
```
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/ backend/app/services/ backend/tests/test_api_*.py
git commit -m "feat: add Config and MCP Servers API routes with tests"
```

---

### Task 4: LLM service + Script generation + Prompts API

**Files:**
- Create: `backend/app/services/llm_service.py`
- Create: `backend/app/routers/prompts.py`
- Create: `backend/app/routers/scripts.py`
- Modify: `backend/app/main.py` — register routers
- Create: `backend/tests/test_llm_service.py`
- Create: `backend/tests/test_api_prompts.py`

**Interfaces:**
- Consumes: `build_generation_prompt()` from Task 2, `McpService.get_server_tools()` from Task 3, `decrypt_value()` from Task 2, all models/schemas
- Produces: `LlmService.generate_script(prompt_text: str, mcp_servers: list[McpServer], config: Config) -> tuple[str, bool, list]` — returns (code, needs_llm, llm_steps)
- Produces: `CRUD + regenerate + toggle /api/v1/prompts` endpoints
- Produces: `GET /api/v1/prompts/:id/scripts`, `GET /api/v1/scripts/:id`, `POST /api/v1/scripts/:id/run` endpoints

- [ ] **Step 1: Write failing test for LLM service**

`backend/tests/test_llm_service.py`:
```python
import ast
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.llm_service import LlmService


@pytest.mark.asyncio
async def test_generate_script_returns_valid_python():
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = """import asyncio
import json

async def main():
    result = {"output": "test", "llm_used": False, "tokens": 0}
    print(json.dumps(result))

if __name__ == "__main__":
    asyncio.run(main())"""
    mock_response.usage.total_tokens = 150

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        code, needs_llm, llm_steps = await LlmService.generate_script(
            prompt_text="Test prompt",
            mcp_servers_info=[],
            api_key="sk-test",
            llm_provider="openai",
            llm_model="gpt-4",
        )

    # Must be valid Python
    ast.parse(code)
    assert isinstance(needs_llm, bool)
    assert isinstance(llm_steps, list)


@pytest.mark.asyncio
async def test_generate_script_detects_llm_usage():
    code_with_llm = """import asyncio
import json
import os
from openai import OpenAI

async def main():
    llm = OpenAI(api_key=os.environ["LLM_API_KEY"])
    print(json.dumps({"output": "done", "llm_used": True, "tokens": 100}))

if __name__ == "__main__":
    asyncio.run(main())"""

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = code_with_llm
    mock_response.usage.total_tokens = 200

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        code, needs_llm, llm_steps = await LlmService.generate_script(
            prompt_text="Summarize data",
            mcp_servers_info=[],
            api_key="sk-test",
            llm_provider="openai",
            llm_model="gpt-4",
        )

    assert needs_llm is True
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd backend && python -m pytest tests/test_llm_service.py -v
```

- [ ] **Step 3: Implement LLM service**

`backend/app/services/llm_service.py`:
```python
import ast

import structlog
from openai import OpenAI

from app.utils.prompt_builder import build_generation_prompt

log = structlog.get_logger()

LLM_USAGE_MARKERS = ["LLM_API_KEY", "OpenAI(", "Anthropic(", "chat.completions.create"]


class LlmService:
    @staticmethod
    async def generate_script(
        prompt_text: str,
        mcp_servers_info: list[dict],
        api_key: str,
        llm_provider: str,
        llm_model: str,
    ) -> tuple[str, bool, list]:
        system_prompt = build_generation_prompt(prompt_text, mcp_servers_info)

        if llm_provider == "openai":
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_text},
                ],
                temperature=0.2,
            )
            code = response.choices[0].message.content.strip()
        elif llm_provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=llm_model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt_text}],
            )
            code = response.content[0].text.strip()
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")

        # Strip markdown fences if present
        if code.startswith("```python"):
            code = code[len("```python"):].strip()
        if code.startswith("```"):
            code = code[3:].strip()
        if code.endswith("```"):
            code = code[:-3].strip()

        # Validate syntax
        try:
            ast.parse(code)
        except SyntaxError as e:
            log.warning("Generated script has syntax error, retrying", error=str(e))
            # Retry once with the error context
            retry_msg = f"The previous script had a syntax error: {e}. Fix it and return only the corrected Python code."
            if llm_provider == "openai":
                response = client.chat.completions.create(
                    model=llm_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt_text},
                        {"role": "assistant", "content": code},
                        {"role": "user", "content": retry_msg},
                    ],
                    temperature=0.1,
                )
                code = response.choices[0].message.content.strip()
                if code.startswith("```python"):
                    code = code[len("```python"):].strip()
                if code.startswith("```"):
                    code = code[3:].strip()
                if code.endswith("```"):
                    code = code[:-3].strip()
            ast.parse(code)  # If still invalid, let it raise

        # Detect if script uses LLM at runtime
        needs_llm = any(marker in code for marker in LLM_USAGE_MARKERS)
        llm_steps = []
        if needs_llm:
            llm_steps = [{"description": "Script contains LLM API calls for runtime reasoning"}]

        return code, needs_llm, llm_steps
```

- [ ] **Step 4: Run LLM service tests — expect PASS**

```bash
cd backend && python -m pytest tests/test_llm_service.py -v
```

- [ ] **Step 5: Implement prompts router**

`backend/app/routers/prompts.py`:
```python
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_session
from app.models import Config, McpServer, Prompt, Script
from app.schemas import PromptCreate, PromptRead, PromptUpdate, ScriptRead
from app.services.llm_service import LlmService
from app.services.mcp_service import McpService
from app.utils.crypto import decrypt_value

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


@router.get("", response_model=list[PromptRead])
async def list_prompts(session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(
        select(Prompt).options(selectinload(Prompt.scripts)).order_by(Prompt.created_at.desc())
    )
    prompts = result.scalars().all()
    out = []
    for p in prompts:
        latest = max(p.scripts, key=lambda s: s.version, default=None)
        out.append(PromptRead(
            id=p.id, name=p.name, description=p.description,
            prompt_text=p.prompt_text, cron_expr=p.cron_expr,
            enabled=p.enabled, created_at=p.created_at, updated_at=p.updated_at,
            latest_script_version=latest.version if latest else None,
            needs_llm=latest.needs_llm if latest else None,
        ))
    return out


@router.post("", response_model=PromptRead, status_code=201)
async def create_prompt(data: PromptCreate, session: AsyncSession = Depends(get_async_session)):
    # Get config for LLM
    config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
    if not config or not config.api_key:
        raise HTTPException(status_code=400, detail="LLM not configured. Set API key in Config first.")

    # Get selected MCP servers and their tools
    servers = []
    for sid in data.mcp_server_ids:
        server = await session.get(McpServer, sid)
        if not server:
            raise HTTPException(status_code=404, detail=f"MCP server {sid} not found")
        tools = await McpService.get_server_tools(server)
        servers.append({
            "name": server.name,
            "transport": server.transport,
            "command": server.command,
            "args": server.args or [],
            "url": server.url,
            "tools": tools,
        })

    # Create prompt
    prompt = Prompt(
        name=data.name, description=data.description,
        prompt_text=data.prompt_text, cron_expr=data.cron_expr, enabled=data.enabled,
    )
    session.add(prompt)
    await session.commit()
    await session.refresh(prompt)

    # Generate script
    try:
        api_key = decrypt_value(config.api_key)
        code, needs_llm, llm_steps = await LlmService.generate_script(
            prompt_text=data.prompt_text,
            mcp_servers_info=servers,
            api_key=api_key,
            llm_provider=config.llm_provider,
            llm_model=config.llm_model,
        )
        script = Script(
            prompt_id=prompt.id, version=1, code=code,
            needs_llm=needs_llm, llm_steps=llm_steps,
        )
        session.add(script)
        await session.commit()
    except Exception as e:
        log.error("Script generation failed", prompt_id=str(prompt.id), error=str(e))
        # Prompt is saved, but no script — user can retry via regenerate

    return PromptRead(
        id=prompt.id, name=prompt.name, description=prompt.description,
        prompt_text=prompt.prompt_text, cron_expr=prompt.cron_expr,
        enabled=prompt.enabled, created_at=prompt.created_at, updated_at=prompt.updated_at,
        latest_script_version=1 if 'script' in dir() else None,
        needs_llm=needs_llm if 'needs_llm' in dir() else None,
    )


@router.get("/{prompt_id}", response_model=PromptRead)
async def get_prompt(prompt_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(
        select(Prompt).options(selectinload(Prompt.scripts)).where(Prompt.id == prompt_id)
    )
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    latest = max(prompt.scripts, key=lambda s: s.version, default=None)
    return PromptRead(
        id=prompt.id, name=prompt.name, description=prompt.description,
        prompt_text=prompt.prompt_text, cron_expr=prompt.cron_expr,
        enabled=prompt.enabled, created_at=prompt.created_at, updated_at=prompt.updated_at,
        latest_script_version=latest.version if latest else None,
        needs_llm=latest.needs_llm if latest else None,
    )


@router.put("/{prompt_id}", response_model=PromptRead)
async def update_prompt(prompt_id: uuid.UUID, data: PromptUpdate, session: AsyncSession = Depends(get_async_session)):
    prompt = await session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(prompt, field, value)
    await session.commit()
    await session.refresh(prompt)
    return prompt


@router.delete("/{prompt_id}", status_code=204)
async def delete_prompt(prompt_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    prompt = await session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    await session.delete(prompt)
    await session.commit()


@router.put("/{prompt_id}/toggle", response_model=PromptRead)
async def toggle_prompt(prompt_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    prompt = await session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    prompt.enabled = not prompt.enabled
    await session.commit()
    await session.refresh(prompt)
    return prompt


@router.post("/{prompt_id}/regenerate", response_model=ScriptRead)
async def regenerate_script(prompt_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    prompt = await session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
    if not config or not config.api_key:
        raise HTTPException(status_code=400, detail="LLM not configured")

    # Get MCP servers (all enabled)
    servers_result = await session.execute(select(McpServer).where(McpServer.enabled == True))
    servers_info = []
    for server in servers_result.scalars().all():
        tools = await McpService.get_server_tools(server)
        servers_info.append({
            "name": server.name, "transport": server.transport,
            "command": server.command, "args": server.args or [],
            "url": server.url, "tools": tools,
        })

    api_key = decrypt_value(config.api_key)
    code, needs_llm, llm_steps = await LlmService.generate_script(
        prompt_text=prompt.prompt_text,
        mcp_servers_info=servers_info,
        api_key=api_key,
        llm_provider=config.llm_provider,
        llm_model=config.llm_model,
    )

    # Get next version number
    max_version = await session.execute(
        select(func.max(Script.version)).where(Script.prompt_id == prompt_id)
    )
    current_max = max_version.scalar() or 0

    script = Script(
        prompt_id=prompt.id, version=current_max + 1,
        code=code, needs_llm=needs_llm, llm_steps=llm_steps,
    )
    session.add(script)
    await session.commit()
    await session.refresh(script)
    return script


@router.get("/{prompt_id}/scripts", response_model=list[ScriptRead])
async def list_prompt_scripts(prompt_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(
        select(Script).where(Script.prompt_id == prompt_id).order_by(Script.version.desc())
    )
    return result.scalars().all()
```

- [ ] **Step 6: Implement scripts router**

`backend/app/routers/scripts.py`:
```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Script
from app.schemas import ScriptRead, ExecutionRead
from app.services.script_executor import ScriptExecutor

router = APIRouter(prefix="/api/v1/scripts", tags=["scripts"])


@router.get("/{script_id}", response_model=ScriptRead)
async def get_script(script_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    script = await session.get(Script, script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    return script


@router.post("/{script_id}/run", response_model=ExecutionRead)
async def run_script(script_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    script = await session.get(Script, script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    execution = await ScriptExecutor.run(script, session)
    return execution
```

- [ ] **Step 7: Register routers in main.py**

Add to `backend/app/main.py`:
```python
from app.routers import prompts as prompts_router
from app.routers import scripts as scripts_router

app.include_router(prompts_router.router)
app.include_router(scripts_router.router)
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/llm_service.py backend/app/routers/prompts.py backend/app/routers/scripts.py backend/tests/test_llm_service.py
git commit -m "feat: add LLM service, Prompts and Scripts API routes"
```

---

### Task 5: Script executor + Executions API

**Files:**
- Create: `backend/app/services/script_executor.py`
- Create: `backend/app/routers/executions.py`
- Modify: `backend/app/main.py` — register executions router
- Create: `backend/tests/test_script_executor.py`
- Create: `backend/tests/test_api_executions.py`

**Interfaces:**
- Consumes: `Script` model, `Execution` model, `Config` model, `decrypt_value()` from Task 2
- Produces: `ScriptExecutor.run(script: Script, session: AsyncSession) -> Execution`
- Produces: `GET /api/v1/executions`, `GET /api/v1/executions/:id`, `GET /api/v1/prompts/:id/executions`

- [ ] **Step 1: Write failing test for script executor**

`backend/tests/test_script_executor.py`:
```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.script_executor import ScriptExecutor


@pytest.mark.asyncio
async def test_execute_simple_script(session):
    from app.models import Prompt, Script, Config
    from app.utils.crypto import encrypt_value

    # Create config
    config = Config(llm_provider="openai", llm_model="gpt-4", api_key=encrypt_value("sk-test"))
    session.add(config)

    prompt = Prompt(name="Test", prompt_text="Test", cron_expr="0 * * * *")
    session.add(prompt)
    await session.commit()

    script = Script(
        prompt_id=prompt.id, version=1,
        code='import json\nprint(json.dumps({"output": "hello", "llm_used": false, "tokens": 0}))',
        needs_llm=False,
    )
    session.add(script)
    await session.commit()
    await session.refresh(script)

    execution = await ScriptExecutor.run(script, session)
    assert execution.status == "success"
    assert "hello" in execution.output
    assert execution.tokens_used == 0


@pytest.mark.asyncio
async def test_execute_failing_script(session):
    from app.models import Prompt, Script, Config
    from app.utils.crypto import encrypt_value

    config = Config(llm_provider="openai", llm_model="gpt-4", api_key=encrypt_value("sk-test"))
    session.add(config)

    prompt = Prompt(name="Test", prompt_text="Test")
    session.add(prompt)
    await session.commit()

    script = Script(
        prompt_id=prompt.id, version=1,
        code="raise Exception('boom')",
        needs_llm=False,
    )
    session.add(script)
    await session.commit()
    await session.refresh(script)

    execution = await ScriptExecutor.run(script, session)
    assert execution.status == "failed"
    assert "boom" in execution.error
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd backend && python -m pytest tests/test_script_executor.py -v
```

- [ ] **Step 3: Implement script executor**

`backend/app/services/script_executor.py`:
```python
import asyncio
import json
import time
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Config, Execution, Script
from app.utils.crypto import decrypt_value

log = structlog.get_logger()


class ScriptExecutor:
    @staticmethod
    async def run(script: Script, session: AsyncSession, timeout: int | None = None) -> Execution:
        timeout = timeout or settings.DEFAULT_SCRIPT_TIMEOUT

        # Create execution record
        execution = Execution(script_id=script.id, status="running")
        session.add(execution)
        await session.commit()
        await session.refresh(execution)

        start_time = time.monotonic()

        # Build environment variables
        env = await ScriptExecutor._build_env(session)

        try:
            process = await asyncio.create_subprocess_exec(
                "python", "-c", script.code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                execution.status = "timeout"
                execution.error = f"Script timed out after {timeout}s"
                execution.finished_at = datetime.now(timezone.utc)
                execution.duration_ms = int((time.monotonic() - start_time) * 1000)
                await session.commit()
                return execution

            duration_ms = int((time.monotonic() - start_time) * 1000)
            execution.duration_ms = duration_ms
            execution.finished_at = datetime.now(timezone.utc)

            if process.returncode != 0:
                execution.status = "failed"
                execution.error = stderr.decode("utf-8", errors="replace")
                await session.commit()
                return execution

            # Parse output
            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            try:
                # Take the last line as JSON output
                last_line = stdout_str.strip().split("\n")[-1]
                result = json.loads(last_line)
                execution.status = "success"
                execution.output = result.get("output", stdout_str)
                execution.llm_output = result.get("output") if result.get("llm_used") else None
                execution.tokens_used = result.get("tokens", 0)
            except (json.JSONDecodeError, IndexError):
                execution.status = "success"
                execution.output = stdout_str
                execution.tokens_used = 0

            await session.commit()
            return execution

        except Exception as e:
            execution.status = "failed"
            execution.error = str(e)
            execution.finished_at = datetime.now(timezone.utc)
            execution.duration_ms = int((time.monotonic() - start_time) * 1000)
            await session.commit()
            log.error("Script execution error", script_id=str(script.id), error=str(e))
            return execution

    @staticmethod
    async def _build_env(session: AsyncSession) -> dict:
        import os
        env = os.environ.copy()

        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if config and config.api_key:
            env["LLM_API_KEY"] = decrypt_value(config.api_key)
            env["LLM_PROVIDER"] = config.llm_provider
            env["LLM_MODEL"] = config.llm_model

        return env
```

- [ ] **Step 4: Run executor tests — expect PASS**

```bash
cd backend && python -m pytest tests/test_script_executor.py -v
```

- [ ] **Step 5: Implement executions router**

`backend/app/routers/executions.py`:
```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_session
from app.models import Execution, Script, Prompt
from app.schemas import ExecutionRead

router = APIRouter(prefix="/api/v1", tags=["executions"])


def _execution_to_read(execution: Execution, prompt_name: str = None, script_version: int = None) -> ExecutionRead:
    return ExecutionRead(
        id=execution.id, script_id=execution.script_id, status=execution.status,
        started_at=execution.started_at, finished_at=execution.finished_at,
        output=execution.output, llm_output=execution.llm_output,
        tokens_used=execution.tokens_used, error=execution.error,
        duration_ms=execution.duration_ms,
        prompt_name=prompt_name, script_version=script_version,
    )


@router.get("/executions", response_model=list[ExecutionRead])
async def list_executions(
    status: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
):
    query = (
        select(Execution, Script, Prompt)
        .join(Script, Execution.script_id == Script.id)
        .join(Prompt, Script.prompt_id == Prompt.id)
        .order_by(desc(Execution.started_at))
        .limit(limit).offset(offset)
    )
    if status:
        query = query.where(Execution.status == status)

    result = await session.execute(query)
    return [
        _execution_to_read(e, prompt_name=p.name, script_version=s.version)
        for e, s, p in result.all()
    ]


@router.get("/executions/{execution_id}", response_model=ExecutionRead)
async def get_execution(execution_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(
        select(Execution, Script, Prompt)
        .join(Script, Execution.script_id == Script.id)
        .join(Prompt, Script.prompt_id == Prompt.id)
        .where(Execution.id == execution_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Execution not found")
    e, s, p = row
    return _execution_to_read(e, prompt_name=p.name, script_version=s.version)


@router.get("/prompts/{prompt_id}/executions", response_model=list[ExecutionRead])
async def list_prompt_executions(
    prompt_id: uuid.UUID,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(
        select(Execution, Script, Prompt)
        .join(Script, Execution.script_id == Script.id)
        .join(Prompt, Script.prompt_id == Prompt.id)
        .where(Prompt.id == prompt_id)
        .order_by(desc(Execution.started_at))
        .limit(limit).offset(offset)
    )
    return [
        _execution_to_read(e, prompt_name=p.name, script_version=s.version)
        for e, s, p in result.all()
    ]
```

- [ ] **Step 6: Register router in main.py**

Add to `backend/app/main.py`:
```python
from app.routers import executions as executions_router

app.include_router(executions_router.router)
```

- [ ] **Step 7: Run all backend tests**

```bash
cd backend && python -m pytest -v
```
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/script_executor.py backend/app/routers/executions.py backend/tests/test_script_executor.py
git commit -m "feat: add script executor and executions API"
```

---

### Task 6: APScheduler integration

**Files:**
- Create: `backend/app/services/scheduler_service.py`
- Modify: `backend/app/main.py` — start/stop scheduler in lifespan
- Modify: `backend/app/routers/prompts.py` — wire scheduler on create/toggle/delete/update cron
- Create: `backend/tests/test_scheduler_service.py`

**Interfaces:**
- Consumes: `ScriptExecutor.run()` from Task 5, `Prompt` model, `Script` model, `get_async_session()`
- Produces: `SchedulerService` with methods: `start()`, `shutdown()`, `add_job(prompt)`, `remove_job(prompt_id)`, `pause_job(prompt_id)`, `resume_job(prompt_id)`, `reschedule_job(prompt_id, cron_expr)`

- [ ] **Step 1: Write failing test for scheduler service**

`backend/tests/test_scheduler_service.py`:
```python
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.scheduler_service import SchedulerService


def test_scheduler_starts_and_stops():
    service = SchedulerService()
    service.start()
    assert service.scheduler.running
    service.shutdown()
    assert not service.scheduler.running


def test_add_and_remove_job():
    service = SchedulerService()
    service.start()

    import uuid
    prompt_id = uuid.uuid4()
    service.add_job(prompt_id, "0 8 * * *")

    job = service.scheduler.get_job(f"prompt_{prompt_id}")
    assert job is not None

    service.remove_job(prompt_id)
    job = service.scheduler.get_job(f"prompt_{prompt_id}")
    assert job is None

    service.shutdown()


def test_pause_and_resume_job():
    service = SchedulerService()
    service.start()

    import uuid
    prompt_id = uuid.uuid4()
    service.add_job(prompt_id, "0 8 * * *")

    service.pause_job(prompt_id)
    job = service.scheduler.get_job(f"prompt_{prompt_id}")
    assert job.next_run_time is None  # paused

    service.resume_job(prompt_id)
    job = service.scheduler.get_job(f"prompt_{prompt_id}")
    assert job.next_run_time is not None

    service.shutdown()


def test_reschedule_job():
    service = SchedulerService()
    service.start()

    import uuid
    prompt_id = uuid.uuid4()
    service.add_job(prompt_id, "0 8 * * *")

    service.reschedule_job(prompt_id, "0 12 * * *")
    job = service.scheduler.get_job(f"prompt_{prompt_id}")
    assert job is not None  # still exists with new schedule

    service.shutdown()
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd backend && python -m pytest tests/test_scheduler_service.py -v
```

- [ ] **Step 3: Implement scheduler service**

`backend/app/services/scheduler_service.py`:
```python
import uuid

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

log = structlog.get_logger()

# Convert async DB URL to sync for APScheduler jobstore
_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")


async def _execute_prompt_job(prompt_id: str):
    """Callback executed by APScheduler on each cron tick."""
    from app.database import async_session
    from app.models import Prompt, Script
    from app.services.script_executor import ScriptExecutor
    from sqlalchemy import select

    log.info("Cron job triggered", prompt_id=prompt_id)

    async with async_session() as session:
        prompt = await session.get(Prompt, uuid.UUID(prompt_id))
        if not prompt or not prompt.enabled:
            log.warning("Prompt not found or disabled", prompt_id=prompt_id)
            return

        # Get latest script version
        result = await session.execute(
            select(Script)
            .where(Script.prompt_id == prompt.id)
            .order_by(Script.version.desc())
            .limit(1)
        )
        script = result.scalar_one_or_none()
        if not script:
            log.warning("No script found for prompt", prompt_id=prompt_id)
            return

        execution = await ScriptExecutor.run(script, session)
        log.info("Cron job completed", prompt_id=prompt_id, status=execution.status)


class SchedulerService:
    def __init__(self, use_db_jobstore: bool = True):
        jobstores = {}
        if use_db_jobstore:
            jobstores["default"] = SQLAlchemyJobStore(url=_sync_db_url)

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
        )

    def start(self):
        self.scheduler.start()
        log.info("Scheduler started")

    def shutdown(self):
        self.scheduler.shutdown(wait=True)
        log.info("Scheduler stopped")

    def add_job(self, prompt_id: uuid.UUID, cron_expr: str):
        job_id = f"prompt_{prompt_id}"
        self.scheduler.add_job(
            _execute_prompt_job,
            trigger=CronTrigger.from_crontab(cron_expr),
            id=job_id,
            args=[str(prompt_id)],
            replace_existing=True,
        )
        log.info("Job added", job_id=job_id, cron=cron_expr)

    def remove_job(self, prompt_id: uuid.UUID):
        job_id = f"prompt_{prompt_id}"
        try:
            self.scheduler.remove_job(job_id)
            log.info("Job removed", job_id=job_id)
        except Exception:
            log.warning("Job not found for removal", job_id=job_id)

    def pause_job(self, prompt_id: uuid.UUID):
        job_id = f"prompt_{prompt_id}"
        self.scheduler.pause_job(job_id)
        log.info("Job paused", job_id=job_id)

    def resume_job(self, prompt_id: uuid.UUID):
        job_id = f"prompt_{prompt_id}"
        self.scheduler.resume_job(job_id)
        log.info("Job resumed", job_id=job_id)

    def reschedule_job(self, prompt_id: uuid.UUID, cron_expr: str):
        job_id = f"prompt_{prompt_id}"
        self.scheduler.reschedule_job(job_id, trigger=CronTrigger.from_crontab(cron_expr))
        log.info("Job rescheduled", job_id=job_id, cron=cron_expr)


# Global instance
scheduler_service = SchedulerService()
```

- [ ] **Step 4: Run scheduler tests — expect PASS**

Note: tests use in-memory jobstore, update test to pass `use_db_jobstore=False`:

Update tests to use `SchedulerService(use_db_jobstore=False)`:
```python
service = SchedulerService(use_db_jobstore=False)
```

```bash
cd backend && python -m pytest tests/test_scheduler_service.py -v
```

- [ ] **Step 5: Wire scheduler into FastAPI lifespan**

Update `backend/app/main.py` lifespan:
```python
from app.services.scheduler_service import scheduler_service
from app.database import async_session
from app.models import Prompt
from sqlalchemy import select


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting MCP Tour De Control")
    scheduler_service.start()

    # Reload cron jobs from DB
    async with async_session() as session:
        result = await session.execute(
            select(Prompt).where(Prompt.enabled == True, Prompt.cron_expr.isnot(None))
        )
        for prompt in result.scalars().all():
            scheduler_service.add_job(prompt.id, prompt.cron_expr)
            log.info("Restored cron job", prompt_id=str(prompt.id), cron=prompt.cron_expr)

    yield

    scheduler_service.shutdown()
    log.info("Shutting down MCP Tour De Control")
```

- [ ] **Step 6: Wire scheduler into prompts router**

Add to `backend/app/routers/prompts.py` — import and use scheduler in create/toggle/delete:

At top:
```python
from app.services.scheduler_service import scheduler_service
```

In `create_prompt`, after script creation succeeds and if cron_expr is set:
```python
if prompt.cron_expr and prompt.enabled:
    scheduler_service.add_job(prompt.id, prompt.cron_expr)
```

In `toggle_prompt`, after toggling:
```python
if prompt.enabled and prompt.cron_expr:
    scheduler_service.resume_job(prompt.id)
else:
    scheduler_service.pause_job(prompt.id)
```

In `delete_prompt`, before deletion:
```python
scheduler_service.remove_job(prompt.id)
```

In `update_prompt`, if cron_expr changed:
```python
if data.cron_expr is not None and prompt.cron_expr:
    scheduler_service.reschedule_job(prompt.id, prompt.cron_expr)
```

- [ ] **Step 7: Run all backend tests**

```bash
cd backend && python -m pytest -v
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/scheduler_service.py backend/app/main.py backend/app/routers/prompts.py backend/tests/test_scheduler_service.py
git commit -m "feat: integrate APScheduler with cron job management"
```

---

### Task 7: Backend Dockerfile + full docker-compose

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/.env.example`
- Modify: `docker-compose.yml` — add backend service

**Interfaces:**
- Consumes: all backend code from Tasks 1-6
- Produces: working `docker-compose up` that starts postgres + backend on port 8000

- [ ] **Step 1: Create backend Dockerfile**

`backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create .env.example**

`backend/.env.example`:
```
DATABASE_URL=postgresql+asyncpg://mcp:mcp_secret@postgres:5432/mcp_control
ENCRYPTION_KEY=<run: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
DEFAULT_SCRIPT_TIMEOUT=300
```

- [ ] **Step 3: Update docker-compose.yml**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: mcp_control
      POSTGRES_USER: mcp
      POSTGRES_PASSWORD: mcp_secret
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mcp -d mcp_control"]
      interval: 5s
      timeout: 5s
      retries: 5

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://mcp:mcp_secret@postgres:5432/mcp_control
      ENCRYPTION_KEY: ${ENCRYPTION_KEY:-dGVzdC1lbmNyeXB0aW9uLWtleS0xMjM0NTY3ODk=}
    command: >
      sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"

volumes:
  pgdata:
```

- [ ] **Step 4: Test docker-compose up**

```bash
docker-compose up --build -d
curl http://localhost:8000/health
```
Expected: `{"status":"ok"}`

- [ ] **Step 5: Commit**

```bash
git add backend/Dockerfile backend/.env.example docker-compose.yml
git commit -m "feat: add backend Docker setup and full docker-compose"
```

---

### Task 8: Frontend scaffold + API client + Layout

**Files:**
- Create: `frontend/` (Vite + React + TypeScript project)
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/components/Layout/AppShell.tsx`
- Create: `frontend/src/components/Layout/TabNav.tsx`
- Create: `frontend/src/pages/PromptsPage.tsx` (placeholder)
- Create: `frontend/src/pages/ReportsPage.tsx` (placeholder)
- Create: `frontend/src/pages/ConfigPage.tsx` (placeholder)

**Interfaces:**
- Consumes: backend API on `http://localhost:8000/api/v1`
- Produces: React app with routing, layout shell, tab navigation, typed API client

- [ ] **Step 1: Scaffold Vite React project**

```bash
cd /Users/yebe/Desktop/MCP-Tour-De-Control
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install -D tailwindcss @tailwindcss/vite
npm install @tanstack/react-query react-router-dom
npm install react-syntax-highlighter @types/react-syntax-highlighter
npm install cronstrue
```

- [ ] **Step 2: Configure Tailwind**

`frontend/src/index.css`:
```css
@import "tailwindcss";
```

`frontend/vite.config.ts`:
```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
```

- [ ] **Step 3: Create API client**

`frontend/src/lib/api.ts`:
```typescript
const BASE = "/api/v1";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Config
export const getConfig = () => request<Config>("/config");
export const updateConfig = (data: ConfigUpdate) =>
  request<Config>("/config", { method: "PUT", body: JSON.stringify(data) });

// MCP Servers
export const listMcpServers = () => request<McpServer[]>("/mcp-servers");
export const createMcpServer = (data: McpServerCreate) =>
  request<McpServer>("/mcp-servers", { method: "POST", body: JSON.stringify(data) });
export const updateMcpServer = (id: string, data: Partial<McpServerCreate>) =>
  request<McpServer>(`/mcp-servers/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteMcpServer = (id: string) =>
  request<void>(`/mcp-servers/${id}`, { method: "DELETE" });
export const testMcpServer = (id: string) =>
  request<McpTestResult>(`/mcp-servers/${id}/test`, { method: "POST" });

// Prompts
export const listPrompts = () => request<Prompt[]>("/prompts");
export const createPrompt = (data: PromptCreate) =>
  request<Prompt>("/prompts", { method: "POST", body: JSON.stringify(data) });
export const getPrompt = (id: string) => request<Prompt>(`/prompts/${id}`);
export const updatePrompt = (id: string, data: Partial<PromptCreate>) =>
  request<Prompt>(`/prompts/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const deletePrompt = (id: string) =>
  request<void>(`/prompts/${id}`, { method: "DELETE" });
export const togglePrompt = (id: string) =>
  request<Prompt>(`/prompts/${id}/toggle`, { method: "PUT" });
export const regenerateScript = (id: string) =>
  request<Script>(`/prompts/${id}/regenerate`, { method: "POST" });

// Scripts
export const listScripts = (promptId: string) =>
  request<Script[]>(`/prompts/${promptId}/scripts`);
export const getScript = (id: string) => request<Script>(`/scripts/${id}`);
export const runScript = (id: string) =>
  request<Execution>(`/scripts/${id}/run`, { method: "POST" });

// Executions
export const listExecutions = (params?: { status?: string; limit?: number; offset?: number }) => {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset) query.set("offset", String(params.offset));
  return request<Execution[]>(`/executions?${query}`);
};
export const getExecution = (id: string) => request<Execution>(`/executions/${id}`);
export const listPromptExecutions = (promptId: string) =>
  request<Execution[]>(`/prompts/${promptId}/executions`);

// Types
export interface Config {
  id: string;
  llm_provider: string;
  llm_model: string;
  api_key_set: boolean;
  updated_at: string;
}
export interface ConfigUpdate {
  llm_provider?: string;
  llm_model?: string;
  api_key?: string;
}
export interface McpServer {
  id: string;
  name: string;
  transport: string;
  command: string | null;
  args: string[] | null;
  env: Record<string, string> | null;
  url: string | null;
  enabled: boolean;
  created_at: string;
}
export interface McpServerCreate {
  name: string;
  transport: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  enabled?: boolean;
}
export interface McpToolInfo {
  name: string;
  description: string | null;
  input_schema: Record<string, unknown> | null;
}
export interface McpTestResult {
  success: boolean;
  tools: McpToolInfo[];
  error: string | null;
}
export interface Prompt {
  id: string;
  name: string;
  description: string | null;
  prompt_text: string;
  cron_expr: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  latest_script_version: number | null;
  needs_llm: boolean | null;
}
export interface PromptCreate {
  name: string;
  description?: string;
  prompt_text: string;
  cron_expr?: string;
  enabled?: boolean;
  mcp_server_ids: string[];
}
export interface Script {
  id: string;
  prompt_id: string;
  version: number;
  code: string;
  needs_llm: boolean;
  llm_steps: Record<string, unknown> | null;
  created_at: string;
}
export interface Execution {
  id: string;
  script_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  output: string | null;
  llm_output: string | null;
  tokens_used: number;
  error: string | null;
  duration_ms: number | null;
  prompt_name: string | null;
  script_version: number | null;
}
```

- [ ] **Step 4: Create layout components**

`frontend/src/components/Layout/TabNav.tsx`:
```typescript
import { NavLink } from "react-router-dom";

const tabs = [
  { to: "/", label: "Prompts" },
  { to: "/reports", label: "Reports" },
  { to: "/config", label: "Config" },
];

export function TabNav() {
  return (
    <nav className="border-b border-zinc-800 bg-zinc-950">
      <div className="mx-auto flex max-w-6xl items-center gap-8 px-6">
        <h1 className="py-4 text-lg font-bold text-white">MCP Tour De Control</h1>
        <div className="flex gap-1">
          {tabs.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.to === "/"}
              className={({ isActive }) =>
                `px-4 py-3 text-sm font-medium transition-colors ${
                  isActive
                    ? "border-b-2 border-blue-500 text-white"
                    : "text-zinc-400 hover:text-white"
                }`
              }
            >
              {tab.label}
            </NavLink>
          ))}
        </div>
      </div>
    </nav>
  );
}
```

`frontend/src/components/Layout/AppShell.tsx`:
```typescript
import { Outlet } from "react-router-dom";
import { TabNav } from "./TabNav";

export function AppShell() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <TabNav />
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Create placeholder pages and wire routing**

`frontend/src/pages/PromptsPage.tsx`:
```typescript
export function PromptsPage() {
  return <div><h2 className="text-2xl font-bold">Prompts</h2></div>;
}
```

`frontend/src/pages/ReportsPage.tsx`:
```typescript
export function ReportsPage() {
  return <div><h2 className="text-2xl font-bold">Reports</h2></div>;
}
```

`frontend/src/pages/ConfigPage.tsx`:
```typescript
export function ConfigPage() {
  return <div><h2 className="text-2xl font-bold">Config</h2></div>;
}
```

`frontend/src/App.tsx`:
```typescript
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "./components/Layout/AppShell";
import { PromptsPage } from "./pages/PromptsPage";
import { ReportsPage } from "./pages/ReportsPage";
import { ConfigPage } from "./pages/ConfigPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<PromptsPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="config" element={<ConfigPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

`frontend/src/main.tsx`:
```typescript
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

- [ ] **Step 6: Verify frontend builds**

```bash
cd frontend && npm run build
```
Expected: build succeeds with no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat: frontend scaffold with routing, layout, and API client"
```

---

### Task 9: Config page (LLM + MCP servers UI)

**Files:**
- Create: `frontend/src/components/Config/LlmConfig.tsx`
- Create: `frontend/src/components/Config/McpServerList.tsx`
- Create: `frontend/src/components/Config/McpServerForm.tsx`
- Create: `frontend/src/components/Config/McpToolsPreview.tsx`
- Modify: `frontend/src/pages/ConfigPage.tsx`

**Interfaces:**
- Consumes: API client functions `getConfig`, `updateConfig`, `listMcpServers`, `createMcpServer`, `updateMcpServer`, `deleteMcpServer`, `testMcpServer`
- Produces: fully functional Config tab UI

- [ ] **Step 1: Implement LlmConfig component**

`frontend/src/components/Config/LlmConfig.tsx`:
```typescript
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getConfig, updateConfig } from "../../lib/api";

export function LlmConfig() {
  const queryClient = useQueryClient();
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");

  const mutation = useMutation({
    mutationFn: updateConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setApiKey("");
    },
  });

  const handleSave = () => {
    mutation.mutate({
      llm_provider: provider || undefined,
      llm_model: model || undefined,
      api_key: apiKey || undefined,
    });
  };

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-6">
      <h3 className="mb-4 text-lg font-semibold">LLM Configuration</h3>
      <div className="grid gap-4">
        <div>
          <label className="mb-1 block text-sm text-zinc-400">Provider</label>
          <select
            className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white"
            value={provider || config?.llm_provider || ""}
            onChange={(e) => setProvider(e.target.value)}
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>
        <div>
          <label className="mb-1 block text-sm text-zinc-400">Model</label>
          <input
            type="text"
            className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white"
            placeholder={config?.llm_model || "gpt-4"}
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </div>
        <div>
          <label className="mb-1 block text-sm text-zinc-400">
            API Key {config?.api_key_set && <span className="text-green-500">(set)</span>}
          </label>
          <input
            type="password"
            className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white"
            placeholder="sk-..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
        <button
          onClick={handleSave}
          disabled={mutation.isPending}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {mutation.isPending ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Implement McpToolsPreview component**

`frontend/src/components/Config/McpToolsPreview.tsx`:
```typescript
import type { McpToolInfo } from "../../lib/api";

export function McpToolsPreview({ tools }: { tools: McpToolInfo[] }) {
  if (tools.length === 0) return null;
  return (
    <div className="mt-2 rounded border border-zinc-700 bg-zinc-800 p-3">
      <p className="mb-2 text-xs font-medium text-zinc-400">
        {tools.length} tool{tools.length > 1 ? "s" : ""} discovered:
      </p>
      <div className="flex flex-wrap gap-2">
        {tools.map((t) => (
          <span
            key={t.name}
            className="rounded bg-zinc-700 px-2 py-1 text-xs text-zinc-300"
            title={t.description || ""}
          >
            {t.name}
          </span>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Implement McpServerForm component**

`frontend/src/components/Config/McpServerForm.tsx`:
```typescript
import { useState } from "react";
import type { McpServerCreate } from "../../lib/api";

interface Props {
  initial?: Partial<McpServerCreate>;
  onSubmit: (data: McpServerCreate) => void;
  onCancel: () => void;
}

export function McpServerForm({ initial, onSubmit, onCancel }: Props) {
  const [name, setName] = useState(initial?.name || "");
  const [transport, setTransport] = useState(initial?.transport || "stdio");
  const [command, setCommand] = useState(initial?.command || "");
  const [args, setArgs] = useState(initial?.args?.join(" ") || "");
  const [url, setUrl] = useState(initial?.url || "");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      name,
      transport,
      command: transport === "stdio" ? command : undefined,
      args: transport === "stdio" && args ? args.split(" ") : undefined,
      url: transport === "http" ? url : undefined,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="grid gap-3 rounded border border-zinc-700 bg-zinc-800 p-4">
      <input
        required
        placeholder="Server name"
        className="rounded border border-zinc-600 bg-zinc-900 px-3 py-2 text-white"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <select
        className="rounded border border-zinc-600 bg-zinc-900 px-3 py-2 text-white"
        value={transport}
        onChange={(e) => setTransport(e.target.value)}
      >
        <option value="stdio">stdio</option>
        <option value="http">http</option>
      </select>
      {transport === "stdio" ? (
        <>
          <input
            required
            placeholder="Command (e.g. python)"
            className="rounded border border-zinc-600 bg-zinc-900 px-3 py-2 text-white"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
          />
          <input
            placeholder="Args (space-separated, e.g. server.py --port 8080)"
            className="rounded border border-zinc-600 bg-zinc-900 px-3 py-2 text-white"
            value={args}
            onChange={(e) => setArgs(e.target.value)}
          />
        </>
      ) : (
        <input
          required
          placeholder="URL (e.g. http://localhost:8080/mcp)"
          className="rounded border border-zinc-600 bg-zinc-900 px-3 py-2 text-white"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
      )}
      <div className="flex gap-2">
        <button type="submit" className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
          Save
        </button>
        <button type="button" onClick={onCancel} className="rounded bg-zinc-700 px-4 py-2 text-sm text-white hover:bg-zinc-600">
          Cancel
        </button>
      </div>
    </form>
  );
}
```

- [ ] **Step 4: Implement McpServerList component**

`frontend/src/components/Config/McpServerList.tsx`:
```typescript
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listMcpServers,
  createMcpServer,
  updateMcpServer,
  deleteMcpServer,
  testMcpServer,
} from "../../lib/api";
import type { McpServerCreate, McpTestResult } from "../../lib/api";
import { McpServerForm } from "./McpServerForm";
import { McpToolsPreview } from "./McpToolsPreview";

export function McpServerList() {
  const queryClient = useQueryClient();
  const { data: servers = [] } = useQuery({ queryKey: ["mcp-servers"], queryFn: listMcpServers });
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, McpTestResult>>({});

  const createMut = useMutation({
    mutationFn: createMcpServer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp-servers"] });
      setShowForm(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<McpServerCreate> }) => updateMcpServer(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp-servers"] });
      setEditingId(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: deleteMcpServer,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mcp-servers"] }),
  });

  const handleTest = async (id: string) => {
    const result = await testMcpServer(id);
    setTestResults((prev) => ({ ...prev, [id]: result }));
  };

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold">MCP Servers</h3>
        <button
          onClick={() => setShowForm(true)}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
        >
          + Add
        </button>
      </div>

      {showForm && (
        <div className="mb-4">
          <McpServerForm onSubmit={(data) => createMut.mutate(data)} onCancel={() => setShowForm(false)} />
        </div>
      )}

      <div className="space-y-3">
        {servers.map((server) => (
          <div key={server.id} className="rounded border border-zinc-700 bg-zinc-800 p-4">
            {editingId === server.id ? (
              <McpServerForm
                initial={server}
                onSubmit={(data) => updateMut.mutate({ id: server.id, data })}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className={`h-2 w-2 rounded-full ${server.enabled ? "bg-green-500" : "bg-zinc-500"}`} />
                    <span className="font-medium">{server.name}</span>
                    <span className="text-xs text-zinc-500">{server.transport}</span>
                    <span className="text-xs text-zinc-500">
                      {server.transport === "stdio" ? `${server.command} ${(server.args || []).join(" ")}` : server.url}
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => handleTest(server.id)} className="rounded bg-zinc-700 px-2 py-1 text-xs text-white hover:bg-zinc-600">
                      Test
                    </button>
                    <button onClick={() => setEditingId(server.id)} className="rounded bg-zinc-700 px-2 py-1 text-xs text-white hover:bg-zinc-600">
                      Edit
                    </button>
                    <button onClick={() => deleteMut.mutate(server.id)} className="rounded bg-red-900 px-2 py-1 text-xs text-white hover:bg-red-800">
                      Delete
                    </button>
                  </div>
                </div>
                {testResults[server.id] && (
                  testResults[server.id].success ? (
                    <McpToolsPreview tools={testResults[server.id].tools} />
                  ) : (
                    <p className="mt-2 text-sm text-red-400">{testResults[server.id].error}</p>
                  )
                )}
              </>
            )}
          </div>
        ))}
        {servers.length === 0 && !showForm && (
          <p className="text-sm text-zinc-500">No MCP servers configured yet.</p>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Wire ConfigPage**

`frontend/src/pages/ConfigPage.tsx`:
```typescript
import { LlmConfig } from "../components/Config/LlmConfig";
import { McpServerList } from "../components/Config/McpServerList";

export function ConfigPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Config</h2>
      <LlmConfig />
      <McpServerList />
    </div>
  );
}
```

- [ ] **Step 6: Verify build**

```bash
cd frontend && npm run build
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Config/ frontend/src/pages/ConfigPage.tsx
git commit -m "feat: implement Config tab with LLM and MCP server management"
```

---

### Task 10: Prompts page (create, list, script preview, run, regenerate)

**Files:**
- Create: `frontend/src/components/Prompts/PromptList.tsx`
- Create: `frontend/src/components/Prompts/PromptForm.tsx`
- Create: `frontend/src/components/Prompts/ScriptPreview.tsx`
- Create: `frontend/src/components/Prompts/CronPicker.tsx`
- Modify: `frontend/src/pages/PromptsPage.tsx`

**Interfaces:**
- Consumes: API client functions `listPrompts`, `createPrompt`, `togglePrompt`, `regenerateScript`, `listScripts`, `runScript`, `listMcpServers`
- Produces: fully functional Prompts tab UI

- [ ] **Step 1: Implement CronPicker component**

`frontend/src/components/Prompts/CronPicker.tsx`:
```typescript
import { useState, useEffect } from "react";
import cronstrue from "cronstrue/i18n";

interface Props {
  value: string;
  onChange: (value: string) => void;
}

const PRESETS = [
  { label: "Every hour", value: "0 * * * *" },
  { label: "Every day at 8am", value: "0 8 * * *" },
  { label: "Every day at midnight", value: "0 0 * * *" },
  { label: "Every Monday at 9am", value: "0 9 * * 1" },
  { label: "Every 5 minutes", value: "*/5 * * * *" },
];

export function CronPicker({ value, onChange }: Props) {
  const [custom, setCustom] = useState(false);
  const [humanReadable, setHumanReadable] = useState("");

  useEffect(() => {
    try {
      setHumanReadable(cronstrue.toString(value, { locale: "fr" }));
    } catch {
      setHumanReadable("Expression cron invalide");
    }
  }, [value]);

  return (
    <div>
      <label className="mb-1 block text-sm text-zinc-400">Schedule (cron)</label>
      {!custom ? (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.value}
                type="button"
                onClick={() => onChange(p.value)}
                className={`rounded px-3 py-1 text-xs ${
                  value === p.value ? "bg-blue-600 text-white" : "bg-zinc-700 text-zinc-300 hover:bg-zinc-600"
                }`}
              >
                {p.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setCustom(true)}
              className="rounded bg-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-600"
            >
              Custom...
            </button>
          </div>
        </div>
      ) : (
        <input
          type="text"
          className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white"
          placeholder="0 8 * * *"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {value && <p className="mt-1 text-xs text-zinc-500">{humanReadable}</p>}
    </div>
  );
}
```

- [ ] **Step 2: Implement ScriptPreview component**

`frontend/src/components/Prompts/ScriptPreview.tsx`:
```typescript
import { Light as SyntaxHighlighter } from "react-syntax-highlighter";
import python from "react-syntax-highlighter/dist/esm/languages/hljs/python";
import { atomOneDark } from "react-syntax-highlighter/dist/esm/styles/hljs";

SyntaxHighlighter.registerLanguage("python", python);

interface Props {
  code: string;
  version: number;
  needsLlm: boolean;
}

export function ScriptPreview({ code, version, needsLlm }: Props) {
  return (
    <div className="rounded border border-zinc-700">
      <div className="flex items-center justify-between border-b border-zinc-700 bg-zinc-800 px-4 py-2">
        <span className="text-sm font-medium">Script v{version}</span>
        <span className={`rounded px-2 py-0.5 text-xs ${needsLlm ? "bg-amber-900 text-amber-300" : "bg-green-900 text-green-300"}`}>
          {needsLlm ? "Uses LLM at runtime" : "No LLM needed"}
        </span>
      </div>
      <SyntaxHighlighter language="python" style={atomOneDark} customStyle={{ margin: 0, padding: "1rem", background: "#18181b" }}>
        {code}
      </SyntaxHighlighter>
    </div>
  );
}
```

- [ ] **Step 3: Implement PromptForm component**

`frontend/src/components/Prompts/PromptForm.tsx`:
```typescript
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listMcpServers } from "../../lib/api";
import type { PromptCreate } from "../../lib/api";
import { CronPicker } from "./CronPicker";

interface Props {
  onSubmit: (data: PromptCreate) => void;
  onCancel: () => void;
}

export function PromptForm({ onSubmit, onCancel }: Props) {
  const { data: servers = [] } = useQuery({ queryKey: ["mcp-servers"], queryFn: listMcpServers });
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [promptText, setPromptText] = useState("");
  const [cronExpr, setCronExpr] = useState("0 8 * * *");
  const [selectedServers, setSelectedServers] = useState<string[]>([]);

  const toggleServer = (id: string) => {
    setSelectedServers((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      name,
      description: description || undefined,
      prompt_text: promptText,
      cron_expr: cronExpr,
      mcp_server_ids: selectedServers,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border border-zinc-700 bg-zinc-900 p-6">
      <div>
        <label className="mb-1 block text-sm text-zinc-400">Name</label>
        <input
          required
          className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div>
        <label className="mb-1 block text-sm text-zinc-400">Description</label>
        <input
          className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div>
        <label className="mb-1 block text-sm text-zinc-400">Prompt</label>
        <textarea
          required
          rows={4}
          className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white"
          placeholder="Describe what the script should do..."
          value={promptText}
          onChange={(e) => setPromptText(e.target.value)}
        />
      </div>
      <CronPicker value={cronExpr} onChange={setCronExpr} />
      <div>
        <label className="mb-1 block text-sm text-zinc-400">MCP Servers to use</label>
        {servers.length === 0 ? (
          <p className="text-sm text-zinc-500">No servers configured. Go to Config tab first.</p>
        ) : (
          <div className="space-y-2">
            {servers.filter((s) => s.enabled).map((server) => (
              <label key={server.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selectedServers.includes(server.id)}
                  onChange={() => toggleServer(server.id)}
                  className="rounded"
                />
                {server.name}
                <span className="text-xs text-zinc-500">({server.transport})</span>
              </label>
            ))}
          </div>
        )}
      </div>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={selectedServers.length === 0}
          className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
        >
          Create & Generate Script
        </button>
        <button type="button" onClick={onCancel} className="rounded bg-zinc-700 px-4 py-2 text-sm text-white hover:bg-zinc-600">
          Cancel
        </button>
      </div>
    </form>
  );
}
```

- [ ] **Step 4: Implement PromptList component**

`frontend/src/components/Prompts/PromptList.tsx`:
```typescript
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listPrompts,
  togglePrompt,
  deletePrompt,
  regenerateScript,
  listScripts,
  runScript,
} from "../../lib/api";
import type { Prompt, Script } from "../../lib/api";
import { ScriptPreview } from "./ScriptPreview";
import cronstrue from "cronstrue/i18n";

export function PromptList() {
  const queryClient = useQueryClient();
  const { data: prompts = [] } = useQuery({ queryKey: ["prompts"], queryFn: listPrompts });
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [scripts, setScripts] = useState<Record<string, Script[]>>({});

  const toggleMut = useMutation({
    mutationFn: togglePrompt,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  });

  const deleteMut = useMutation({
    mutationFn: deletePrompt,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  });

  const regenMut = useMutation({
    mutationFn: regenerateScript,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  });

  const handleExpand = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    const s = await listScripts(id);
    setScripts((prev) => ({ ...prev, [id]: s }));
  };

  const handleRun = async (prompt: Prompt) => {
    const s = scripts[prompt.id] || (await listScripts(prompt.id));
    if (s.length > 0) {
      await runScript(s[0].id);
      queryClient.invalidateQueries({ queryKey: ["executions"] });
    }
  };

  const cronLabel = (expr: string | null) => {
    if (!expr) return "No schedule";
    try {
      return cronstrue.toString(expr, { locale: "fr" });
    } catch {
      return expr;
    }
  };

  return (
    <div className="space-y-3">
      {prompts.map((prompt) => (
        <div key={prompt.id} className="rounded-lg border border-zinc-800 bg-zinc-900">
          <div
            className="flex cursor-pointer items-center justify-between p-4"
            onClick={() => handleExpand(prompt.id)}
          >
            <div className="flex items-center gap-3">
              <span className={`h-2 w-2 rounded-full ${prompt.enabled ? "bg-green-500" : "bg-zinc-500"}`} />
              <span className="font-medium">{prompt.name}</span>
              {prompt.latest_script_version && (
                <span className="text-xs text-zinc-500">v{prompt.latest_script_version}</span>
              )}
              {prompt.needs_llm !== null && (
                <span className={`rounded px-2 py-0.5 text-xs ${prompt.needs_llm ? "bg-amber-900/50 text-amber-400" : "bg-green-900/50 text-green-400"}`}>
                  {prompt.needs_llm ? "LLM" : "No LLM"}
                </span>
              )}
            </div>
            <div className="flex items-center gap-4">
              <span className="text-xs text-zinc-500">{cronLabel(prompt.cron_expr)}</span>
              <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
                <button
                  onClick={() => handleRun(prompt)}
                  className="rounded bg-zinc-700 px-2 py-1 text-xs text-white hover:bg-zinc-600"
                >
                  Run
                </button>
                <button
                  onClick={() => regenMut.mutate(prompt.id)}
                  disabled={regenMut.isPending}
                  className="rounded bg-zinc-700 px-2 py-1 text-xs text-white hover:bg-zinc-600 disabled:opacity-50"
                >
                  Regen
                </button>
                <button
                  onClick={() => toggleMut.mutate(prompt.id)}
                  className="rounded bg-zinc-700 px-2 py-1 text-xs text-white hover:bg-zinc-600"
                >
                  {prompt.enabled ? "Disable" : "Enable"}
                </button>
                <button
                  onClick={() => deleteMut.mutate(prompt.id)}
                  className="rounded bg-red-900 px-2 py-1 text-xs text-white hover:bg-red-800"
                >
                  Delete
                </button>
              </div>
            </div>
          </div>

          {expandedId === prompt.id && scripts[prompt.id] && (
            <div className="border-t border-zinc-800 p-4">
              <p className="mb-3 text-sm text-zinc-400">{prompt.prompt_text}</p>
              {scripts[prompt.id].length > 0 ? (
                <ScriptPreview
                  code={scripts[prompt.id][0].code}
                  version={scripts[prompt.id][0].version}
                  needsLlm={scripts[prompt.id][0].needs_llm}
                />
              ) : (
                <p className="text-sm text-zinc-500">No script generated yet.</p>
              )}
            </div>
          )}
        </div>
      ))}
      {prompts.length === 0 && (
        <p className="text-center text-zinc-500">No prompts yet. Create your first one!</p>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Wire PromptsPage**

`frontend/src/pages/PromptsPage.tsx`:
```typescript
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createPrompt } from "../lib/api";
import { PromptList } from "../components/Prompts/PromptList";
import { PromptForm } from "../components/Prompts/PromptForm";

export function PromptsPage() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);

  const createMut = useMutation({
    mutationFn: createPrompt,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      setShowForm(false);
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Prompts</h2>
        <button
          onClick={() => setShowForm(true)}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          + New Prompt
        </button>
      </div>
      {showForm && (
        <PromptForm onSubmit={(data) => createMut.mutate(data)} onCancel={() => setShowForm(false)} />
      )}
      <PromptList />
    </div>
  );
}
```

- [ ] **Step 6: Verify build**

```bash
cd frontend && npm run build
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Prompts/ frontend/src/pages/PromptsPage.tsx
git commit -m "feat: implement Prompts tab with create, list, script preview, run, regenerate"
```

---

### Task 11: Reports page (execution list + detail)

**Files:**
- Create: `frontend/src/components/Reports/StatusBadge.tsx`
- Create: `frontend/src/components/Reports/ExecutionList.tsx`
- Create: `frontend/src/components/Reports/ExecutionDetail.tsx`
- Modify: `frontend/src/pages/ReportsPage.tsx`

**Interfaces:**
- Consumes: API client functions `listExecutions`, `getExecution`
- Produces: fully functional Reports tab UI

- [ ] **Step 1: Implement StatusBadge**

`frontend/src/components/Reports/StatusBadge.tsx`:
```typescript
const styles: Record<string, string> = {
  success: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
  running: "bg-blue-900 text-blue-300",
  timeout: "bg-amber-900 text-amber-300",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${styles[status] || "bg-zinc-700 text-zinc-300"}`}>
      {status}
    </span>
  );
}
```

- [ ] **Step 2: Implement ExecutionDetail**

`frontend/src/components/Reports/ExecutionDetail.tsx`:
```typescript
import type { Execution } from "../../lib/api";
import { StatusBadge } from "./StatusBadge";

interface Props {
  execution: Execution;
  onClose: () => void;
}

export function ExecutionDetail({ execution, onClose }: Props) {
  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900 p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold">{execution.prompt_name}</h3>
          <StatusBadge status={execution.status} />
          <span className="text-sm text-zinc-500">v{execution.script_version}</span>
        </div>
        <button onClick={onClose} className="text-zinc-400 hover:text-white">Close</button>
      </div>

      <div className="mb-4 grid grid-cols-4 gap-4 text-sm">
        <div>
          <span className="text-zinc-500">Started</span>
          <p>{new Date(execution.started_at).toLocaleString("fr-FR")}</p>
        </div>
        <div>
          <span className="text-zinc-500">Duration</span>
          <p>{execution.duration_ms ? `${(execution.duration_ms / 1000).toFixed(1)}s` : "—"}</p>
        </div>
        <div>
          <span className="text-zinc-500">Tokens used</span>
          <p>{execution.tokens_used}</p>
        </div>
        <div>
          <span className="text-zinc-500">Finished</span>
          <p>{execution.finished_at ? new Date(execution.finished_at).toLocaleString("fr-FR") : "—"}</p>
        </div>
      </div>

      {execution.output && (
        <div className="mb-4">
          <h4 className="mb-1 text-sm font-medium text-zinc-400">Output</h4>
          <pre className="max-h-64 overflow-auto rounded bg-zinc-800 p-4 text-sm text-zinc-200">
            {execution.output}
          </pre>
        </div>
      )}

      {execution.llm_output && (
        <div className="mb-4">
          <h4 className="mb-1 text-sm font-medium text-zinc-400">LLM Output</h4>
          <pre className="max-h-64 overflow-auto rounded bg-zinc-800 p-4 text-sm text-zinc-200">
            {execution.llm_output}
          </pre>
        </div>
      )}

      {execution.error && (
        <div>
          <h4 className="mb-1 text-sm font-medium text-red-400">Error</h4>
          <pre className="max-h-64 overflow-auto rounded bg-red-950 p-4 text-sm text-red-300">
            {execution.error}
          </pre>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Implement ExecutionList**

`frontend/src/components/Reports/ExecutionList.tsx`:
```typescript
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listExecutions, getExecution } from "../../lib/api";
import type { Execution } from "../../lib/api";
import { StatusBadge } from "./StatusBadge";
import { ExecutionDetail } from "./ExecutionDetail";

export function ExecutionList() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [selected, setSelected] = useState<Execution | null>(null);

  const { data: executions = [] } = useQuery({
    queryKey: ["executions", statusFilter],
    queryFn: () => listExecutions({ status: statusFilter || undefined }),
    refetchInterval: 10000,
  });

  const handleSelect = async (id: string) => {
    const exec = await getExecution(id);
    setSelected(exec);
  };

  if (selected) {
    return <ExecutionDetail execution={selected} onClose={() => setSelected(null)} />;
  }

  return (
    <div>
      <div className="mb-4 flex gap-2">
        {["", "success", "failed", "timeout", "running"].map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`rounded px-3 py-1 text-xs ${
              statusFilter === s ? "bg-blue-600 text-white" : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
            }`}
          >
            {s || "All"}
          </button>
        ))}
      </div>

      <div className="overflow-hidden rounded-lg border border-zinc-800">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900">
            <tr className="text-left text-zinc-400">
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3">Prompt</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Tokens</th>
              <th className="px-4 py-3">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {executions.map((exec) => (
              <tr
                key={exec.id}
                onClick={() => handleSelect(exec.id)}
                className="cursor-pointer hover:bg-zinc-900"
              >
                <td className="px-4 py-3 text-zinc-300">
                  {new Date(exec.started_at).toLocaleString("fr-FR")}
                </td>
                <td className="px-4 py-3">{exec.prompt_name}</td>
                <td className="px-4 py-3"><StatusBadge status={exec.status} /></td>
                <td className="px-4 py-3 text-zinc-400">{exec.tokens_used}</td>
                <td className="px-4 py-3 text-zinc-400">
                  {exec.duration_ms ? `${(exec.duration_ms / 1000).toFixed(1)}s` : "—"}
                </td>
              </tr>
            ))}
            {executions.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-zinc-500">
                  No executions yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire ReportsPage**

`frontend/src/pages/ReportsPage.tsx`:
```typescript
import { ExecutionList } from "../components/Reports/ExecutionList";

export function ReportsPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Reports</h2>
      <ExecutionList />
    </div>
  );
}
```

- [ ] **Step 5: Verify build**

```bash
cd frontend && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Reports/ frontend/src/pages/ReportsPage.tsx
git commit -m "feat: implement Reports tab with execution list, filters, and detail view"
```

---

### Task 12: Frontend Dockerfile + final docker-compose + end-to-end test

**Files:**
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Modify: `docker-compose.yml` — add frontend service
- Create: `backend/.env`

**Interfaces:**
- Consumes: all frontend code from Tasks 8-11, all backend code from Tasks 1-7
- Produces: fully working `docker-compose up` with all 3 services, end-to-end verified

- [ ] **Step 1: Create frontend Dockerfile (multi-stage with nginx)**

`frontend/Dockerfile`:
```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
```

`frontend/nginx.conf`:
```nginx
server {
    listen 3000;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 2: Update docker-compose.yml with frontend**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: mcp_control
      POSTGRES_USER: mcp
      POSTGRES_PASSWORD: mcp_secret
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mcp -d mcp_control"]
      interval: 5s
      timeout: 5s
      retries: 5

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://mcp:mcp_secret@postgres:5432/mcp_control
      ENCRYPTION_KEY: ${ENCRYPTION_KEY:-dGVzdC1lbmNyeXB0aW9uLWtleS0xMjM0NTY3ODk=}
    command: >
      sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - backend

volumes:
  pgdata:
```

- [ ] **Step 3: Generate a real encryption key and create .env**

```bash
cd backend && python -c "from cryptography.fernet import Fernet; print(f'ENCRYPTION_KEY={Fernet.generate_key().decode()}')" > ../.env
```

- [ ] **Step 4: Build and start everything**

```bash
cd /Users/yebe/Desktop/MCP-Tour-De-Control
docker-compose up --build -d
```

- [ ] **Step 5: End-to-end smoke test**

```bash
# Health check
curl http://localhost:8000/health
# Expected: {"status":"ok"}

# Get default config
curl http://localhost:8000/api/v1/config
# Expected: JSON with llm_provider, api_key_set: false

# Create an MCP server
curl -X POST http://localhost:8000/api/v1/mcp-servers \
  -H "Content-Type: application/json" \
  -d '{"name":"test-server","transport":"stdio","command":"python","args":["--version"]}'
# Expected: 201 with server JSON

# Check frontend loads
curl -s http://localhost:3000 | head -5
# Expected: HTML with React app
```

- [ ] **Step 6: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf docker-compose.yml .env
git commit -m "feat: add frontend Docker build and complete docker-compose setup"
```

- [ ] **Step 7: Final push**

```bash
git push origin main
```
