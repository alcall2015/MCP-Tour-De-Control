import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.schemas import HeatmapRead, ScanResult, SectionRead
from app.services.activity_view import ActivityView
from app.services.document_scanner import DocumentScanner
from app.services.google_service import GoogleAccessError

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/activity", tags=["activity"])


@router.get("/documents", response_model=list[SectionRead])
async def list_documents(session: AsyncSession = Depends(get_async_session)):
    return await ActivityView.sections(session)


@router.get("/heatmap", response_model=HeatmapRead)
async def get_heatmap(session: AsyncSession = Depends(get_async_session)):
    return await ActivityView.heatmap(session)


@router.post("/scan", response_model=ScanResult)
async def scan_now(session: AsyncSession = Depends(get_async_session)):
    try:
        walked = await DocumentScanner.scan_all(session)
    except GoogleAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ScanResult(walked=walked)
