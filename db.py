"""SQLite storage. Raw first, clean second.

raw_sources       one row per imported file/page (content hash = id)
raw_performances  strings exactly as found; insert-only (triggers block
                  UPDATE and DELETE, so raw data can never be overwritten)
performances      the clean table, rebuilt from raw by `rebuild_clean()`
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import parse

DEFAULT_DB = Path(__file__).parent / "data" / "tracker.db"

RAW_FIELDS = ["athlete_name", "athlete_id", "gender", "team", "event", "mark", "wind",
              "meet", "date", "season", "place", "round"]

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS raw_sources (
    source_id   TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    origin      TEXT,
    saved_path  TEXT,
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_performances (
    raw_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL REFERENCES raw_sources(source_id),
    row_num     INTEGER NOT NULL,
    {", ".join(f"{f} TEXT" for f in RAW_FIELDS)},
    imported_at TEXT NOT NULL,
    UNIQUE (source_id, row_num)
);
CREATE TRIGGER IF NOT EXISTS raw_performances_no_update
BEFORE UPDATE ON raw_performances
BEGIN SELECT RAISE(ABORT, 'raw_performances is insert-only'); END;
CREATE TRIGGER IF NOT EXISTS raw_performances_no_delete
BEFORE DELETE ON raw_performances
BEGIN SELECT RAISE(ABORT, 'raw_performances is insert-only'); END;
CREATE TRIGGER IF NOT EXISTS raw_sources_no_update
BEFORE UPDATE ON raw_sources
BEGIN SELECT RAISE(ABORT, 'raw_sources is insert-only'); END;
"""

CLEAN_COLUMNS = ["raw_id", "athlete_key", "athlete", "gender", "event_raw", "event", "event_group",
                 "mark_raw", "mark_value", "units", "status", "wind", "wind_aided", "hand_timed",
                 "legal", "meet", "date", "season_type", "season_year", "season", "place", "round"]


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(_SCHEMA)
    return con


def content_hash(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def add_raw(con: sqlite3.Connection, source_id: str, kind: str, origin: str | None,
            saved_path: str | None, rows: list[dict]) -> int:
    """Store one source and its rows. Re-importing identical content is a
    no-op. Returns the number of new raw rows."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.execute("INSERT OR IGNORE INTO raw_sources VALUES (?, ?, ?, ?, ?)",
                (source_id, kind, origin, saved_path, now))
    before = con.total_changes
    con.executemany(
        f"INSERT OR IGNORE INTO raw_performances (source_id, row_num, {', '.join(RAW_FIELDS)}, imported_at) "
        f"VALUES (?, ?, {', '.join('?' for _ in RAW_FIELDS)}, ?)",
        [(source_id, i, *[_text(r.get(f)) for f in RAW_FIELDS], now) for i, r in enumerate(rows)],
    )
    con.commit()
    return con.total_changes - before


def _text(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return None if s == "" or s.lower() == "nan" else s


def raw_rows(con: sqlite3.Connection) -> list[dict]:
    cur = con.execute(f"SELECT raw_id, {', '.join(RAW_FIELDS)} FROM raw_performances ORDER BY raw_id")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def rebuild_clean(con: sqlite3.Connection) -> int:
    """Re-derive the clean table from raw. Safe to run any time."""
    df = pd.DataFrame(parse.clean_rows(raw_rows(con)), columns=CLEAN_COLUMNS)
    df.to_sql("performances", con, if_exists="replace", index=False)
    con.commit()
    return len(df)


def load_performances(con: sqlite3.Connection) -> pd.DataFrame:
    try:
        df = pd.read_sql("SELECT * FROM performances", con)
    except Exception:  # table not built yet
        return pd.DataFrame(columns=CLEAN_COLUMNS)
    for col in ("wind_aided", "hand_timed", "legal"):
        df[col] = df[col].astype(bool)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df
