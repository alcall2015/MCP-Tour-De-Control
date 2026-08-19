import json
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.google_service import (
    GoogleAccessError,
    GoogleService,
    detect_kind,
    parse_file_id,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://docs.google.com/spreadsheets/d/ABC123def/edit#gid=0", "ABC123def"),
        ("https://docs.google.com/document/d/XYZ789/edit", "XYZ789"),
        ("https://drive.google.com/file/d/FILE42/view?usp=sharing", "FILE42"),
        ("https://drive.google.com/open?id=OPEN99", "OPEN99"),
        ("https://example.com/not-google", None),
        ("", None),
    ],
)
def test_parse_file_id(url, expected):
    assert parse_file_id(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://docs.google.com/spreadsheets/d/A/edit", "sheet"),
        ("https://docs.google.com/document/d/A/edit", "doc"),
        ("https://docs.google.com/presentation/d/A/edit", "slide"),
        ("https://drive.google.com/file/d/A/view", "drive"),
        ("https://example.com/x", "other"),
    ],
)
def test_detect_kind(url, expected):
    assert detect_kind(url) == expected


def test_read_suivi_parses_rows():
    service = GoogleService.__new__(GoogleService)
    sheets = MagicMock()
    sheets.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [["avancement", "72"], ["budget_total", "12000"]]
    }
    service._sheets = sheets

    assert service.read_suivi("ABC") == {"avancement": 72.0, "budget_total": 12000.0}


def test_read_suivi_empty_tab_returns_empty_dict():
    service = GoogleService.__new__(GoogleService)
    sheets = MagicMock()
    sheets.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {}
    service._sheets = sheets

    assert service.read_suivi("ABC") == {}


def test_read_suivi_wraps_api_errors():
    service = GoogleService.__new__(GoogleService)
    sheets = MagicMock()
    sheets.spreadsheets.return_value.values.return_value.get.return_value.execute.side_effect = RuntimeError(
        "Unable to parse range: SUIVI!A:B"
    )
    service._sheets = sheets

    with pytest.raises(GoogleAccessError) as exc:
        service.read_suivi("ABC")
    assert "SUIVI" in str(exc.value)


def test_get_modified_time_parses_rfc3339():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    drive.files.return_value.get.return_value.execute.return_value = {
        "modifiedTime": "2026-08-17T09:12:44.000Z"
    }
    service._drive = drive

    assert service.get_modified_time("ABC") == datetime(2026, 8, 17, 9, 12, 44, tzinfo=timezone.utc)


def test_invalid_service_account_key_raises():
    with pytest.raises(GoogleAccessError):
        GoogleService("{not valid json")


def test_get_modified_time_returns_none_when_absent():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    drive.files.return_value.get.return_value.execute.return_value = {}
    service._drive = drive

    assert service.get_modified_time("ABC") is None


def test_build_failure_raises_google_access_error():
    valid_key = json.dumps(
        {
            "type": "service_account",
            "project_id": "p",
            "private_key_id": "k",
            "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
            "client_email": "svc@p.iam.gserviceaccount.com",
            "client_id": "1",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    with (
        patch("app.services.google_service.Credentials.from_service_account_info"),
        patch("app.services.google_service.build", side_effect=RuntimeError("discovery unreachable")),
    ):
        with pytest.raises(GoogleAccessError):
            GoogleService(valid_key)
