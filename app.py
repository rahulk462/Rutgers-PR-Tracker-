"""Streamlit dashboard.   Run:  streamlit run app.py

Optional env vars: TRACKER_DB (default data/tracker.db) and
STANDARDS_FILE (default standards.yaml).
"""
from __future__ import annotations

import os

import altair as alt
import pandas as pd
import streamlit as st

import analysis
import db
import events

st.set_page_config(page_title="Rutgers T&F PR Tracker", layout="wide")
st.markdown("""<style>
  .block-container {padding-top: 2rem; max-width: 1200px;}
  [data-testid="stMetricValue"] {font-size: 1.6rem;}
</style>""", unsafe_allow_html=True)

BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#8a8984"


@st.cache_data(ttl=60)
def load():
    con = db.connect(os.environ.get("TRACKER_DB", db.DEFAULT_DB))
    return db.load_performances(con)


df = load()
if df.empty:
    st.title("Rutgers Track & Field PR Tracker")
    st.info("No results yet. Load some first, for example the demo data:\n\n"
            "`python scraper.py import-csv data/sample/demo_results.csv`")
    st.stop()

try:
    standards = analysis.load_standards(os.environ.get("STANDARDS_FILE", analysis.STANDARDS_FILE))
except ValueError as e:
    st.error(str(e))
    standards = ([], {})
std_names = standards[0]

# --- filters ----------------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    season = st.selectbox("Season", analysis.seasons(df))
    group = st.selectbox("Event group", ["All"] + events.GROUPS,
                         format_func=lambda g: g.title())
    gender = st.radio("Gender", ["All", "Men", "Women"], horizontal=True)
    sort_by = st.selectbox("Sort by distance to", std_names) if std_names else None
    include_flagged = st.checkbox("Count wind-aided and hand times", value=False,
                                  help="Off by default: marks with wind over +2.0 m/s or hand "
                                       "timing are shown but don't count as PRs or season bests.")
    if not std_names or not standards[1]:
        st.caption("No standards filled in yet. Add them to `standards.yaml`.")

g = None if gender == "All" else gender.lower()
grp = None if group == "All" else group

team_tab, athlete_tab = st.tabs(["Team", "Athlete"])

# --- team view ----------------------------------------------------------------
with team_tab:
    st.subheader(f"{season} · {group.title() if grp else 'All events'} · {gender}")
    table = analysis.team_table(df, season, standards, gender=g, group=grp,
                                sort_by=sort_by, include_flagged=include_flagged)
    if table.empty:
        st.write("No marks for this selection.")
    else:
        pct_cols = [c for c in table.columns if c.startswith("% off ")]
        table["Met"] = table.apply(
            lambda r: ", ".join(c[6:] for c in pct_cols if pd.notna(r[c]) and r[c] <= 0), axis=1)
        show = ["Athlete", "Event", "Season best", "PR", *pct_cols, "Met", "SB meet"]
        if not g:
            show.insert(1, "Gender")
        cfg = {c: st.column_config.NumberColumn(c, format="%.2f%%",
                                                help="How far the season best is from the standard. "
                                                     "0 or below means it's met.")
               for c in pct_cols}
        cfg["PR"] = st.column_config.TextColumn("PR", help="Lifetime best, same season type "
                                                           "(indoor, outdoor or XC).")
        st.dataframe(table[show].fillna({"Met": ""}), column_config=cfg, hide_index=True, use_container_width=True,
                     height=min(38 + 35 * len(table), 700))
        st.caption(f"{len(table)} athlete-events. Sorted by % off "
                   f"{sort_by or (std_names[0] if std_names else 'event')}, closest first.")

# --- athlete view -------------------------------------------------------------
with athlete_tab:
    pool = df[df["event_group"].isin(analysis.INDIVIDUAL_GROUPS)]
    if g:
        pool = pool[pool["gender"] == g]
    if grp:
        pool = pool[pool["event_group"] == grp]
    in_season = pool[pool["season"] == season]
    athletes = (in_season[["athlete_key", "athlete"]].drop_duplicates()
                .sort_values("athlete"))
    if athletes.empty:
        st.write("No athletes for this selection.")
        st.stop()
    names = dict(zip(athletes["athlete_key"], athletes["athlete"]))
    c1, c2 = st.columns(2)
    key = c1.selectbox("Athlete", list(names), format_func=names.get)
    evs = [e for e in analysis.athlete_events(df, key, season)
           if not grp or events.get(e).group == grp]
    event = c2.selectbox("Event", evs)

    prog = analysis.progression(df, key, event, season=season, include_flagged=include_flagged)
    marks = prog[prog["mark_value"].notna()]
    season_type = prog["season_type"].dropna().iloc[0] if prog["season_type"].notna().any() else None
    pr = analysis.lifetime_pr(df, key, event, season_type, include_flagged)
    counted_marks = marks[marks["legal"] | include_flagged]
    sb = analysis.best_marks(counted_marks, ["event"])

    m1, m2, m3 = st.columns(3)
    m1.metric("Season best", sb["mark"].iloc[0] if len(sb) else "—")
    m2.metric("Lifetime PR", events.format_mark(pr["mark_value"], event) if pr is not None else "—",
              help="Same season type, legal marks only unless the sidebar option is on.")
    m3.metric("Meets this season", int(prog["meet"].nunique()))

    if len(marks):
        lower = events.lower_is_better(event)
        unit = events.get(event).units
        plot = marks.assign(
            kind=["PR" if p else ("Not counted" if not (l or include_flagged) else "Mark")
                  for p, l in zip(marks["is_pr"], marks["legal"])],
            when=marks["date"].dt.strftime("%b %d, %Y"))
        y_title = {"s": "Time (up = faster)", "m": "Distance (m)", "pts": "Points"}[unit]
        label_expr = ("datum.value >= 60 ? floor(datum.value/60) + ':' + "
                      "(datum.value % 60 < 10 ? '0' : '') + format(datum.value % 60, '.2f') "
                      ": format(datum.value, '.2f')") if unit == "s" else None
        y = alt.Y("mark_value:Q", title=y_title,
                  scale=alt.Scale(zero=False, reverse=lower, padding=12),
                  axis=alt.Axis(labelExpr=label_expr, grid=True, gridOpacity=0.4))
        x = alt.X("date:T", title=None, axis=alt.Axis(format="%b %d", grid=False))
        tip = [alt.Tooltip("when:N", title="Date"), alt.Tooltip("meet:N", title="Meet"),
               alt.Tooltip("mark:N", title="Mark"), alt.Tooltip("wind:Q", title="Wind", format="+.1f"),
               alt.Tooltip("round:N", title="Round"), alt.Tooltip("note:N", title="Note")]
        counted = plot[plot["kind"] != "Not counted"]
        line = alt.Chart(counted).mark_line(color=BLUE, strokeWidth=2).encode(x=x, y=y)
        color = alt.Color("kind:N", title=None,
                          scale=alt.Scale(domain=["Mark", "PR", "Not counted"], range=[BLUE, ORANGE, GRAY]),
                          legend=alt.Legend(orient="top"))
        pts = alt.Chart(counted).mark_point(filled=True, opacity=1).encode(
            x=x, y=y, tooltip=tip, color=color,
            shape=alt.condition(alt.datum.kind == "PR", alt.value("diamond"), alt.value("circle")),
            size=alt.condition(alt.datum.kind == "PR", alt.value(220), alt.value(90)))
        flagged = alt.Chart(plot[plot["kind"] == "Not counted"]).mark_point(
            filled=False, strokeWidth=2, size=90, opacity=1).encode(x=x, y=y, tooltip=tip, color=color)
        label = alt.Chart(plot[plot["is_pr"]]).mark_text(dy=-16, fontWeight="bold", color=ORANGE).encode(
            x=x, y=y, text=alt.value("PR"))
        st.altair_chart((line + flagged + pts + label).properties(height=340), use_container_width=True)

    st.dataframe(
        prog[["date", "meet", "mark", "wind", "round", "place", "note"]]
        .assign(date=prog["date"].dt.date,
                place=[str(int(v)) if pd.notna(v) else "" for v in prog["place"]],
                wind=[f"{v:+.1f}" if pd.notna(v) else "" for v in prog["wind"]])
        .rename(columns=str.title).astype(object).where(lambda t: t.notna(), ""),
        hide_index=True, use_container_width=True)
