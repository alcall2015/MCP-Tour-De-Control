from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import SmsReply
from app.schemas.sms_reply import SmsAutoReplyStats, SmsReplyRead
from app.services.sms_auto_reply_service import SmsAutoReplyService

router = APIRouter(prefix="/api/v1/sms-autoreply", tags=["sms-autoreply"])


@router.get("/replies", response_model=list[SmsReplyRead])
async def list_replies(session: AsyncSession = Depends(get_async_session)):
    return list((await session.execute(
        select(SmsReply).order_by(SmsReply.created_at.desc()).limit(100)
    )).scalars())


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
