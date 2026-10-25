import uuid
from datetime import datetime

from pydantic import BaseModel


class ConfigRead(BaseModel):
    id: uuid.UUID
    llm_provider: str
    llm_model: str
    api_key_set: bool  # never expose the key, just whether it's set
    google_sa_key_set: bool  # same rule for the Google service account key
    google_sa_email: str | None = None  # client_email only, never other key material
    drive_folder_id: str
    activity_cron: str
    pairing_openrouter_api_key_set: bool
    pairing_openrouter_model: str
    pairing_conversation_enabled: bool
    pairing_conversation_interval_minutes: int
    pairing_target_messages: int
    pairing_max_messages_per_run: int
    pairing_sim_cooldown_minutes: int
    pairing_quiet_hours_enabled: bool
    pairing_quiet_start_hour: int
    pairing_quiet_end_hour: int
    sms_autoreply_enabled: bool
    sms_autoreply_template: str
    sms_autoreply_max_per_run: int
    sms_autoreply_lookback_minutes: int
    sms_autoreply_recipient_cooldown_hours: int
    pairing_archive_retention_days: int
    pairing_call_enabled: bool
    pairing_call_interval_minutes: int
    pairing_call_min_seconds: int
    pairing_call_max_seconds: int
    pairing_call_max_per_run: int
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConfigUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    api_key: str | None = None  # plaintext, will be encrypted before storage
    google_sa_key: str | None = None  # plaintext JSON, will be encrypted before storage
    drive_folder_id: str | None = None
    activity_cron: str | None = None
    pairing_openrouter_api_key: str | None = None
    pairing_openrouter_model: str | None = None
    pairing_conversation_enabled: bool | None = None
    pairing_conversation_interval_minutes: int | None = None
    pairing_target_messages: int | None = None
    pairing_max_messages_per_run: int | None = None
    pairing_sim_cooldown_minutes: int | None = None
    pairing_quiet_hours_enabled: bool | None = None
    pairing_quiet_start_hour: int | None = None
    pairing_quiet_end_hour: int | None = None
    sms_autoreply_enabled: bool | None = None
    sms_autoreply_template: str | None = None
    sms_autoreply_max_per_run: int | None = None
    sms_autoreply_lookback_minutes: int | None = None
    sms_autoreply_recipient_cooldown_hours: int | None = None
    pairing_archive_retention_days: int | None = None
    pairing_call_enabled: bool | None = None
    pairing_call_interval_minutes: int | None = None
    pairing_call_min_seconds: int | None = None
    pairing_call_max_seconds: int | None = None
    pairing_call_max_per_run: int | None = None
