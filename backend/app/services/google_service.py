"""Read-only Google Sheets/Drive access through a service account."""

import json
import re
from datetime import datetime, timezone

import structlog
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from app.utils.suivi_parser import parse_suivi_rows

log = structlog.get_logger()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

SUIVI_RANGE = "SUIVI!A:B"

_FILE_ID_PATTERNS = [
    re.compile(r"/d/([a-zA-Z0-9_-]+)"),
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

        self._sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self._drive = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def read_suivi(self, file_id: str) -> dict:
        """Read SUIVI!A:B and return the parsed metrics dict."""
        try:
            response = (
                self._sheets.spreadsheets()
                .values()
                .get(spreadsheetId=file_id, range=SUIVI_RANGE)
                .execute()
            )
        except Exception as exc:
            raise GoogleAccessError(f"cannot read {SUIVI_RANGE} of {file_id}: {exc}") from exc
        return parse_suivi_rows(response.get("values", []))

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
