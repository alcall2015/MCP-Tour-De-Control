import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(max_length=200)
    description: str | None = None
    position: int = 0
    stale_days: int = Field(default=14, ge=1)
    budget_warn_pct: int = Field(default=90, ge=1, le=100)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    position: int | None = None
    stale_days: int | None = Field(default=None, ge=1)
    budget_warn_pct: int | None = Field(default=None, ge=1, le=100)


class ProjectLinkCreate(BaseModel):
    label: str
    url: str
    is_kpi_source: bool = False
    position: int = 0


class ProjectLinkUpdate(BaseModel):
    label: str | None = None
    url: str | None = None
    is_kpi_source: bool | None = None
    position: int | None = None


class ProjectLinkRead(BaseModel):
    id: uuid.UUID
    label: str
    url: str
    kind: str
    is_kpi_source: bool
    position: int

    model_config = {"from_attributes": True}


class ProjectStatusRead(BaseModel):
    level: str
    reason: str


class ProjectSnapshotRead(BaseModel):
    captured_at: datetime
    metrics: dict | None
    error: str | None

    model_config = {"from_attributes": True}


class ProjectView(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    position: int
    stale_days: int
    budget_warn_pct: int
    links: list[ProjectLinkRead]
    status: ProjectStatusRead
    metrics: dict | None
    trends: dict
    sparkline: list[float]
    captured_at: datetime | None
    metrics_captured_at: datetime | None
    source_modified_at: datetime | None
    error: str | None


class ProjectDetail(ProjectView):
    history: list[ProjectSnapshotRead]


class PendingDecision(BaseModel):
    project_id: uuid.UUID
    project_name: str
    decision: str


class BudgetSummary(BaseModel):
    consumed: float
    total: float
    remaining: float
    projects_counted: int


class RefreshResult(BaseModel):
    refreshed: int
