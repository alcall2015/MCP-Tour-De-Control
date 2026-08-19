from datetime import date

import pytest

from app.utils.suivi_parser import normalize_key, parse_date, parse_suivi_rows, parse_value


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("avancement", "avancement"),
        ("  Avancement  ", "avancement"),
        ("Budget consommé", "budget_consomme"),
        ("PROCHAIN JALON", "prochain_jalon"),
        ("décision_attendue", "decision_attendue"),
        ("Coût / mois", "cout_mois"),
    ],
)
def test_normalize_key(raw, expected):
    assert normalize_key(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("72", 72.0),
        ("72%", 72.0),
        ("8400", 8400.0),
        ("8 400", 8400.0),
        ("8\u00a0400", 8400.0),  # non-breaking space, as Sheets exports it
        ("8,400", 8400.0),
        ("8400,50", 8400.5),
        ("8.400,50", 8400.5),
        ("8,400.50", 8400.5),
        ("12000 €", 12000.0),
        ("-250", -250.0),
    ],
)
def test_parse_value_numbers(raw, expected):
    assert parse_value(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-08-28", "2026-08-28"),
        ("Fabien", "Fabien"),
        ("moyen", "moyen"),
        ("Arbitrer le contrat X", "Arbitrer le contrat X"),
        ("", ""),
        ("  ", ""),
    ],
)
def test_parse_value_strings(raw, expected):
    assert parse_value(raw) == expected


def test_parse_date():
    assert parse_date("2026-08-28") == date(2026, 8, 28)
    assert parse_date("28/08/2026") is None
    assert parse_date("Fabien") is None
    assert parse_date(72.0) is None


def test_parse_suivi_rows():
    rows = [
        ["avancement", "72"],
        ["Budget consommé", "8 400"],
        ["budget_total", "12000"],
        ["prochain_jalon", "2026-08-28"],
        ["responsable", "Fabien"],
    ]
    assert parse_suivi_rows(rows) == {
        "avancement": 72.0,
        "budget_consomme": 8400.0,
        "budget_total": 12000.0,
        "prochain_jalon": "2026-08-28",
        "responsable": "Fabien",
    }


def test_parse_suivi_rows_skips_empty_and_keeps_last_duplicate():
    rows = [
        ["avancement", "40"],
        [],
        ["", "orphan value"],
        ["   ", "blank key"],
        ["missing value column"],
        ["avancement", "55"],
    ]
    assert parse_suivi_rows(rows) == {"avancement": 55.0, "missing_value_column": ""}
