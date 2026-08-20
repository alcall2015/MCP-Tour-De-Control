"""Read-only Google Sheets/Drive access through a service account."""

import json
import re
from datetime import datetime, timezone

import httplib2
from google.oauth2.service_account import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

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
