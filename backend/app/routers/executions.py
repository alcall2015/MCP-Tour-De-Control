import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

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
