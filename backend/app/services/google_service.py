"""Read-only Google Sheets/Drive access through a service account."""

import json
import re
from datetime import datetime, timezone

import httplib2
import structlog
from google.oauth2.service_account import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

from app.services.text_extractor import FOLDER_MIME, SHORTCUT_MIME

log = structlog.get_logger()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# googleapiclient sets no socket timeout by default. refresh_all is sequential
# and the scheduler runs with max_instances=1, so one wedged connection would
# otherwise stop the daily refresh permanently until the backend is restarted.
HTTP_TIMEOUT_SECONDS = 30       # listing and metadata: must stay responsive
EXPORT_TIMEOUT_SECONDS = 120    # content reads: a long Doc genuinely takes time

_FILE_ID_PATTERNS = [
    re.compile(r"/d/([a-zA-Z0-9_-]+)"),
    re.compile(r"/folders/([a-zA-Z0-9_-]+)"),
    re.compile(r"[?&]id=([a-zA-Z0-9_-]+)"),
]


class GoogleAccessError(Exception):
    """Raised when credentials are invalid or a Google API call fails."""


def parse_file_id(url: str) -> str | None:
    """Extract the Google file id from a Docs/Sheets/Slides/Drive URL."""
    if not url:
        return None
    for pattern in _FILE_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def detect_kind(url: str) -> str:
    """Classify a Google URL for display purposes."""
    if "/spreadsheets/" in url:
        return "sheet"
    if "/document/" in url:
        return "doc"
    if "/presentation/" in url:
        return "slide"
    if "drive.google.com" in url:
        return "drive"
    return "other"


class GoogleService:
    """Thin wrapper over the Sheets and Drive APIs. One instance per refresh run."""

    # Default for instances built via GoogleService.__new__ (as tests do),
    # which never run __init__. HttpRequest.execute(http=None) falls back to
    # the request's own transport, so this matches current behaviour exactly.
    _export_http = None

    def __init__(self, sa_key_json: str):
        try:
            info = json.loads(sa_key_json)
            credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as exc:
            raise GoogleAccessError(f"invalid service account key: {exc}") from exc

        try:
            # A bounded httplib2 timeout, passed via the http= kwarg (instead
            # of credentials=) so a hung connection raises rather than blocking
            # the refresh run forever. Both clients are built on this short
            # transport, so every call defaults to a fast failure.
            authed_http = AuthorizedHttp(
                credentials, http=httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS)
            )
            self._sheets = build("sheets", "v4", http=authed_http, cache_discovery=False)
            self._drive = build("drive", "v3", http=authed_http, cache_discovery=False)

            # A second transport, sharing the same credentials, for calls
            # that stream document content: a long Doc export or a
            # many-row spreadsheet read genuinely needs more than
            # HTTP_TIMEOUT_SECONDS. Call sites opt in explicitly via
            # execute(http=self._export_http).
            self._export_http = AuthorizedHttp(
                credentials, http=httplib2.Http(timeout=EXPORT_TIMEOUT_SECONDS)
            )
        except Exception as exc:
            raise GoogleAccessError(f"cannot build Google API client: {exc}") from exc

    def get_modified_time(self, file_id: str) -> datetime | None:
        """Return the Drive modifiedTime of a file, or None when absent."""
        try:
            response = self._drive.files().get(fileId=file_id, fields="modifiedTime").execute()
        except Exception as exc:
            raise GoogleAccessError(f"cannot read metadata of {file_id}: {exc}") from exc
        raw = response.get("modifiedTime")
        if not raw:
            return None
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)

    _LIST_FIELDS = (
        "nextPageToken, files(id, name, mimeType, webViewLink, modifiedTime, "
        "lastModifyingUser/displayName, shortcutDetails)"
    )
    _TARGET_FIELDS = "id, name, mimeType, webViewLink, modifiedTime, lastModifyingUser/displayName"

    def list_folder_tree(self, folder_id: str, max_files: int) -> tuple[list[dict], int]:
        """Walk a folder breadth-first. Returns (files, number skipped by the cap).

        `section` is the name of the root's immediate subfolder a file descends
        from, or None for files sitting directly in the root.

        Shortcuts are resolved transparently: a shortcut to a folder is walked
        like the folder itself (using the shortcut's own name for sectioning),
        and a shortcut to a file is emitted using the target's id/mimeType/
        webViewLink/modifiedTime/author but the shortcut's own name. Because
        this can make the same target reachable more than once in a walk (two
        shortcuts to it, or the file itself plus a shortcut), entries are
        deduplicated on the resolved id: the first occurrence wins.

        Real Drive containment is acyclic, but a shortcut can target any
        folder, including an ancestor or itself. A folder id is therefore only
        ever enqueued once (`visited_folders`, seeded with the root): this
        both bounds the walk when shortcuts form a cycle and avoids listing a
        folder twice when two shortcuts point at it.
        """
        queue: list[tuple[str, str | None]] = [(folder_id, None)]
        visited_folders: set[str] = {folder_id}
        files: list[dict] = []
        skipped = 0
        seen_ids: dict[str, str] = {}

        while queue:
            parent, section = queue.pop(0)
            try:
                children = self._list_children(parent)
            except GoogleAccessError:
                if parent == folder_id:
                    # The root itself is unlistable: the configured folder id
                    # is wrong, and the caller needs that to surface as an error.
                    raise
                # One unlistable subfolder must not abort the whole walk.
                log.warning("Cannot list subfolder, skipping", folder=parent)
                continue
            for entry in children:
                entry_id = entry.get("id")
                if entry_id is None:
                    # An entry we can't identify can't be tracked (deduped, queued,
                    # or returned) at all, so drop it rather than crash the walk.
                    log.warning("Drive entry missing id, skipping", parent=parent)
                    continue

                mime_type = entry.get("mimeType")

                if mime_type == FOLDER_MIME:
                    # The first subfolder level names the section; deeper folders inherit it.
                    if entry_id not in visited_folders:
                        visited_folders.add(entry_id)
                        queue.append((entry_id, section or entry.get("name")))
                    continue

                if mime_type == SHORTCUT_MIME:
                    details = entry.get("shortcutDetails") or {}
                    target_id = details.get("targetId")
                    target_mime = details.get("targetMimeType")
                    if not target_id:
                        log.warning("Shortcut has no target, skipping", shortcut=entry.get("name"))
                        continue
                    if target_mime == FOLDER_MIME:
                        # A shortcut to a folder behaves like the folder itself,
                        # but the shortcut's own name still names the section.
                        # Same visited-folder guard as a real subfolder: a
                        # shortcut may target an ancestor (or itself), and two
                        # shortcuts may target the same folder.
                        if target_id not in visited_folders:
                            visited_folders.add(target_id)
                            queue.append((target_id, section or entry.get("name")))
                        continue

                    resolved_id = target_id
                    if self._is_duplicate(resolved_id, entry.get("name"), seen_ids):
                        continue

                    try:
                        target = self._get_target_metadata(target_id)
                    except GoogleAccessError as exc:
                        log.warning(
                            "Cannot resolve shortcut target, skipping",
                            shortcut=entry.get("name"),
                            target=target_id,
                            error=str(exc),
                        )
                        continue

                    file_entry = {
                        "id": target.get("id", target_id),
                        "name": entry.get("name", ""),
                        "mimeType": target.get("mimeType", ""),
                        "webViewLink": target.get("webViewLink", ""),
                        "modifiedTime": target.get("modifiedTime"),
                        "author": (target.get("lastModifyingUser") or {}).get("displayName"),
                        "section": section,
                    }
                else:
                    resolved_id = entry_id
                    if self._is_duplicate(resolved_id, entry.get("name"), seen_ids):
                        continue

                    file_entry = {
                        "id": entry_id,
                        "name": entry.get("name", ""),
                        "mimeType": mime_type or "",
                        "webViewLink": entry.get("webViewLink", ""),
                        "modifiedTime": entry.get("modifiedTime"),
                        "author": (entry.get("lastModifyingUser") or {}).get("displayName"),
                        "section": section,
                    }

                seen_ids[resolved_id] = file_entry["name"]
                if len(files) < max_files:
                    files.append(file_entry)
                else:
                    skipped += 1

        return files, skipped

    @staticmethod
    def _is_duplicate(resolved_id: str, name: str | None, seen_ids: dict[str, str]) -> bool:
        """True (after logging a warning) when resolved_id was already emitted in this walk.

        Shared by the shortcut-to-file and plain-file branches of
        list_folder_tree so the dedup check and its warning cannot drift
        apart between the two paths.
        """
        if resolved_id not in seen_ids:
            return False
        log.warning(
            "Duplicate document in walk, skipping",
            duplicate=name,
            kept=seen_ids[resolved_id],
            id=resolved_id,
        )
        return True

    def _get_target_metadata(self, file_id: str) -> dict:
        """Fetch the metadata of a shortcut's target file."""
        try:
            return self._drive.files().get(fileId=file_id, fields=self._TARGET_FIELDS).execute()
        except Exception as exc:
            raise GoogleAccessError(f"cannot read metadata of {file_id}: {exc}") from exc

    def _list_children(self, parent_id: str) -> list[dict]:
        """Every non-trashed child of a folder, following pagination."""
        entries: list[dict] = []
        page_token = None
        while True:
            try:
                response = (
                    self._drive.files()
                    .list(
                        q=f"'{parent_id}' in parents and trashed = false",
                        fields=self._LIST_FIELDS,
                        pageSize=1000,
                        pageToken=page_token,
                    )
                    .execute()
                )
            except Exception as exc:
                raise GoogleAccessError(f"cannot list folder {parent_id}: {exc}") from exc
            entries.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return entries

    def export_text(self, file_id: str) -> str:
        """Export a Google Doc as plain text."""
        try:
            data = (
                self._drive.files()
                .export(fileId=file_id, mimeType="text/plain")
                .execute(http=self._export_http)
            )
            return data.decode("utf-8") if isinstance(data, bytes) else str(data)
        except Exception as exc:
            raise GoogleAccessError(f"cannot export {file_id} as text: {exc}") from exc

    def read_all_tabs(self, file_id: str) -> list[tuple[str, list[list]]]:
        """Every tab of a spreadsheet as (title, rows).

        Drive's CSV export would silently return only the first tab, so this
        goes through the Sheets API instead.
        """
        try:
            meta = (
                self._sheets.spreadsheets()
                .get(spreadsheetId=file_id, fields="sheets.properties.title")
                .execute()
            )
            titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
            if not titles:
                return []
            result = (
                self._sheets.spreadsheets()
                .values()
                .batchGet(spreadsheetId=file_id, ranges=titles)
                .execute(http=self._export_http)
            )
        except Exception as exc:
            raise GoogleAccessError(f"cannot read tabs of {file_id}: {exc}") from exc

        ranges = result.get("valueRanges", [])
        return [(title, ranges[i].get("values", []) if i < len(ranges) else []) for i, title in enumerate(titles)]
