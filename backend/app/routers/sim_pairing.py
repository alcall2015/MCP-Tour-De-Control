import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import SimPair, SimPairHistory, SimPairMessage, SimPairMessageQueue, SimPairingGroup, SimPairingRun, SimPairingTopic
from app.schemas.sim_pairing import SimPairCountRead, SimPairHistoryRead, SimPairMessageQueueRead, SimPairMessageRead, SimPairQueueStats, SimPairRead, SimPairingGroupCreate, SimPairingGroupRead, SimPairingTopicCreate, SimPairingTopicRead
from app.services.sim_pair_conversation_service import SimPairConversationService
from app.services.sim_pairing_service import SimPairingService

router = APIRouter(prefix="/api/v1/sim-pairing", tags=["sim-pairing"])


@router.get("/groups", response_model=list[SimPairingGroupRead])
async def list_groups(session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(select(SimPairingGroup).order_by(SimPairingGroup.name))
    return list(result.scalars().all())


@router.post("/groups", response_model=SimPairingGroupRead, status_code=201)
async def create_group(data: SimPairingGroupCreate, session: AsyncSession = Depends(get_async_session)):
    group = SimPairingGroup(name=data.name.strip())
    session.add(group)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="This SIM group is already tracked")
    await session.refresh(group)
    return group


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    group = await session.get(SimPairingGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="SIM group not found")
    await session.delete(group)
    await session.commit()


@router.get("/topics", response_model=list[SimPairingTopicRead])
async def list_topics(session: AsyncSession = Depends(get_async_session)):
    return list((await session.execute(select(SimPairingTopic).order_by(SimPairingTopic.name))).scalars())


@router.post("/topics", response_model=SimPairingTopicRead, status_code=201)
async def create_topic(data: SimPairingTopicCreate, session: AsyncSession = Depends(get_async_session)):
    topic = SimPairingTopic(name=data.name.strip())
    session.add(topic)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="This conversation topic already exists")
    await session.refresh(topic)
    return topic


@router.delete("/topics/{topic_id}", status_code=204)
async def delete_topic(topic_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    topic = await session.get(SimPairingTopic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Conversation topic not found")
    await session.delete(topic)
    await session.commit()


@router.get("/pairs/count", response_model=SimPairCountRead)
async def pairs_count(session: AsyncSession = Depends(get_async_session)):
    """Counts for both statuses, so the UI can label the archived toggle and size pagination without fetching rows it will not display."""
    active = (
        await session.execute(select(func.count()).select_from(SimPair).where(SimPair.status == "active"))
    ).scalar_one()
    archived = (
        await session.execute(select(func.count()).select_from(SimPair).where(SimPair.status == "archived"))
    ).scalar_one()
    return SimPairCountRead(active=active, archived=archived)


@router.get("/pairs", response_model=list[SimPairRead])
async def list_pairs(
    status: Literal["active", "archived"] | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_async_session),
):
    query = select(SimPair).order_by(SimPair.created_at.desc())
    if status is not None:
        query = query.where(SimPair.status == status)
    query = query.limit(limit).offset(offset)
    return list((await session.execute(query)).scalars())


@router.get("/pairs/{pair_id}/history", response_model=list[SimPairHistoryRead])
async def pair_history(pair_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    return list((await session.execute(select(SimPairHistory).where(SimPairHistory.pair_id == pair_id).order_by(SimPairHistory.created_at.desc()))).scalars())


@router.get("/pairs/{pair_id}/messages", response_model=list[SimPairMessageRead])
async def pair_messages(pair_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    return list((await session.execute(
        select(SimPairMessage).where(SimPairMessage.pair_id == pair_id).order_by(SimPairMessage.created_at.asc())
    )).scalars())


@router.get("/queue", response_model=list[SimPairMessageQueueRead])
async def list_message_queue(session: AsyncSession = Depends(get_async_session)):
    return list((await session.execute(
        select(SimPairMessageQueue).order_by(SimPairMessageQueue.status, SimPairMessageQueue.due_at).limit(100)
    )).scalars())


@router.get("/queue/stats", response_model=SimPairQueueStats)
async def queue_stats(session: AsyncSession = Depends(get_async_session)):
    """Backlog visibility: how many due items the send rate is not keeping up with."""
    return await SimPairConversationService.queue_stats(session)


@router.get("/runs")
async def list_runs(session: AsyncSession = Depends(get_async_session)):
    return list((await session.execute(select(SimPairingRun).order_by(SimPairingRun.started_at.desc()).limit(20))).scalars())


@router.post("/sync")
async def sync_pairs(session: AsyncSession = Depends(get_async_session)):
    return await SimPairingService.sync(session)


@router.post("/conversations/run")
async def run_pair_conversations(country: str | None = None, session: AsyncSession = Depends(get_async_session)):
    # Manual runs use the same cadence as the scheduler; they never bypass it.
    return await SimPairConversationService.run_due(session, country=country)


@router.post("/conversations/preview")
async def preview_pair_conversation(session: AsyncSession = Depends(get_async_session)):
    """Generate one proposed SMS without persisting it or calling TmLite."""
    return await SimPairConversationService.run_due(session, dry_run=True, limit=1)
