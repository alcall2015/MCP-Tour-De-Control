import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import DocumentActivity, DocumentContent, TrackedDocument


async def _document(session, file_id="FILE1", name="Recherche GoogleFlow"):
    doc = TrackedDocument(
        file_id=file_id,
        name=name,
        mime_type="application/vnd.google-apps.document",
        section="Soutien-Scolaire",
        web_url=f"https://docs.google.com/document/d/{file_id}/edit",
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


async def test_document_defaults(session):
    doc = await _document(session)
    assert isinstance(doc.id, uuid.UUID)
    assert doc.is_present is True
    assert doc.line_count is None
    assert doc.last_error is None


async def test_file_id_is_unique(session):
    await _document(session)
    session.add(
        TrackedDocument(
            file_id="FILE1",
            name="Duplicate",
            mime_type="application/vnd.google-apps.document",
            web_url="https://example.com",
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_content_and_activity_cascade(session):
    doc = await _document(session)
    session.add(DocumentContent(document_id=doc.id, text="a\nb\nc"))
    session.add(
        DocumentActivity(document_id=doc.id, day=date(2026, 8, 20), added=142, removed=5)
    )
    await session.commit()

    await session.delete(doc)
    await session.commit()

    assert (await session.execute(select(DocumentContent))).scalars().all() == []
    assert (await session.execute(select(DocumentActivity))).scalars().all() == []


async def test_one_activity_row_per_document_per_day(session):
    doc = await _document(session)
    session.add(DocumentActivity(document_id=doc.id, day=date(2026, 8, 20), added=1, removed=0))
    await session.commit()

    session.add(DocumentActivity(document_id=doc.id, day=date(2026, 8, 20), added=9, removed=9))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_absent_document_keeps_its_history(session):
    doc = await _document(session)
    session.add(DocumentActivity(document_id=doc.id, day=date(2026, 8, 19), added=3, removed=1))
    await session.commit()

    doc.is_present = False
    await session.commit()

    rows = (await session.execute(select(DocumentActivity))).scalars().all()
    assert len(rows) == 1
    assert rows[0].added == 3
