from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control"
    ENCRYPTION_KEY: str = "generate-a-fernet-key-here"
    DEFAULT_SCRIPT_TIMEOUT: int = 300

    model_config = {"env_file": ".env"}


settings = Settings()
