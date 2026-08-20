"""Read model for the activity page. Queries only — the scanner does the writing."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Config, DocumentActivity, TrackedDocument

UNGROUPED = "Ungrouped"
WEEKS_BACK = 52

# Timezone-aware sentinel: every stored timestamp is aware, and mixing a naive
# datetime.min into the same sort would raise as soon as the two are compared.
NEVER = datetime.min.replace(tzinfo=timezone.utc)


def heatmap_span(today: date) -> tuple[date, date]:
    """The grid's exact span: the Monday 52 weeks before this week, through today.

    Aligning on a Monday is what keeps the first column whole; a span of plain
    365 days would render a partial column on the left.
    """
    week_start = today - timedelta(days=today.weekday())
    return week_start - timedelta(weeks=WEEKS_BACK), today


class ActivityView:
    @staticmethod
    async def sections(session: AsyncSession) -> list[dict]:
        """Documents grouped by section, each with its most recent activity."""
        documents = (
            await session.execute(select(TrackedDocument).order_by(TrackedDocument.name))
        ).scalars().all()

        latest = await ActivityView._latest_activity(session)

        grouped: dict[str, list[dict]] = {}
        for doc in documents:
            row = latest.get(doc.id)
            grouped.setdefault(doc.section or UNGROUPED, []).append(
                {
                    "id": doc.id,
                    "name": doc.name,
                    "mime_type": doc.mime_type,
                    "web_url": doc.web_url,
                    "section": doc.section,
                    "last_modified_at": doc.last_modified_at,
                    "last_author": doc.last_author,
                    "line_count": doc.line_count,
                    "is_present": doc.is_present,
                    "last_error": doc.last_error,
                    "last_activity_day": row.day if row else None,
                    "last_added": row.added if row else 0,
                    "last_removed": row.removed if row else 0,
                }
            )

        # Most recently modified first; never-modified documents fall to the end.
        for docs in grouped.values():
            docs.sort(key=lambda d: d["last_modified_at"] or NEVER, reverse=True)

        # Ungrouped always trails; the named sections lead, most recently touched first.
        named = sorted(
            (name for name in grouped if name != UNGROUPED),
            key=lambda name: max(
                (d["last_modified_at"] for d in grouped[name] if d["last_modified_at"]),
                default=NEVER,
            ),
            reverse=True,
        )
        ordered = named + ([UNGROUPED] if UNGROUPED in grouped else [])
        return [{"name": name, "documents": grouped[name]} for name in ordered]

    @staticmethod
    async def _latest_activity(session: AsyncSession) -> dict:
        """The most recent activity row per document, keyed by document id."""
        rows = (
            await session.execute(
                select(DocumentActivity).order_by(DocumentActivity.day.desc())
            )
        ).scalars().all()
        latest: dict = {}
        for row in rows:
            latest.setdefault(row.document_id, row)
        return latest

    @staticmethod
    async def heatmap(session: AsyncSession, today: date | None = None) -> dict:
        """One entry per day across the grid's span, absent days filled with zero."""
        today = today or date.today()
        start, end = heatmap_span(today)

        result = await session.execute(
            select(
                DocumentActivity.day,
                func.sum(DocumentActivity.added),
                func.sum(DocumentActivity.removed),
            )
            .where(DocumentActivity.day >= start, DocumentActivity.day <= end)
            .group_by(DocumentActivity.day)
        )
        totals = {day: (int(added or 0), int(removed or 0)) for day, added, removed in result.all()}

        days = []
        total_changes = 0
        cursor = start
        while cursor <= end:
            added, removed = totals.get(cursor, (0, 0))
            days.append({"day": cursor, "added": added, "removed": removed, "total": added + removed})
            total_changes += added + removed
            cursor += timedelta(days=1)

        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        return {
            "days": days,
            "total_changes": total_changes,
            "last_scan_at": config.last_scan_at if config else None,
        }
