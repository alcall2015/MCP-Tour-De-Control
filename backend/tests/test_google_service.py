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


def test_init_creates_httplib2_transports_with_the_short_and_export_timeouts():
    # __init__ must build two distinct httplib2 transports: the existing
    # short one (listing/metadata) and a new long one (content exports).
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
        patch("app.services.google_service.httplib2.Http") as mock_http_cls,
        patch("app.services.google_service.AuthorizedHttp") as mock_authed_http_cls,
        patch("app.services.google_service.build", return_value=MagicMock()),
    ):
        mock_authed_http_cls.side_effect = lambda credentials, http: MagicMock(http=http)
        GoogleService(valid_key)

    timeouts = sorted(call.kwargs["timeout"] for call in mock_http_cls.call_args_list)
    assert timeouts == [30, 120]


def test_init_stores_a_distinct_export_http_not_passed_to_build():
    # build() (used for both the sheets and drive clients) must keep
    # receiving only the short-timeout transport. The long-timeout transport
    # must be stored separately on the instance, for content-reading calls
    # to opt into explicitly.
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
    captured_builds = {}

    def fake_build(service_name, version, **kwargs):
        captured_builds[service_name] = kwargs["http"]
        return MagicMock()

    with (
        patch("app.services.google_service.Credentials.from_service_account_info"),
        patch("app.services.google_service.build", side_effect=fake_build),
    ):
        service = GoogleService(valid_key)

    assert captured_builds["sheets"].http.timeout == 30
    assert captured_builds["drive"].http.timeout == 30
    assert service._export_http is not None
    assert service._export_http.http.timeout == 120
    assert service._export_http is not captured_builds["drive"]
    assert service._export_http is not captured_builds["sheets"]


def test_export_text_passes_the_export_http_transport_to_execute():
    service = GoogleService.__new__(GoogleService)
    export_http = object()  # a sentinel distinguishable from the short-timeout transport
    service._export_http = export_http
    drive = MagicMock()
    drive.files.return_value.export.return_value.execute.return_value = b"content"
    service._drive = drive

    service.export_text("DOC1")

    drive.files.return_value.export.return_value.execute.assert_called_once_with(http=export_http)


def test_export_text_falls_back_to_default_transport_when_export_http_unset():
    # A service built via __new__ (as the existing tests do) never runs
    # __init__, so it has no instance _export_http. The class attribute
    # default (None) must keep this working: HttpRequest.execute(http=None)
    # falls back to the request's own transport, matching current behaviour.
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    drive.files.return_value.export.return_value.execute.return_value = b"content"
    service._drive = drive

    result = service.export_text("DOC1")

    assert result == "content"
    drive.files.return_value.export.return_value.execute.assert_called_once_with(http=None)


def test_read_all_tabs_passes_the_export_http_only_on_batch_get():
    service = GoogleService.__new__(GoogleService)
    export_http = object()
    service._export_http = export_http
    sheets = MagicMock()
    sheets.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Notes"}}]
    }
    sheets.spreadsheets.return_value.values.return_value.batchGet.return_value.execute.return_value = {
        "valueRanges": [{"values": [["a"]]}]
    }
    service._sheets = sheets

    service.read_all_tabs("SHEET1")

    # the small metadata call must stay on the default (short-timeout) transport
    sheets.spreadsheets.return_value.get.return_value.execute.assert_called_once_with()
    # the potentially large batchGet call must use the long-timeout transport
    sheets.spreadsheets.return_value.values.return_value.batchGet.return_value.execute.assert_called_once_with(
        http=export_http
    )


def test_list_children_does_not_use_the_export_http_transport():
    service = GoogleService.__new__(GoogleService)
    service._export_http = object()  # must not leak into a small listing call
    drive = MagicMock()
    drive.files.return_value.list.return_value.execute.return_value = {"files": []}
    service._drive = drive

    service._list_children("FOLDER1")

    drive.files.return_value.list.return_value.execute.assert_called_once_with()


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
