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
        ("https://drive.google.com/drive/folders/1AbC_dEf-GHi", "1AbC_dEf-GHi"),
        ("https://drive.google.com/drive/folders/1AbC_dEf-GHi?usp=drive_link", "1AbC_dEf-GHi"),
        ("https://drive.google.com/drive/u/0/folders/1AbC_dEf-GHi", "1AbC_dEf-GHi"),
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


def test_sheets_and_drive_clients_get_a_bounded_http_timeout():
    # googleapiclient sets no socket timeout by default. refresh_all is
    # sequential and the scheduler runs with max_instances=1, so one wedged
    # connection would stop the daily refresh permanently. Both clients must
    # be built with a bounded httplib2 timeout.
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
    captured = {}

    def fake_build(service_name, version, **kwargs):
        captured[service_name] = kwargs
        return MagicMock()

    with (
        patch("app.services.google_service.Credentials.from_service_account_info"),
        patch("app.services.google_service.build", side_effect=fake_build),
    ):
        GoogleService(valid_key)

    for service_name in ("sheets", "drive"):
        kwargs = captured[service_name]
        assert "credentials" not in kwargs  # timeout is set via the http object instead
        authed_http = kwargs["http"]
        assert authed_http.http.timeout == 30


def test_list_folder_tree_skips_an_unlistable_subfolder_and_continues():
    # One unlistable subfolder must not abort the whole walk: the files
    # discovered before and after it must still come back, and a warning
    # naming the failed folder must be logged.
    service = GoogleService.__new__(GoogleService)

    def fake_list_children(parent_id):
        if parent_id == "ROOT":
            return [
                {"id": "SUB", "name": "Bad", "mimeType": "application/vnd.google-apps.folder"},
                {"id": "F1", "name": "Doc", "mimeType": "application/vnd.google-apps.document", "webViewLink": "u"},
            ]
        if parent_id == "SUB":
            raise GoogleAccessError("cannot list folder SUB: permission denied")
        raise AssertionError(f"unexpected parent {parent_id}")

    service._list_children = MagicMock(side_effect=fake_list_children)

    with patch("app.services.google_service.log") as mock_log:
        files, skipped = service.list_folder_tree("ROOT", 500)

    assert [f["id"] for f in files] == ["F1"]
    assert skipped == 0
    assert mock_log.warning.called
    warning_text = " ".join(str(c) for c in mock_log.warning.call_args_list)
    assert "SUB" in warning_text


def test_list_folder_tree_propagates_when_the_root_folder_is_unlistable():
    # A failure listing the root itself means the configured folder id is
    # wrong; that must still surface as an error (HTTP 400), not be silently
    # swallowed.
    service = GoogleService.__new__(GoogleService)
    service._list_children = MagicMock(side_effect=GoogleAccessError("cannot list folder ROOT: not found"))

    with pytest.raises(GoogleAccessError):
        service.list_folder_tree("ROOT", 500)


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
