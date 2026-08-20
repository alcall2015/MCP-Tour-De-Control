"""Read-only Google Sheets/Drive access through a service account."""

import json
import re
from datetime import datetime, timezone

import httplib2
import structlog
from google.oauth2.service_account import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

from app.services.text_extractor import FOLDER_MIME

log = structlog.get_logger()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# googleapiclient sets no socket timeout by default. refresh_all is sequential
# and the scheduler runs with max_instances=1, so one wedged connection would
# otherwise stop the daily refresh permanently until the backend is restarted.
HTTP_TIMEOUT_SECONDS = 30

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

    def __init__(self, sa_key_json: str):
        try:
            info = json.loads(sa_key_json)
            credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as exc:
            raise GoogleAccessError(f"invalid service account key: {exc}") from exc

        try:
            # A bounded httplib2 timeout, passed via the http= kwarg (instead
            # of credentials=) so a hung connection raises rather than blocking
            # the refresh run forever.
            authed_http = AuthorizedHttp(
                credentials, http=httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS)
            )
            self._sheets = build("sheets", "v4", http=authed_http, cache_discovery=False)
            self._drive = build("drive", "v3", http=authed_http, cache_discovery=False)
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

    _LIST_FIELDS = "nextPageToken, files(id, name, mimeType, webViewLink, modifiedTime, lastModifyingUser/displayName)"

    def list_folder_tree(self, folder_id: str, max_files: int) -> tuple[list[dict], int]:
        """Walk a folder breadth-first. Returns (files, number skipped by the cap).

        `section` is the name of the root's immediate subfolder a file descends
        from, or None for files sitting directly in the root.
        """
        queue: list[tuple[str, str | None]] = [(folder_id, None)]
        files: list[dict] = []
        skipped = 0

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
                if entry.get("mimeType") == FOLDER_MIME:
                    # The first subfolder level names the section; deeper folders inherit it.
                    queue.append((entry_id, section or entry.get("name")))
                elif len(files) < max_files:
                    files.append(
                        {
                            "id": entry_id,
                            "name": entry.get("name", ""),
                            "mimeType": entry.get("mimeType", ""),
                            "webViewLink": entry.get("webViewLink", ""),
                            "modifiedTime": entry.get("modifiedTime"),
                            "author": (entry.get("lastModifyingUser") or {}).get("displayName"),
                            "section": section,
                        }
                    )
                else:
                    skipped += 1

        return files, skipped

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
            data = self._drive.files().export(fileId=file_id, mimeType="text/plain").execute()
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
                .execute()
            )
        except Exception as exc:
            raise GoogleAccessError(f"cannot read tabs of {file_id}: {exc}") from exc

        ranges = result.get("valueRanges", [])
        return [(title, ranges[i].get("values", []) if i < len(ranges) else []) for i, title in enumerate(titles)]
