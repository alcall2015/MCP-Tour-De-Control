"""Parsing of the SUIVI key/value tab. Pure functions, no I/O."""

import re
import unicodedata
from datetime import date, datetime

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FR_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_NUMERIC_RE = re.compile(r"^-?[\d.,]+$")


def normalize_key(raw: str) -> str:
    """Lowercase, strip accents, turn any run of non-alphanumerics into a single underscore."""
    text = unicodedata.normalize("NFKD", str(raw).strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def parse_value(raw) -> float | str:
    """Numbers become floats; everything else is returned as a trimmed string.

    ISO dates stay strings so the result is JSON-serialisable for the JSONB column.
    """
    value = str(raw).strip()
    if not value:
        return ""
    if _ISO_DATE_RE.match(value):
        return value
    number = _parse_number(value)
    return value if number is None else number


def parse_date(value) -> date | None:
    """Convert a date string to a date. Anything else, or not a real calendar date, returns None.

    Accepts ISO `YYYY-MM-DD` (Sheets API's raw value) and French `DD/MM/YYYY`
    (how the Sheets API returns a cell as displayed on a French-locale
    spreadsheet). On an ambiguous DD/MM/YYYY that could also read as
    MM/DD/YYYY, the day-first (French) reading wins.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()

    if _ISO_DATE_RE.match(text):
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None

    match = _FR_DATE_RE.match(text)
    if match:
        day, month, year = (int(part) for part in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    return None


def parse_suivi_rows(rows: list[list]) -> dict[str, float | str]:
    """Turn SUIVI!A:B rows into a metrics dict. Blank keys are skipped, last duplicate wins."""
    metrics: dict[str, float | str] = {}
    for row in rows:
        if not row:
            continue
        key = normalize_key(row[0])
        if not key:
            continue
        raw_value = row[1] if len(row) > 1 else ""
        metrics[key] = parse_value(raw_value)
    return metrics


def _parse_number(value: str) -> float | None:
    """Parse a spreadsheet number: thousands separators, comma decimals, % and currency symbols."""
    # \s is Unicode-aware in Python, so it also strips the non-breaking spaces Sheets emits.
    cleaned = re.sub(r"[€$£%\s]", "", value)
    if not cleaned or not _NUMERIC_RE.match(cleaned):
        return None

    if "." in cleaned and "," in cleaned:
        # Whichever separator comes last is the decimal one.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        head, _, tail = cleaned.rpartition(",")
        # "8400,50" is a decimal; "8,400" is a thousands separator.
        cleaned = f"{head}.{tail}" if len(tail) in (1, 2) else cleaned.replace(",", "")

    try:
        return float(cleaned)
    except ValueError:
        return None
