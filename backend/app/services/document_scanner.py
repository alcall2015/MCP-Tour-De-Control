"""Walk the tracked Drive folder, diff each file against its stored copy, persist."""

import asyncio
from datetime import date, datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Config, DocumentActivity, DocumentContent, TrackedDocument
from app.services.google_service import GoogleAccessError, GoogleService
from app.services.text_extractor import DOC_MIME, SHEET_MIME, is_diffable, sheet_text
from app.utils.crypto import decrypt_value
from app.utils.line_diff import count_changes, split_lines

log = structlog.get_logger()


class DocumentScanner:
    MAX_FILES = 500

    @staticmethod
    async def scan_all(session: AsyncSession) -> int:
        """Rescan the whole folder. Returns the number of files walked."""
        google, folder_id = await DocumentScanner._build_google(session)

        files, skipped = await asyncio.to_thread(
            google.list_folder_tree, folder_id, DocumentScanner.MAX_FILES
        )
        if skipped:
            # Never truncate silently: partial coverage must not read as complete.
            log.warning("Scan cap reached", cap=DocumentScanner.MAX_FILES, skipped=skipped)

        today = datetime.now(timezone.utc).date()
        seen: set[str] = set()

        for entry in files:
            seen.add(entry["id"])
            await DocumentScanner._process(session, google, entry, today)

        await DocumentScanner._mark_absent(session, seen)
        await session.commit()
        log.info("Activity scan finished", walked=len(files), skipped=skipped)
        return len(files)

    @staticmethod
    async def _build_google(session: AsyncSession) -> tuple[GoogleService, str]:
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if not config or not config.google_sa_key:
            raise GoogleAccessError("Google service account key not configured")
        if not config.drive_folder_id:
            raise GoogleAccessError("No Drive folder configured")
        google = await asyncio.to_thread(GoogleService, decrypt_value(config.google_sa_key))
        return google, config.drive_folder_id

    @staticmethod
    async def _process(session: AsyncSession, google: GoogleService, entry: dict, today: date) -> None:
        doc = await DocumentScanner._upsert_document(session, entry)

        if not is_diffable(entry["mimeType"]):
            return

        try:
            text = await DocumentScanner._extract(google, entry)
        except GoogleAccessError as exc:
            doc.last_error = str(exc)
            log.warning("Extraction failed", document=doc.name, error=str(exc))
            return

        new_lines = split_lines(text)
        stored = (
            await session.execute(
                select(DocumentContent).where(DocumentContent.document_id == doc.id)
            )
        ).scalar_one_or_none()

        if stored is None:
            # First sighting: record a baseline. Counting a pre-existing file's
            # whole content as "added" would put a false spike in the grid.
            session.add(DocumentContent(document_id=doc.id, text=text))
            doc.line_count = len(new_lines)
            return

        added, removed = count_changes(split_lines(stored.text), new_lines)
        if added or removed:
            await DocumentScanner._record_activity(session, doc, today, added, removed, entry.get("author"))
            stored.text = text
            stored.captured_at = datetime.now(timezone.utc)
            doc.line_count = len(new_lines)

    @staticmethod
    async def _extract(google: GoogleService, entry: dict) -> str:
        if entry["mimeType"] == DOC_MIME:
            return await asyncio.to_thread(google.export_text, entry["id"])
        tabs = await asyncio.to_thread(google.read_all_tabs, entry["id"])
        return sheet_text(tabs)

    @staticmethod
    async def _upsert_document(session: AsyncSession, entry: dict) -> TrackedDocument:
        doc = (
            await session.execute(
                select(TrackedDocument).where(TrackedDocument.file_id == entry["id"])
            )
        ).scalar_one_or_none()

        modified = entry.get("modifiedTime")
        modified_at = (
            datetime.fromisoformat(modified.replace("Z", "+00:00")).astimezone(timezone.utc)
            if modified
            else None
        )

        if doc is None:
            doc = TrackedDocument(file_id=entry["id"], name=entry["name"], mime_type=entry["mimeType"])
            session.add(doc)

        doc.name = entry["name"]
        doc.mime_type = entry["mimeType"]
        doc.section = entry.get("section")
        doc.web_url = entry.get("webViewLink", "")
        doc.last_modified_at = modified_at
        doc.last_author = entry.get("author")
        doc.is_present = True
        doc.last_error = None

        await session.flush()
        return doc

    @staticmethod
    async def _record_activity(
        session: AsyncSession,
        doc: TrackedDocument,
        day: date,
        added: int,
        removed: int,
        author: str | None,
    ) -> None:
        """Accumulate into today's row.

        A manual rescan later the same day only sees the delta since the
        previous scan, so replacing the row would erase the morning's work.
        """
        row = (
            await session.execute(
                select(DocumentActivity).where(
                    DocumentActivity.document_id == doc.id, DocumentActivity.day == day
                )
            )
        ).scalar_one_or_none()

        if row is None:
            session.add(
                DocumentActivity(
                    document_id=doc.id, day=day, added=added, removed=removed, author=author
                )
            )
        else:
            row.added += added
            row.removed += removed
            if author:
                row.author = author

    @staticmethod
    async def _mark_absent(session: AsyncSession, seen: set[str]) -> None:
        """Flag documents that left the folder. Their history is deliberately kept."""
        statement = update(TrackedDocument).where(TrackedDocument.is_present.is_(True)).values(is_present=False)
        if seen:
            statement = statement.where(TrackedDocument.file_id.not_in(seen))
        await session.execute(statement)
