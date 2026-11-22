import sqlite3
from pathlib import Path

import pytest

import analysis
import db
import scraper

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "sample" / "demo_results.csv"


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "RAW_CSV_DIR", tmp_path / "raw_csv")
    c = db.connect(tmp_path / "t.db")
    scraper.import_csv(c, DEMO)
    db.rebuild_clean(c)
    return c


def test_raw_is_insert_only(con):
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE raw_performances SET mark='1.00'")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM raw_performances")


def test_reimport_is_noop(con):
    before = con.execute("SELECT COUNT(*) FROM raw_performances").fetchone()[0]
    assert scraper.import_csv(con, DEMO) == 0
    assert con.execute("SELECT COUNT(*) FROM raw_performances").fetchone()[0] == before


def test_season_best_excludes_wind_and_hand(con):
    df = db.load_performances(con)
    t = analysis.team_table(df, "2026 Outdoor", ([], {}))
    row = t[(t["Athlete"] == "Demo Sprinter A") & (t["Event"] == "100m")].iloc[0]
    assert row["Season best"] == "10.39"       # not 10.31w (+3.2) or 10.2h
    t2 = analysis.team_table(df, "2026 Outdoor", ([], {}), include_flagged=True)
    row2 = t2[(t2["Athlete"] == "Demo Sprinter A") & (t2["Event"] == "100m")].iloc[0]
    assert row2["Season best"] == "10.20"


def test_field_best_is_highest_and_indoor_outdoor_separate(con):
    df = db.load_performances(con)
    t = analysis.team_table(df, "2026 Indoor", ([], {}))
    lj = t[(t["Athlete"] == "Demo Jumper D") & (t["Event"] == "LJ")].iloc[0]
    assert lj["Season best"] == "7.28m"        # 23-10.75 beats 7.21m
    assert lj["PR"] == "7.28m"                 # outdoor 7.35m is a different season type


def test_lifetime_pr_spans_seasons(con):
    df = db.load_performances(con)
    t = analysis.team_table(df, "2025 Outdoor", ([], {}))
    row = t.iloc[0]
    assert row["Season best"] == "10.61" and row["PR"] == "10.39" and not row["New PR"]


def test_standards_gap_and_sort(con, tmp_path):
    std = tmp_path / "s.yaml"
    std.write_text('standards: ["A"]\noutdoor:\n  men:\n    100m: {"A": "10.00"}\n    LJ: {"A": "8.00m"}\n')
    standards = analysis.load_standards(std)
    df = db.load_performances(con)
    t = analysis.team_table(df, "2026 Outdoor", standards, gender="men")
    assert list(t["Event"][:2]) == ["100m", "LJ"]     # 3.9% off beats 8.1% off
    assert t.iloc[0]["% off A"] == pytest.approx(3.9)
    assert t.iloc[1]["% off A"] == pytest.approx(8.13, abs=0.01)


def test_blank_standards_template_loads_empty():
    names, lookup = analysis.load_standards(ROOT / "standards.yaml")
    assert names == ["Big Ten", "NCAA"] and lookup == {}


def test_bad_standard_raises(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text('outdoor:\n  men:\n    100m: {"A": "fast"}\n')
    with pytest.raises(ValueError):
        analysis.load_standards(p)


def test_progression_marks_pr(con):
    df = db.load_performances(con)
    key = df[df["athlete"] == "Demo Sprinter A"]["athlete_key"].iloc[0]
    p = analysis.progression(df, key, "100m", season="2026 Outdoor")
    assert p["is_pr"].sum() == 1
    assert p[p["is_pr"]]["mark"].iloc[0] == "10.39"
    assert "wind-aided" in set(p["note"]) and "hand time" in set(p["note"])
