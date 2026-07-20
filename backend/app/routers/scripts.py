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
