import uuid
from datetime import datetime

from pydantic import BaseModel


class ConfigRead(BaseModel):
    id: uuid.UUID
    llm_provider: str
    llm_model: str
    api_key_set: bool  # never expose the key, just whether it's set
    google_sa_key_set: bool  # same rule for the Google service account key
    projects_cron: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConfigUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    api_key: str | None = None  # plaintext, will be encrypted before storage
    google_sa_key: str | None = None  # plaintext JSON, will be encrypted before storage
    projects_cron: str | None = None
