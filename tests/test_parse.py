from datetime import date

import pytest

import parse


@pytest.mark.parametrize("raw,event,value", [
    ("10.45", "100m", 10.45),
    ("1:52.34", "800m", 112.34),
    ("4:01.5", "Mile", 241.5),
    ("1:02:33.4", "10000m", 3753.4),
    ("25:12.3", "XC 8K", 1512.3),
    ("7.12m", "LJ", 7.12),
    ("7.12", "LJ", 7.12),
    ("16.45 m", "SP", 16.45),
    ("23-4.5", "LJ", (23 * 12 + 4.5) * 0.0254),
    ("23-04.50", "LJ", (23 * 12 + 4.5) * 0.0254),
    ("23' 4.5\"", "LJ", (23 * 12 + 4.5) * 0.0254),
    ("23ft 4.5in", "LJ", (23 * 12 + 4.5) * 0.0254),
    ("5432", "Heptathlon", 5432),
    ("6.70#", "60m", 6.70),
])
def test_parse_mark_values(raw, event, value):
    m = parse.parse_mark(raw, event)
    assert m.status == "OK"
    assert m.value == pytest.approx(value, abs=1e-4)


@pytest.mark.parametrize("raw,status", [
    ("DNF", "DNF"), ("DNS", "DNS"), ("DQ", "DQ"), ("DQ (FS)", "DQ"), ("FOUL", "FOUL"),
    ("NM", "NM"), ("NH", "NH"), ("dnf", "DNF"), ("SCR", "DNS"), ("", "UNPARSED"),
    ("??", "UNPARSED"), ("23-14", "UNPARSED"),
])
def test_parse_mark_statuses(raw, status):
    event = "LJ" if raw in ("FOUL", "NM", "NH", "23-14") else "100m"
    m = parse.parse_mark(raw, event)
    assert m.status == status
    assert m.value is None


def test_hand_time_and_wind_markers():
    m = parse.parse_mark("10.4h", "100m")
    assert m.hand_timed and m.value == pytest.approx(10.4)
    m = parse.parse_mark("10.31w", "100m")
    assert m.wind_flag and m.value == pytest.approx(10.31)
    m = parse.parse_mark("7.58m (+2.6)", "LJ")
    assert m.wind == pytest.approx(2.6) and m.value == pytest.approx(7.58)


@pytest.mark.parametrize("raw,expected", [
    ("+1.8", 1.8), ("-0.5", -0.5), ("2.1", 2.1), ("(+0.4)", 0.4), ("NWI", None), ("", None), (None, None),
])
def test_parse_wind(raw, expected):
    assert parse.parse_wind(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("2026-04-25", date(2026, 4, 25)), ("04/25/2026", date(2026, 4, 25)),
    ("Apr 25, 2026", date(2026, 4, 25)), ("Apr 25-27, 2024", date(2024, 4, 25)),
    ("Feb 27 - Mar 1, 2026", date(2026, 2, 27)), ("", None), ("someday", None),
])
def test_parse_date(raw, expected):
    assert parse.parse_date(raw) == expected


def test_place_and_round():
    assert parse.parse_place("3rd (F)") == 3
    assert parse.parse_round(None, "3rd (F)") == "Final"
    assert parse.parse_round("P", None) == "Prelim"
    assert parse.parse_place("") is None


def test_infer_season():
    assert parse.infer_season("60m", date(2026, 3, 20), None) == ("indoor", 2026)
    assert parse.infer_season("Mile", date(2025, 12, 6), None) == ("indoor", 2026)
    assert parse.infer_season("Mile", date(2026, 4, 10), None) == ("outdoor", 2026)
    assert parse.infer_season("XC 8K", date(2025, 10, 31), None) == ("xc", 2025)
    assert parse.infer_season("200m", date(2026, 4, 10), "Indoor") == ("indoor", 2026)


def _raw(**kw):
    base = dict(raw_id=1, athlete_name="Test A", athlete_id=None, gender="men", event="100",
                mark="10.40", wind="+1.0", meet="M", date="2026-04-10", season=None,
                place="1", round="F")
    base.update(kw)
    return base


def test_clean_row_flags():
    assert parse.clean_row(_raw())["legal"]
    r = parse.clean_row(_raw(wind="+2.1"))
    assert r["wind_aided"] and not r["legal"] and r["mark_value"] == pytest.approx(10.40)
    r = parse.clean_row(_raw(wind="+2.0"))
    assert not r["wind_aided"] and r["legal"]           # exactly 2.0 is legal
    r = parse.clean_row(_raw(mark="10.3h", wind=None))
    assert r["hand_timed"] and not r["legal"]
    r = parse.clean_row(_raw(event="400", wind="+5.0"))
    assert not r["wind_aided"]                          # 400m isn't wind-affected
    r = parse.clean_row(_raw(event="60", date="2026-02-01", wind="+3.0"))
    assert not r["wind_aided"]                          # indoor
    r = parse.clean_row(_raw(mark="DNF"))
    assert r["status"] == "DNF" and not r["legal"]
    r = parse.clean_row(_raw(event="Egg and spoon"))
    assert r["status"] == "UNKNOWN_EVENT" and r["event"] is None


def test_clean_rows_dedupes_reimports():
    rows = parse.clean_rows([_raw(raw_id=1), _raw(raw_id=7)])
    assert len(rows) == 1 and rows[0]["raw_id"] == 7


ATHLETE_PAGE = """
<html><head><link rel="canonical" href="https://www.tfrrs.org/athletes/123456/Rutgers/Test_Runner.html"></head>
<body>
<h3 class="panel-title">TEST RUNNER</h3>
<a href="https://www.tfrrs.org/teams/tf/NJ_college_f_Rutgers.html">Rutgers</a>
<div id="meet-results">
 <table class="table"><thead><tr><th colspan="3">
   <a href="/results/1/Demo_Classic">Demo Classic</a> <span>Apr 25-26, 2026</span></th></tr></thead>
  <tbody>
   <tr><td>100H</td><td><a href="#">13.48</a> <span>(-0.3)</span></td><td>1st (F)</td></tr>
   <tr><td>LJ</td><td><a href="#">6.01m</a> <span>(+2.4)</span></td><td>3rd</td></tr>
  </tbody></table>
 <table class="table"><thead><tr><th colspan="3">
   <a href="/results/2/Demo_Indoor">Demo Indoor</a> <span>Feb 27 - Mar 1, 2026</span></th></tr></thead>
  <tbody><tr><td>60H</td><td><a href="#">8.31</a></td><td>2nd (P)</td></tr></tbody></table>
</div></body></html>
"""


def test_parse_tfrrs_athlete_page():
    rows = parse.parse_tfrrs_athlete_page(ATHLETE_PAGE)
    assert len(rows) == 3
    r = rows[0]
    assert r["athlete_name"] == "Test Runner" and r["athlete_id"] == "123456" and r["gender"] == "f"
    assert (r["event"], r["mark"], r["wind"], r["meet"]) == ("100H", "13.48", "-0.3", "Demo Classic")
    clean = [parse.clean_row(dict(x, raw_id=i)) for i, x in enumerate(rows)]
    assert clean[0]["round"] == "Final" and clean[0]["legal"]
    assert clean[1]["wind_aided"]
    assert clean[2]["season"] == "2026 Indoor" and clean[2]["round"] == "Prelim"


def test_parse_roster_page():
    html = ('<a href="/athletes/1/Rutgers/A.html">A</a><a href="//www.tfrrs.org/athletes/2/Rutgers/B.html">B</a>'
            '<a href="/athletes/1/Rutgers/A.html">A again</a>')
    assert parse.parse_tfrrs_roster_page(html) == [
        "https://www.tfrrs.org/athletes/1/Rutgers/A.html", "https://www.tfrrs.org/athletes/2/Rutgers/B.html"]
