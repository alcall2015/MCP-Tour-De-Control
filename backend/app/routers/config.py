import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Config
from app.schemas import ConfigRead, ConfigUpdate
from app.services.google_service import parse_file_id
from app.services.scheduler_service import is_valid_cron, scheduler_service
from app.utils.crypto import decrypt_value, encrypt_value

router = APIRouter(prefix="/api/v1/config", tags=["config"])


def _google_sa_email(config: Config) -> str | None:
    """Best-effort extraction of client_email from the stored key.

    Never returns anything else from the key: a missing key, undecryptable
    ciphertext, unparsable JSON, or a JSON body without client_email all
    resolve to None.
    """
    if not config.google_sa_key:
        return None
    try:
        data = json.loads(decrypt_value(config.google_sa_key))
    except Exception:
        return None
    email = data.get("client_email") if isinstance(data, dict) else None
    return email if isinstance(email, str) else None


async def _get_or_create_config(session: AsyncSession) -> Config:
    result = await session.execute(select(Config).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        config = Config()
        session.add(config)
        await session.commit()
        await session.refresh(config)
    return config


def _to_read(config: Config) -> ConfigRead:
    return ConfigRead(
        id=config.id,
        llm_provider=config.llm_provider,
        llm_model=config.llm_model,
        api_key_set=bool(config.api_key),
        google_sa_key_set=bool(config.google_sa_key),
        google_sa_email=_google_sa_email(config),
        drive_folder_id=config.drive_folder_id,
        activity_cron=config.activity_cron,
        pairing_openrouter_api_key_set=bool(config.pairing_openrouter_api_key),
        pairing_openrouter_model=config.pairing_openrouter_model,
        pairing_conversation_enabled=config.pairing_conversation_enabled,
        pairing_conversation_interval_minutes=config.pairing_conversation_interval_minutes,
        pairing_target_messages=config.pairing_target_messages,
        pairing_max_messages_per_run=config.pairing_max_messages_per_run,
        pairing_sim_cooldown_minutes=config.pairing_sim_cooldown_minutes,
        pairing_quiet_hours_enabled=config.pairing_quiet_hours_enabled,
        pairing_quiet_start_hour=config.pairing_quiet_start_hour,
        pairing_quiet_end_hour=config.pairing_quiet_end_hour,
        sms_autoreply_enabled=config.sms_autoreply_enabled,
        sms_autoreply_template=config.sms_autoreply_template,
        sms_autoreply_max_per_run=config.sms_autoreply_max_per_run,
        sms_autoreply_lookback_minutes=config.sms_autoreply_lookback_minutes,
        sms_autoreply_recipient_cooldown_hours=config.sms_autoreply_recipient_cooldown_hours,
        updated_at=config.updated_at,
    )


@router.get("", response_model=ConfigRead)
async def get_config(session: AsyncSession = Depends(get_async_session)):
    return _to_read(await _get_or_create_config(session))


@router.put("", response_model=ConfigRead)
async def update_config(data: ConfigUpdate, session: AsyncSession = Depends(get_async_session)):
    # Validate before touching the database or the session, so an invalid
    # cron expression rejects the whole request without persisting anything
    # and without leaving the DB and the live scheduler out of sync.
    if data.activity_cron is not None and not is_valid_cron(data.activity_cron):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid cron expression for activity_cron: {data.activity_cron!r}",
        )

    config = await _get_or_create_config(session)
    if data.llm_provider is not None:
        config.llm_provider = data.llm_provider
    if data.llm_model is not None:
        config.llm_model = data.llm_model
    if data.api_key is not None:
        config.api_key = encrypt_value(data.api_key)
    if data.google_sa_key is not None:
        config.google_sa_key = encrypt_value(data.google_sa_key)
    if data.drive_folder_id is not None:
        parsed = parse_file_id(data.drive_folder_id)
        value = parsed or data.drive_folder_id
        max_len = Config.drive_folder_id.type.length
        if parsed is None and len(value) > max_len:
            raise HTTPException(
                status_code=422,
                detail=f"drive_folder_id: could not extract a folder id and the value exceeds {max_len} characters",
            )
        config.drive_folder_id = value

    cron_changed = data.activity_cron is not None and data.activity_cron != config.activity_cron
    if data.activity_cron is not None:
        config.activity_cron = data.activity_cron
    if data.pairing_openrouter_api_key is not None:
        config.pairing_openrouter_api_key = encrypt_value(data.pairing_openrouter_api_key)
    if data.pairing_openrouter_model is not None:
        model = data.pairing_openrouter_model.strip()
        if not model:
            raise HTTPException(status_code=422, detail="pairing_openrouter_model must not be empty")
        config.pairing_openrouter_model = model
    if data.pairing_conversation_enabled is not None:
        config.pairing_conversation_enabled = data.pairing_conversation_enabled
    if data.pairing_conversation_interval_minutes is not None:
        if not 30 <= data.pairing_conversation_interval_minutes <= 1440:
            raise HTTPException(status_code=422, detail="pairing_conversation_interval_minutes must be between 30 and 1440")
        config.pairing_conversation_interval_minutes = data.pairing_conversation_interval_minutes
    if data.pairing_target_messages is not None:
        if not 2 <= data.pairing_target_messages <= 100:
            raise HTTPException(status_code=422, detail="pairing_target_messages must be between 2 and 100")
        config.pairing_target_messages = data.pairing_target_messages
    if data.pairing_max_messages_per_run is not None:
        if not 1 <= data.pairing_max_messages_per_run <= 50:
            raise HTTPException(status_code=422, detail="pairing_max_messages_per_run must be between 1 and 50")
        config.pairing_max_messages_per_run = data.pairing_max_messages_per_run
    if data.pairing_sim_cooldown_minutes is not None:
        if not 0 <= data.pairing_sim_cooldown_minutes <= 240:
            raise HTTPException(status_code=422, detail="pairing_sim_cooldown_minutes must be between 0 and 240")
        config.pairing_sim_cooldown_minutes = data.pairing_sim_cooldown_minutes
    if data.pairing_quiet_hours_enabled is not None:
        config.pairing_quiet_hours_enabled = data.pairing_quiet_hours_enabled
    for field in ("pairing_quiet_start_hour", "pairing_quiet_end_hour"):
        hour = getattr(data, field)
        if hour is not None:
            if not 0 <= hour <= 23:
                raise HTTPException(status_code=422, detail=f"{field} must be between 0 and 23")
            setattr(config, field, hour)

    if data.sms_autoreply_enabled is not None:
        config.sms_autoreply_enabled = data.sms_autoreply_enabled
    if data.sms_autoreply_template is not None:
        template = data.sms_autoreply_template.strip()
        if "{whatsapp}" not in template:
            raise HTTPException(status_code=422, detail="sms_autoreply_template must contain {whatsapp}")
        config.sms_autoreply_template = template
    if data.sms_autoreply_max_per_run is not None:
        if not 1 <= data.sms_autoreply_max_per_run <= 50:
            raise HTTPException(status_code=422, detail="sms_autoreply_max_per_run must be between 1 and 50")
        config.sms_autoreply_max_per_run = data.sms_autoreply_max_per_run
    if data.sms_autoreply_lookback_minutes is not None:
        if not 15 <= data.sms_autoreply_lookback_minutes <= 1440:
            raise HTTPException(status_code=422, detail="sms_autoreply_lookback_minutes must be between 15 and 1440")
        config.sms_autoreply_lookback_minutes = data.sms_autoreply_lookback_minutes
    if data.sms_autoreply_recipient_cooldown_hours is not None:
        if not 1 <= data.sms_autoreply_recipient_cooldown_hours <= 720:
            raise HTTPException(status_code=422,
                                detail="sms_autoreply_recipient_cooldown_hours must be between 1 and 720")
        config.sms_autoreply_recipient_cooldown_hours = data.sms_autoreply_recipient_cooldown_hours

    await session.commit()
    await session.refresh(config)

    if cron_changed:
        scheduler_service.set_activity_job(config.activity_cron)

    return _to_read(config)
