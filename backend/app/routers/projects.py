import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Project, ProjectLink, ProjectSnapshot
from app.schemas import (
    BudgetSummary,
    PendingDecision,
    ProjectCreate,
    ProjectDetail,
    ProjectLinkCreate,
    ProjectLinkRead,
    ProjectLinkUpdate,
    ProjectUpdate,
    ProjectView,
    RefreshResult,
)
from app.services.google_service import GoogleAccessError, detect_kind, parse_file_id
from app.services.project_service import ProjectService, budget_summary, pending_decisions

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


# --- Collection routes -------------------------------------------------------
# Literal paths MUST stay above /{project_id}, otherwise FastAPI parses them as a UUID.


@router.get("", response_model=list[ProjectView])
async def list_projects(session: AsyncSession = Depends(get_async_session)):
    return await ProjectService.build_views(session)


@router.post("", response_model=ProjectView, status_code=201)
async def create_project(data: ProjectCreate, session: AsyncSession = Depends(get_async_session)):
    project = Project(**data.model_dump())
    session.add(project)
    await session.commit()
    await session.refresh(project)

    views = await ProjectService.build_views(session)
    view = next((v for v in views if v["id"] == project.id), None)
    if view is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return view


@router.get("/decisions", response_model=list[PendingDecision])
async def list_decisions(session: AsyncSession = Depends(get_async_session)):
    return pending_decisions(await ProjectService.build_views(session))


@router.get("/summary", response_model=BudgetSummary)
async def get_summary(session: AsyncSession = Depends(get_async_session)):
    return budget_summary(await ProjectService.build_views(session))


@router.post("/refresh", response_model=RefreshResult)
async def refresh_projects(session: AsyncSession = Depends(get_async_session)):
    try:
        refreshed = await ProjectService.refresh_all(session)
    except GoogleAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RefreshResult(refreshed=refreshed)


# --- Link routes (also literal, keep above /{project_id}) --------------------


@router.put("/links/{link_id}", response_model=ProjectLinkRead)
async def update_link(
    link_id: uuid.UUID, data: ProjectLinkUpdate, session: AsyncSession = Depends(get_async_session)
):
    link = await session.get(ProjectLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(link, field, value)
    if data.url is not None:
        link.kind = detect_kind(data.url)
        link.file_id = parse_file_id(data.url)

    await session.commit()
    await session.refresh(link)
    return link


@router.delete("/links/{link_id}", status_code=204)
async def delete_link(link_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    link = await session.get(ProjectLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    await session.delete(link)
    await session.commit()


# --- Single-project routes ---------------------------------------------------


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    views = await ProjectService.build_views(session)
    view = next((v for v in views if v["id"] == project_id), None)
    if not view:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await session.execute(
        select(ProjectSnapshot)
        .where(ProjectSnapshot.project_id == project_id)
        .order_by(ProjectSnapshot.captured_at.desc())
    )
    return {**view, "history": list(result.scalars().all())}


@router.put("/{project_id}", response_model=ProjectView)
async def update_project(
    project_id: uuid.UUID, data: ProjectUpdate, session: AsyncSession = Depends(get_async_session)
):
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await session.commit()

    views = await ProjectService.build_views(session)
    view = next((v for v in views if v["id"] == project_id), None)
    if view is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return view


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await session.delete(project)
    await session.commit()


@router.post("/{project_id}/refresh", response_model=RefreshResult)
async def refresh_project(project_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        written = await ProjectService.refresh_one(session, project_id)
    except GoogleAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RefreshResult(refreshed=1 if written else 0)


@router.post("/{project_id}/links", response_model=ProjectLinkRead, status_code=201)
async def add_link(
    project_id: uuid.UUID, data: ProjectLinkCreate, session: AsyncSession = Depends(get_async_session)
):
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    link = ProjectLink(
        project_id=project_id,
        label=data.label,
        url=data.url,
        kind=detect_kind(data.url),
        file_id=parse_file_id(data.url),
        is_kpi_source=data.is_kpi_source,
        position=data.position,
    )
    session.add(link)
    await session.commit()
    await session.refresh(link)
    return link
