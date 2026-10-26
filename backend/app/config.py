from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control"
    ENCRYPTION_KEY: str = "generate-a-fernet-key-here"
    DEFAULT_SCRIPT_TIMEOUT: int = 300
    SIPP_MCP_URL: str = "http://localhost:9090/mcp"
    # Empty means "the interpreter running this backend", which is the only one
    # guaranteed to have the generated scripts' dependencies installed.
    SCRIPT_PYTHON: str = ""

    # Agent execution worker
    AGENT_WORKER_CONCURRENCY: int = 2
    AGENT_TASK_HEARTBEAT_SECONDS: int = 15
    AGENT_TASK_STALE_SECONDS: int = 90
    AGENT_TASK_FINAL_GRACE_SECONDS: int = 90
    # Per-call ceilings: without them a provider or an MCP server that never
    # answers hangs a task until the stale sweep notices, which it cannot do
    # while the heartbeat keeps beating.
    LLM_CALL_TIMEOUT_SECONDS: int = 120
    MCP_TOOL_TIMEOUT_SECONDS: int = 120

    # Used to build the task links put in WhatsApp approval notifications.
    PUBLIC_BASE_URL: str = "https://tour.alcall.net"

    model_config = {"env_file": ".env"}


settings = Settings()
