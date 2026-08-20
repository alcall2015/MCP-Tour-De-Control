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
