import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Config
from app.schemas import ConfigRead, ConfigUpdate
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
        projects_cron=config.projects_cron,
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
    if data.projects_cron is not None and not is_valid_cron(data.projects_cron):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid cron expression for projects_cron: {data.projects_cron!r}",
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

    cron_changed = data.projects_cron is not None and data.projects_cron != config.projects_cron
    if data.projects_cron is not None:
        config.projects_cron = data.projects_cron

    await session.commit()
    await session.refresh(config)

    if cron_changed:
        scheduler_service.set_projects_job(config.projects_cron)

    return _to_read(config)
