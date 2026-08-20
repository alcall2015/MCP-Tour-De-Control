import uuid
from datetime import date, datetime

from pydantic import BaseModel


class DocumentRead(BaseModel):
    id: uuid.UUID
    name: str
    mime_type: str
    web_url: str
    section: str | None
    last_modified_at: datetime | None
    last_author: str | None
    line_count: int | None
    is_present: bool
    last_error: str | None
    last_activity_day: date | None
    last_added: int
    last_removed: int


class SectionRead(BaseModel):
    name: str
    documents: list[DocumentRead]


class HeatmapDay(BaseModel):
    day: date
    added: int
    removed: int
    total: int


class HeatmapRead(BaseModel):
    days: list[HeatmapDay]
    total_changes: int
    last_scan_at: datetime | None


class ScanResult(BaseModel):
    walked: int
