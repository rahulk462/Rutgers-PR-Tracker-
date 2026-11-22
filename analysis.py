"""Season bests, lifetime PRs, progressions and gaps to standards.

PRs and season bests use legal marks only by default: wind-aided
(> +2.0 m/s) and hand-timed marks are excluded but stay in the data.
Indoor and outdoor marks are kept apart (a 200m indoors is not compared
with a 200m outdoors), and so is cross country.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

import events
import parse

STANDARDS_FILE = Path(__file__).parent / "standards.yaml"
INDIVIDUAL_GROUPS = set(events.GROUPS)


# --- standards -------------------------------------------------------------

def load_standards(path: str | Path = STANDARDS_FILE) -> tuple[list[str], dict]:
    """Read standards.yaml. Returns (standard_names, lookup) where lookup maps
    (season_type, gender, event) -> {standard_name: numeric value}.
    Blank entries are skipped; nothing is ever filled in for you."""
    path = Path(path)
    if not path.exists():
        return [], {}
    cfg = yaml.safe_load(path.read_text()) or {}
    names = list(cfg.get("standards") or [])
    lookup: dict[tuple, dict] = {}
    for season_type in ("indoor", "outdoor", "xc"):
        for gender, evs in ((cfg.get(season_type) or {}).items()):
            g = parse.normalize_gender(gender)
            for ev_name, marks in (evs or {}).items():
                ev = events.normalize_event(str(ev_name))
                if ev is None:
                    raise ValueError(f"standards.yaml: unknown event {ev_name!r} ({season_type}/{gender})")
                for std_name, raw in (marks or {}).items():
                    if raw in (None, ""):
                        continue
                    m = parse.parse_mark(str(raw), ev)
                    if m.value is None:
                        raise ValueError(f"standards.yaml: can't read {raw!r} for {ev_name} {std_name}")
                    if std_name not in names:
                        names.append(std_name)
                    lookup.setdefault((season_type, g, ev), {})[std_name] = m.value
    return names, lookup


# --- core helpers ----------------------------------------------------------

def _usable(df: pd.DataFrame, include_flagged: bool) -> pd.DataFrame:
    ok = df["event_group"].isin(INDIVIDUAL_GROUPS) & (df["status"] == "OK") & df["mark_value"].notna()
    if not include_flagged:
        ok &= df["legal"]
    return df[ok]


def best_marks(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Best row per group, using events.sort_key so direction lives in one place."""
    if df.empty:
        return df
    keyed = df.assign(_k=[events.sort_key(v, e) for v, e in zip(df["mark_value"], df["event"])])
    idx = keyed.sort_values(["_k", "date"]).groupby(by, dropna=False).head(1).index
    return df.loc[idx]


def seasons(df: pd.DataFrame) -> list[str]:
    s = df.dropna(subset=["season"]).sort_values("date", ascending=False)["season"]
    return list(dict.fromkeys(s))


# --- team view -------------------------------------------------------------

def team_table(df: pd.DataFrame, season: str, standards: tuple[list[str], dict],
               gender: str | None = None, group: str | None = None,
               sort_by: str | None = None, include_flagged: bool = False) -> pd.DataFrame:
    """One row per athlete-event that has a mark in `season`: season best,
    lifetime PR (same season type), and % off each standard. Sorted by
    % off `sort_by` (closest to qualifying first)."""
    names, lookup = standards
    pool = _usable(df, include_flagged)
    in_season = pool[pool["season"] == season]
    if gender:
        in_season = in_season[in_season["gender"] == gender]
    if group:
        in_season = in_season[in_season["event_group"] == group]
    if in_season.empty:
        return pd.DataFrame()
    season_type = in_season["season_type"].iloc[0]

    keys = ["athlete_key", "event"]
    sb = best_marks(in_season, keys)
    pr_pool = pool[pool["season_type"] == season_type]
    pr = best_marks(pr_pool, keys).set_index(keys)

    out = []
    for _, r in sb.iterrows():
        p = pr.loc[(r["athlete_key"], r["event"])]
        row = {
            "Athlete": r["athlete"], "Gender": (r["gender"] or "").title(),
            "Group": r["event_group"], "Event": r["event"],
            "Season best": events.format_mark(r["mark_value"], r["event"]),
            "SB meet": r["meet"],
            "PR": events.format_mark(p["mark_value"], r["event"]),
            "PR date": p["date"].date().isoformat() if pd.notna(p["date"]) else "",
            "New PR": bool(r["mark_value"] == p["mark_value"]),
            "_sb": r["mark_value"], "_athlete_key": r["athlete_key"],
        }
        stds = lookup.get((season_type, r["gender"], r["event"]), {})
        for name in names:
            v = stds.get(name)
            row[f"% off {name}"] = round(events.pct_off(r["mark_value"], v, r["event"]), 2) if v else None
        out.append(row)
    table = pd.DataFrame(out)
    sort_col = f"% off {sort_by}" if sort_by else (f"% off {names[0]}" if names else None)
    if sort_col and sort_col in table:
        table = table.sort_values([sort_col, "Event", "Athlete"], na_position="last")
    else:
        table = table.sort_values(["Group", "Event", "Athlete"])
    return table.reset_index(drop=True)


# --- athlete view ----------------------------------------------------------

def athlete_events(df: pd.DataFrame, athlete_key: str, season: str | None = None) -> list[str]:
    d = df[(df["athlete_key"] == athlete_key) & df["event_group"].isin(INDIVIDUAL_GROUPS)]
    if season:
        d = d[d["season"] == season]
    order = {name: i for i, name in enumerate(events.EVENTS)}
    return sorted(d["event"].dropna().unique(), key=lambda e: order.get(e, 999))


def lifetime_pr(df: pd.DataFrame, athlete_key: str, event: str, season_type: str | None,
                include_flagged: bool = False) -> pd.Series | None:
    """The athlete's best mark in `event` for one season type, or None."""
    d = df[(df["athlete_key"] == athlete_key) & (df["event"] == event)]
    if season_type:
        d = d[d["season_type"] == season_type]
    best = best_marks(_usable(d, include_flagged), ["event"])
    return best.iloc[0] if len(best) else None


def progression(df: pd.DataFrame, athlete_key: str, event: str,
                season: str | None = None, include_flagged: bool = False) -> pd.DataFrame:
    """Every performance for one athlete/event (optionally one season), with
    the lifetime PR flagged. Flagged marks are included but marked."""
    d = df[(df["athlete_key"] == athlete_key) & (df["event"] == event)].copy()
    if season:
        d = d[d["season"] == season]
    season_type = d["season_type"].dropna().iloc[0] if season and d["season_type"].notna().any() else None
    pr = lifetime_pr(df, athlete_key, event, season_type, include_flagged)
    d["is_pr"] = d["raw_id"] == (pr["raw_id"] if pr is not None else None)
    d["mark"] = [events.format_mark(v, event) if pd.notna(v) else s
                 for v, s in zip(d["mark_value"], d["status"])]
    d["note"] = [", ".join(x for x in (("wind-aided" if w else ""), ("hand time" if h else ""),
                                      ("" if st == "OK" else st)) if x)
                 for w, h, st in zip(d["wind_aided"], d["hand_timed"], d["status"])]
    return d.sort_values("date")
