from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import SmsReply
from app.schemas.sms_reply import SmsAutoReplyStats, SmsReplyPage
from app.services.sms_auto_reply_service import SmsAutoReplyService

router = APIRouter(prefix="/api/v1/sms-autoreply", tags=["sms-autoreply"])


@router.get("/replies", response_model=SmsReplyPage)
async def list_replies(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_async_session),
):
    total = (await session.execute(select(func.count()).select_from(SmsReply))).scalar_one()
    items = list((await session.execute(
        select(SmsReply).order_by(SmsReply.created_at.desc()).limit(limit).offset(offset)
    )).scalars())
    return SmsReplyPage(items=items, total=total)


@router.get("/stats", response_model=SmsAutoReplyStats)
async def stats(session: AsyncSession = Depends(get_async_session)):
    return await SmsAutoReplyService.stats(session)


@router.post("/run")
async def run(session: AsyncSession = Depends(get_async_session)):
    """Run for real: sends SMS. Never call this to preview — use /preview."""
    return await SmsAutoReplyService.run(session)


@router.post("/preview")
async def preview(session: AsyncSession = Depends(get_async_session)):
    """Show what would be sent. Reads TmLite in dry-run mode, never sends."""
    return await SmsAutoReplyService.run(session, dry_run=True)
