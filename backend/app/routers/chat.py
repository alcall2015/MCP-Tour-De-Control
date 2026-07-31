import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Conversation, ChatMessage
from app.schemas import ConversationRead, ChatMessageRead, ChatMessageCreate

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
