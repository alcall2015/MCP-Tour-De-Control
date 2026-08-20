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
    # A genuine removal is represented by a non-empty walk that no longer
    # includes the file (a decoy file is present so the walk isn't empty —
    # see test_empty_walk_with_tracked_documents_marks_nothing_absent for
    # why an empty walk must NOT be treated as "everything removed").
    await _configured(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a")):
        await DocumentScanner.scan_all(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nb")):
        await DocumentScanner.scan_all(session)
    with patch(
        "app.services.document_scanner.GoogleService",
        return_value=_google([_doc("F2", name="Autre")]),
    ):
        await DocumentScanner.scan_all(session)

    doc = (await session.execute(select(TrackedDocument).where(TrackedDocument.file_id == "F1"))).scalar_one()
    assert doc.is_present is False
    assert len((await session.execute(select(DocumentActivity))).scalars().all()) == 1


async def test_empty_walk_with_tracked_documents_marks_nothing_absent(session):
    await _configured(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a")):
        await DocumentScanner.scan_all(session)

    with (
        patch("app.services.document_scanner.GoogleService", return_value=_google([])),
        patch("app.services.document_scanner.log") as mock_log,
    ):
        walked = await DocumentScanner.scan_all(session)

    assert walked == 0
    doc = (await session.execute(select(TrackedDocument))).scalar_one()
    assert doc.is_present is True, "an empty walk with tracked documents is likely a misconfiguration, not a real removal"
    assert mock_log.warning.called
    warning_text = " ".join(str(c) for c in mock_log.warning.call_args_list).lower()
    assert "no files" in warning_text


async def test_empty_walk_with_no_tracked_documents_does_not_error(session):
    await _configured(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([])):
        walked = await DocumentScanner.scan_all(session)

    assert walked == 0
    assert (await session.execute(select(TrackedDocument))).scalars().all() == []


async def test_cap_hit_skips_absent_marking_for_the_run(session):
    # F1's presence in the tracked table simulates a file sitting untouched in
    # Drive but pushed out of `seen` by the 500-file cap on this run. Because
    # skipped > 0, the walk's view of the folder is known to be incomplete and
    # must not be used to conclude anything about absence.
    await _configured(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc("F1")], text="a")):
        await DocumentScanner.scan_all(session)

    with (
        patch(
            "app.services.document_scanner.GoogleService",
            return_value=_google([_doc("F2", name="Autre")], skipped=5),
        ),
        patch("app.services.document_scanner.log") as mock_log,
    ):
        await DocumentScanner.scan_all(session)

    doc = (await session.execute(select(TrackedDocument).where(TrackedDocument.file_id == "F1"))).scalar_one()
    assert doc.is_present is True, "the walk was truncated by the cap; it cannot be used to conclude F1 is gone"
    warning_text = " ".join(str(c) for c in mock_log.warning.call_args_list).lower()
    assert "skip" in warning_text and "cap" in warning_text


async def test_a_failing_file_does_not_abort_the_walk(session):
    await _configured(session)
    google = _google([_doc("F1"), _doc("F2", name="Autre")], export_error="permission denied")
    with patch("app.services.document_scanner.GoogleService", return_value=google):
        walked = await DocumentScanner.scan_all(session)

    assert walked == 2
    docs = (await session.execute(select(TrackedDocument))).scalars().all()
    assert len(docs) == 2
    assert all("permission denied" in (d.last_error or "") for d in docs)


async def test_malformed_modified_time_does_not_abort_the_walk(session):
    # A malformed Drive field (here a bad modifiedTime) must be caught and
    # recorded on the offending document's last_error, not raise out of the
    # loop and discard the whole run's already-processed files.
    await _configured(session)
    bad = _doc("F1", name="Bad")
    bad["modifiedTime"] = "not-a-real-timestamp"
    good = _doc("F2", name="Good")

    with patch("app.services.document_scanner.GoogleService", return_value=_google([bad, good])):
        walked = await DocumentScanner.scan_all(session)

    assert walked == 2
    docs = {d.file_id: d for d in (await session.execute(select(TrackedDocument))).scalars().all()}
    assert len(docs) == 2
    assert docs["F2"].last_error is None
    assert docs["F2"].line_count == 3, "the other file in the same walk must still be processed"


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


async def test_failed_rescan_preserves_last_good_content(session):
    """Verify that when a read fails, stored content is preserved and last_error is set."""
    await _configured(session)

    # First scan: succeeds
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nb\nc")):
        await DocumentScanner.scan_all(session)

    # Verify content is stored, no activity yet (first sighting)
    content = (await session.execute(select(DocumentContent))).scalar_one()
    assert content.text == "a\nb\nc"
    assert (await session.execute(select(DocumentActivity))).scalars().all() == []

    # Second scan: fails with permission error
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], export_error="permission denied")):
        await DocumentScanner.scan_all(session)

    # Verify stored content is UNCHANGED
    content = (await session.execute(select(DocumentContent))).scalar_one()
    assert content.text == "a\nb\nc", "stored content must be preserved on read failure"

    # Verify last_error is set
    doc = (await session.execute(select(TrackedDocument))).scalar_one()
    assert "permission denied" in (doc.last_error or ""), "last_error must record the failure"

    # Verify no activity row was created by the failed scan
    assert (await session.execute(select(DocumentActivity))).scalars().all() == [], \
        "no activity should be recorded when extraction fails"

    # Third scan: succeeds with slightly different text
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nb\nc\nd")):
        await DocumentScanner.scan_all(session)

    # Verify the diff is measured against the preserved content from step 1, not empty
    activity = (await session.execute(select(DocumentActivity))).scalar_one()
    assert activity.added == 1, "diff should show 1 line added (not 4), proving content was preserved"
    assert activity.removed == 0
