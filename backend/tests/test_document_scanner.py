import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.models import Config, DocumentActivity, DocumentContent, TrackedDocument
from app.services.google_service import GoogleAccessError
from app.services.document_scanner import DocumentScanner
from app.services.text_extractor import DOC_MIME, SHEET_MIME
from app.utils.crypto import encrypt_value


async def _configured(session, folder="ROOT"):
    session.add(Config(google_sa_key=encrypt_value('{"type": "service_account"}'), drive_folder_id=folder))
    await session.commit()


def _google(files, text="a\nb\nc", skipped=0, export_error=None):
    google = MagicMock()
    google.list_folder_tree.return_value = (files, skipped)
    if export_error:
        google.export_text.side_effect = GoogleAccessError(export_error)
    else:
        google.export_text.return_value = text
    google.read_all_tabs.return_value = [("Feuille1", [["x"]])]
    return google


def _doc(file_id="F1", name="Recherche", section="Soutien-Scolaire"):
    return {
        "id": file_id,
        "name": name,
        "mimeType": DOC_MIME,
        "webViewLink": f"https://docs.google.com/document/d/{file_id}/edit",
        "modifiedTime": "2026-08-20T09:12:44.000Z",
        "author": "Fabien",
        "section": section,
    }


async def test_first_sighting_stores_a_baseline_and_no_activity(session):
    await _configured(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()])):
        walked = await DocumentScanner.scan_all(session)

    assert walked == 1
    doc = (await session.execute(select(TrackedDocument))).scalar_one()
    assert doc.name == "Recherche"
    assert doc.section == "Soutien-Scolaire"
    assert doc.last_author == "Fabien"
    assert doc.line_count == 3
    assert (await session.execute(select(DocumentContent))).scalar_one().text == "a\nb\nc"
    assert (await session.execute(select(DocumentActivity))).scalars().all() == []


async def test_second_scan_with_changes_records_them(session):
    await _configured(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nb\nc")):
        await DocumentScanner.scan_all(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nZ\nc\nd")):
        await DocumentScanner.scan_all(session)

    row = (await session.execute(select(DocumentActivity))).scalar_one()
    assert (row.added, row.removed) == (2, 1)
    assert row.author == "Fabien"


async def test_unchanged_document_writes_no_row(session):
    await _configured(session)
    for _ in range(2):
        with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()])):
            await DocumentScanner.scan_all(session)

    assert (await session.execute(select(DocumentActivity))).scalars().all() == []


async def test_same_day_rescan_accumulates_instead_of_replacing(session):
    await _configured(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a")):
        await DocumentScanner.scan_all(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nb")):
        await DocumentScanner.scan_all(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nb\nc")):
        await DocumentScanner.scan_all(session)

    row = (await session.execute(select(DocumentActivity))).scalar_one()
    assert row.added == 2, "the morning's line must survive the afternoon rescan"


async def test_vanished_document_is_marked_absent_and_keeps_history(session):
    await _configured(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a")):
        await DocumentScanner.scan_all(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nb")):
        await DocumentScanner.scan_all(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([])):
        await DocumentScanner.scan_all(session)

    doc = (await session.execute(select(TrackedDocument))).scalar_one()
    assert doc.is_present is False
    assert len((await session.execute(select(DocumentActivity))).scalars().all()) == 1


async def test_a_failing_file_does_not_abort_the_walk(session):
    await _configured(session)
    google = _google([_doc("F1"), _doc("F2", name="Autre")], export_error="permission denied")
    with patch("app.services.document_scanner.GoogleService", return_value=google):
        walked = await DocumentScanner.scan_all(session)

    assert walked == 2
    docs = (await session.execute(select(TrackedDocument))).scalars().all()
    assert len(docs) == 2
    assert all("permission denied" in (d.last_error or "") for d in docs)


async def test_non_diffable_file_is_listed_but_not_extracted(session):
    await _configured(session)
    pdf = {**_doc("P1", name="Facture"), "mimeType": "application/pdf"}
    google = _google([pdf])
    with patch("app.services.document_scanner.GoogleService", return_value=google):
        await DocumentScanner.scan_all(session)

    doc = (await session.execute(select(TrackedDocument))).scalar_one()
    assert doc.line_count is None
    google.export_text.assert_not_called()
    assert (await session.execute(select(DocumentContent))).scalars().all() == []


async def test_spreadsheet_goes_through_read_all_tabs(session):
    await _configured(session)
    sheet = {**_doc("S1", name="Planning"), "mimeType": SHEET_MIME}
    google = _google([sheet])
    with patch("app.services.document_scanner.GoogleService", return_value=google):
        await DocumentScanner.scan_all(session)

    google.read_all_tabs.assert_called_once_with("S1")
    google.export_text.assert_not_called()
    assert (await session.execute(select(DocumentContent))).scalar_one().text == "Feuille1\tx"


async def test_missing_folder_raises(session):
    session.add(Config(google_sa_key=encrypt_value('{"type": "service_account"}'), drive_folder_id=""))
    await session.commit()

    with pytest.raises(GoogleAccessError):
        await DocumentScanner.scan_all(session)


async def test_missing_key_raises(session):
    session.add(Config(google_sa_key="", drive_folder_id="ROOT"))
    await session.commit()

    with pytest.raises(GoogleAccessError):
        await DocumentScanner.scan_all(session)
