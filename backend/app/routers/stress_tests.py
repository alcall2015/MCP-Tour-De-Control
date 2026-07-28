import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import StressTest, StressTestMetrics
from app.schemas import (
    StressTestCreate, StressTestRead, StressTestMetricsRead,
    StressTestCompareRequest, ScenarioInfo,
)
from app.services.stress_test_service import StressTestService

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/stress-tests", tags=["stress-tests"])


@router.get("", response_model=list[StressTestRead])
async def list_stress_tests(
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(
        select(StressTest).order_by(desc(StressTest.created_at)).limit(limit).offset(offset)
    )
    tests = result.scalars().all()
    out = []
    for t in tests:
        latest = await StressTestService.get_latest_metrics(str(t.id), session)
        read = StressTestRead.model_validate(t)
        if latest:
            read.latest_metrics = StressTestMetricsRead.model_validate(latest)
        out.append(read)
    return out


@router.post("", response_model=StressTestRead, status_code=201)
async def create_stress_test(
    data: StressTestCreate,
    session: AsyncSession = Depends(get_async_session),
):
    test = StressTest(**data.model_dump())
    session.add(test)
    await session.commit()
    await session.refresh(test)

    test = await StressTestService.launch_test(test, session)
    return StressTestRead.model_validate(test)


# NOTE: /scenarios must be defined BEFORE /{test_id} to avoid route conflicts
@router.get("/scenarios", response_model=list[ScenarioInfo])
async def list_scenarios():
    scenarios = await StressTestService.get_scenarios()
    return [ScenarioInfo(**s) for s in scenarios]


# NOTE: /compare must be defined BEFORE /{test_id} to avoid route conflicts
@router.post("/compare", response_model=list[StressTestRead])
async def compare_tests(
    data: StressTestCompareRequest,
    session: AsyncSession = Depends(get_async_session),
):
    results = []
    for tid in data.test_ids:
        test = await session.get(StressTest, tid)
        if not test:
            continue
        latest = await StressTestService.get_latest_metrics(str(tid), session)
        read = StressTestRead.model_validate(test)
        if latest:
            read.latest_metrics = StressTestMetricsRead.model_validate(latest)
        results.append(read)
    return results


@router.get("/{test_id}", response_model=StressTestRead)
async def get_stress_test(
    test_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    test = await session.get(StressTest, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Stress test not found")
    latest = await StressTestService.get_latest_metrics(str(test_id), session)
    read = StressTestRead.model_validate(test)
    if latest:
        read.latest_metrics = StressTestMetricsRead.model_validate(latest)
    return read


@router.delete("/{test_id}", status_code=204)
async def delete_stress_test(
    test_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    test = await session.get(StressTest, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Stress test not found")
    if test.status == "running":
        await StressTestService.stop_test(test, session)
    await session.delete(test)
    await session.commit()


@router.post("/{test_id}/stop", response_model=StressTestRead)
async def stop_stress_test(
    test_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    test = await session.get(StressTest, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Stress test not found")
    if test.status != "running":
        raise HTTPException(status_code=400, detail="Test is not running")
    test = await StressTestService.stop_test(test, session)
    return StressTestRead.model_validate(test)


@router.get("/{test_id}/metrics", response_model=list[StressTestMetricsRead])
async def get_metrics_timeline(
    test_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    metrics = await StressTestService.get_all_metrics(str(test_id), session)
    return [StressTestMetricsRead.model_validate(m) for m in metrics]


@router.get("/{test_id}/metrics/latest", response_model=StressTestMetricsRead | None)
async def get_latest_metrics(
    test_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    m = await StressTestService.get_latest_metrics(str(test_id), session)
    return StressTestMetricsRead.model_validate(m) if m else None
