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
