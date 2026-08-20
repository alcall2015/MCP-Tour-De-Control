import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from unittest.mock import MagicMock

import pytest

from app.services.google_service import GoogleAccessError, GoogleService
from app.services.text_extractor import DOC_MIME, SHEET_MIME, is_diffable, sheet_text


def test_is_diffable():
    assert is_diffable(DOC_MIME) is True
    assert is_diffable(SHEET_MIME) is True
    assert is_diffable("application/pdf") is False
    assert is_diffable("application/vnd.google-apps.folder") is False


def test_sheet_text_prefixes_every_row_with_its_tab():
    tabs = [("SUIVI", [["avancement", "72"], ["budget", "8400"]])]
    assert sheet_text(tabs) == "SUIVI\tavancement\t72\nSUIVI\tbudget\t8400"


def test_sheet_text_covers_every_tab():
    tabs = [("Notes", [["a"]]), ("Budget", [["b"]])]
    assert sheet_text(tabs) == "Notes\ta\nBudget\tb"


def test_sheet_text_skips_fully_blank_rows():
    tabs = [("T", [["a"], ["", "  "], [], ["b"]])]
    assert sheet_text(tabs) == "T\ta\nT\tb"


def test_sheet_text_on_empty_input():
    assert sheet_text([]) == ""
    assert sheet_text([("T", [])]) == ""


def test_export_text_decodes_bytes():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    drive.files.return_value.export.return_value.execute.return_value = b"ligne 1\nligne 2"
    service._drive = drive

    assert service.export_text("DOC1") == "ligne 1\nligne 2"


def test_export_text_wraps_api_errors():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    drive.files.return_value.export.return_value.execute.side_effect = RuntimeError("403 denied")
    service._drive = drive

    with pytest.raises(GoogleAccessError) as exc:
        service.export_text("DOC1")
    assert "DOC1" in str(exc.value)


def test_read_all_tabs_returns_title_and_rows():
    service = GoogleService.__new__(GoogleService)
    sheets = MagicMock()
    sheets.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Notes"}}, {"properties": {"title": "Budget"}}]
    }
    sheets.spreadsheets.return_value.values.return_value.batchGet.return_value.execute.return_value = {
        "valueRanges": [{"values": [["a"]]}, {"values": [["b"]]}]
    }
    service._sheets = sheets

    assert service.read_all_tabs("SHEET1") == [("Notes", [["a"]]), ("Budget", [["b"]])]


def test_read_all_tabs_on_a_spreadsheet_with_no_tabs():
    service = GoogleService.__new__(GoogleService)
    sheets = MagicMock()
    sheets.spreadsheets.return_value.get.return_value.execute.return_value = {}
    service._sheets = sheets

    assert service.read_all_tabs("SHEET1") == []


def test_list_folder_tree_assigns_the_top_subfolder_as_section():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()

    def children(q, **kwargs):
        page = MagicMock()
        if "'ROOT' in parents" in q:
            page.execute.return_value = {
                "files": [
                    {"id": "SUB", "name": "Soutien-Scolaire", "mimeType": "application/vnd.google-apps.folder"},
                    {"id": "TOP", "name": "Note racine", "mimeType": DOC_MIME, "webViewLink": "u1"},
                ]
            }
        elif "'SUB' in parents" in q:
            page.execute.return_value = {
                "files": [
                    {"id": "DEEP", "name": "Sous-dossier", "mimeType": "application/vnd.google-apps.folder"},
                ]
            }
        else:
            page.execute.return_value = {
                "files": [{"id": "F1", "name": "Recherche", "mimeType": DOC_MIME, "webViewLink": "u2"}]
            }
        return page

    drive.files.return_value.list.side_effect = children
    service._drive = drive

    files, skipped = service.list_folder_tree("ROOT", max_files=100)

    by_id = {f["id"]: f for f in files}
    assert skipped == 0
    assert by_id["TOP"]["section"] is None
    assert by_id["F1"]["section"] == "Soutien-Scolaire"


def test_list_children_follows_pagination_across_pages():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()

    first_page = {
        "files": [{"id": "F1", "name": "doc 1", "mimeType": DOC_MIME, "webViewLink": "u1"}],
        "nextPageToken": "PAGE2",
    }
    second_page = {
        "files": [{"id": "F2", "name": "doc 2", "mimeType": DOC_MIME, "webViewLink": "u2"}],
    }
    responses = [first_page, second_page]

    def list_call(q, fields, pageSize, pageToken):
        page = MagicMock()
        page.execute.return_value = responses.pop(0)
        return page

    drive.files.return_value.list.side_effect = list_call
    service._drive = drive

    entries = service._list_children("ROOT")

    ids = {e["id"] for e in entries}
    assert ids == {"F1", "F2"}

    calls = drive.files.return_value.list.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["pageToken"] is None
    assert calls[1].kwargs["pageToken"] == "PAGE2"


def test_list_children_wraps_api_errors():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    drive.files.return_value.list.return_value.execute.side_effect = RuntimeError("403 insufficient permissions")
    service._drive = drive

    with pytest.raises(GoogleAccessError) as exc:
        service.list_folder_tree("ROOT", max_files=100)
    assert "ROOT" in str(exc.value)


def test_list_folder_tree_reports_what_the_cap_skipped():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    page = MagicMock()
    page.execute.return_value = {
        "files": [
            {"id": f"F{i}", "name": f"doc {i}", "mimeType": DOC_MIME, "webViewLink": "u"}
            for i in range(10)
        ]
    }
    drive.files.return_value.list.return_value = page
    service._drive = drive

    files, skipped = service.list_folder_tree("ROOT", max_files=4)

    assert len(files) == 4
    assert skipped == 6


def test_list_folder_tree_returns_every_field_with_an_author():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    page = MagicMock()
    page.execute.return_value = {
        "files": [
            {
                "id": "F1",
                "name": "Note racine",
                "mimeType": DOC_MIME,
                "webViewLink": "https://docs.google.com/document/d/F1/edit",
                "modifiedTime": "2026-08-17T10:00:00Z",
                "lastModifyingUser": {"displayName": "Fabien"},
            }
        ]
    }
    drive.files.return_value.list.return_value = page
    service._drive = drive

    files, skipped = service.list_folder_tree("ROOT", max_files=100)

    assert skipped == 0
    assert len(files) == 1
    assert files[0] == {
        "id": "F1",
        "name": "Note racine",
        "mimeType": DOC_MIME,
        "webViewLink": "https://docs.google.com/document/d/F1/edit",
        "modifiedTime": "2026-08-17T10:00:00Z",
        "author": "Fabien",
        "section": None,
    }


def test_list_folder_tree_author_is_none_when_last_modifying_user_absent():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    page = MagicMock()
    page.execute.return_value = {
        "files": [
            {
                "id": "F1",
                "name": "Note racine",
                "mimeType": DOC_MIME,
                "webViewLink": "u1",
                "modifiedTime": "2026-08-17T10:00:00Z",
            }
        ]
    }
    drive.files.return_value.list.return_value = page
    service._drive = drive

    files, _ = service.list_folder_tree("ROOT", max_files=100)

    assert files[0]["author"] is None


def test_export_text_raises_google_access_error_on_invalid_utf8():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    drive.files.return_value.export.return_value.execute.return_value = b"\xff\xfe invalid"
    service._drive = drive

    with pytest.raises(GoogleAccessError) as exc:
        service.export_text("DOC1")
    assert "DOC1" in str(exc.value)


def test_list_folder_tree_skips_entries_missing_id():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    page = MagicMock()
    page.execute.return_value = {
        "files": [
            {"name": "no id here", "mimeType": DOC_MIME, "webViewLink": "u"},
            {"id": "F1", "name": "good doc", "mimeType": DOC_MIME, "webViewLink": "u"},
        ]
    }
    drive.files.return_value.list.return_value = page
    service._drive = drive

    files, skipped = service.list_folder_tree("ROOT", max_files=100)

    assert [f["id"] for f in files] == ["F1"]
    assert skipped == 0
