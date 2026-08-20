"""Shape raw Google API output into comparable plain text. Pure functions, no I/O."""

FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"


def is_diffable(mime_type: str) -> bool:
    """Only Docs and Sheets yield text we can diff; everything else is listed only."""
    return mime_type in (DOC_MIME, SHEET_MIME)


def sheet_text(tabs: list[tuple[str, list[list]]]) -> str:
    """Turn every tab's rows into one text block, one line per spreadsheet row.

    Each line is prefixed with its tab name, so a row moved from one tab to
    another reads as a real change rather than as no change at all.
    """
    lines = []
    for title, rows in tabs:
        for row in rows:
            cells = [str(cell) for cell in row]
            if any(cell.strip() for cell in cells):
                lines.append("\t".join([title, *cells]))
    return "\n".join(lines)
