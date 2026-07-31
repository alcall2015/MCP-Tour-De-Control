import asyncio
import time
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Conversation, ChatMessage
from app.schemas import ConversationRead, ChatMessageRead, ChatMessageCreate
from app.services.chat_service import ChatService

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.get("/conversations", response_model=list[ConversationRead])
async def list_conversations(session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(
        select(Conversation).order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


@router.post("/conversations", response_model=ConversationRead, status_code=201)
async def create_conversation(session: AsyncSession = Depends(get_async_session)):
    conv = Conversation()
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return conv


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    conv = await session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await session.delete(conv)
    await session.commit()


@router.get("/conversations/{conversation_id}/messages", response_model=list[ChatMessageRead])
async def list_messages(conversation_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    conv = await session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at)
    )
    return result.scalars().all()


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    data: ChatMessageCreate,
    session: AsyncSession = Depends(get_async_session),
):
    conv = await session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    async def event_generator():
        async for event in ChatService.stream_response(
            str(conversation_id), data.content, session
        ):
            yield event

    return StreamingResponse(event_generator(), media_type="text/event-stream")


class RunScriptRequest(BaseModel):
    code: str


@router.post("/conversations/{conversation_id}/run-script")
async def run_script_in_chat(
    conversation_id: uuid.UUID,
    data: RunScriptRequest,
    session: AsyncSession = Depends(get_async_session),
):
    conv = await session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Build environment with LLM keys (reuse logic from ScriptExecutor)
    import os
    from app.models import Config
    from app.utils.crypto import decrypt_value

    env = os.environ.copy()
    config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
    if config and config.api_key:
        env["LLM_API_KEY"] = decrypt_value(config.api_key)
        env["LLM_PROVIDER"] = config.llm_provider
        env["LLM_MODEL"] = config.llm_model

    timeout = 60
    start_time = time.monotonic()

    try:
        process = await asyncio.create_subprocess_exec(
            "python", "-c", data.code,
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
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "status": "timeout",
                "output": None,
                "error": f"Script timed out after {timeout}s",
                "duration_ms": duration_ms,
            }

        duration_ms = int((time.monotonic() - start_time) * 1000)

        if process.returncode != 0:
            return {
                "status": "failed",
                "output": None,
                "error": stderr.decode("utf-8", errors="replace"),
                "duration_ms": duration_ms,
            }

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        return {
            "status": "success",
            "output": stdout_str,
            "error": None,
            "duration_ms": duration_ms,
        }

    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        return {
            "status": "failed",
            "output": None,
            "error": str(e),
            "duration_ms": duration_ms,
        }
