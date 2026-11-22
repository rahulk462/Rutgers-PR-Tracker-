"""Turn raw result strings into clean, numeric performances.

Raw rows are dicts of strings exactly as they were found (see db.RAW_FIELDS).
`clean_rows` turns them into one clean row per performance with:
  mark_value  seconds (running), meters (field) or points (multis)
  status      OK, DNF, DNS, DQ, FOUL, NM, NH, or UNPARSED
  wind_aided / hand_timed flags, and `legal` (counts toward PRs by default)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from bs4 import BeautifulSoup

import events

WIND_LIMIT = 2.0  # m/s; above this a mark is wind-aided

STATUSES = {"DNF", "DNS", "DQ", "FOUL", "NM", "NH"}
_STATUS_ALIASES = {"SCR": "DNS", "FS": "DQ", "DSQ": "DQ", "FOULED": "FOUL"}

INCH = 0.0254


@dataclass
class Mark:
    value: float | None
    status: str = "OK"
    hand_timed: bool = False
    wind_flag: bool = False      # explicit "w" marker on the mark
    wind: float | None = None    # wind found inside the mark string, e.g. "10.45 (+2.1)"


# --- wind ------------------------------------------------------------------

_WIND_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)")


def parse_wind(raw: str | None) -> float | None:
    """'+1.8' -> 1.8, '-0.5' -> -0.5, 'NWI' / '' -> None."""
    if raw is None:
        return None
    s = str(raw).strip().strip("()").replace("m/s", "").strip()
    if not s or s.upper() in {"NWI", "NW", "N/A", "NA", "-", "NAN"}:
        return None
    m = _WIND_RE.fullmatch(s)
    return float(m.group(1)) if m else None


# --- marks -----------------------------------------------------------------

_PAREN_WIND = re.compile(r"\(\s*([+-]?\d+(?:\.\d+)?)\s*\)")
_TIME_RE = re.compile(r"^(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)$")
_FEET_RES = [
    re.compile(r"^(\d+)\s*-\s*(\d+(?:\.\d+)?)$"),                   # 23-4.5, 23-04.50
    re.compile(r"^(\d+)\s*'\s*(\d+(?:\.\d+)?)\s*(?:\"|'')?$"),       # 23' 4.5"
    re.compile(r"^(\d+)\s*ft\.?\s*(\d+(?:\.\d+)?)\s*(?:in\.?)?$"),   # 23ft 4.5in
]


def parse_mark(raw: str | None, event: str) -> Mark:
    """Parse a mark for a canonical event. Never raises: anything it can't
    read comes back with status UNPARSED so it stays visible."""
    if raw is None or str(raw).strip() == "" or str(raw).strip().lower() == "nan":
        return Mark(None, "UNPARSED")
    s = str(raw).strip()

    word = re.match(r"^([A-Za-z]+)\b", s)          # "DNF", "DQ (FS)", "NM"
    token = word.group(1).upper() if word else ""
    if token in STATUSES:
        return Mark(None, token)
    if token in _STATUS_ALIASES:
        return Mark(None, _STATUS_ALIASES[token])

    mark = Mark(None)
    m = _PAREN_WIND.search(s)
    if m:
        mark.wind = float(m.group(1))
        s = _PAREN_WIND.sub("", s).strip()

    # TFRRS-style trailing markers: h = hand time, w/W = wind-aided,
    # plus footnote symbols (#, *, @, c for converted, etc.).
    while s and not s[-1].isdigit() and s[-1] not in "\"'":
        ch = s[-1].lower()
        if ch == "h" and not s.lower().endswith("ph"):
            mark.hand_timed = True
        elif ch == "w":
            mark.wind_flag = True
        elif ch == "m" and events.get(event).kind == "distance":
            pass  # metric unit suffix
        elif s.lower().endswith(("ft", "in")):
            break
        s = s[:-1].rstrip()

    kind = events.get(event).kind
    try:
        if kind == "time":
            mark.value = _parse_time(s)
        elif kind == "distance":
            mark.value = _parse_distance(s)
        else:
            mark.value = float(s.replace(",", ""))
    except ValueError:
        return Mark(None, "UNPARSED")
    return mark


def _parse_time(s: str) -> float:
    m = _TIME_RE.match(s.replace(" ", ""))
    if not m:
        raise ValueError(s)
    a, b, sec = m.groups()
    parts = [p for p in (a, b) if p is not None]
    total = float(sec)
    if len(parts) == 2:          # h:mm:ss.xx
        total += int(parts[0]) * 3600 + int(parts[1]) * 60
    elif len(parts) == 1:        # m:ss.xx
        total += int(parts[0]) * 60
    if total <= 0:
        raise ValueError(s)
    return total


def _parse_distance(s: str) -> float:
    for rx in _FEET_RES:
        m = rx.match(s)
        if m:
            feet, inches = int(m.group(1)), float(m.group(2))
            if inches >= 12:
                raise ValueError(s)
            return round((feet * 12 + inches) * INCH, 4)
    s = s.lower().rstrip("m").strip()
    value = float(s)
    if value <= 0:
        raise ValueError(s)
    return value


# --- place / round / date / season -----------------------------------------

_ROUNDS = {"F": "Final", "P": "Prelim", "Q": "Prelim", "SF": "Semifinal", "S": "Semifinal",
           "H": "Heat", "FINAL": "Final", "FINALS": "Final", "PRELIM": "Prelim",
           "PRELIMS": "Prelim", "SEMI": "Semifinal", "SEMIFINAL": "Semifinal"}


def parse_place(raw: str | None) -> int | None:
    m = re.match(r"^\s*(\d+)", str(raw or ""))
    return int(m.group(1)) if m else None


def parse_round(raw_round: str | None, raw_place: str | None = None) -> str | None:
    """Round from its own column, or from TFRRS's '3rd (F)' place text."""
    for s in (raw_round, raw_place):
        if not s or str(s).lower() == "nan":
            continue
        m = re.search(r"\(([A-Za-z]+)\)", str(s))
        key = (m.group(1) if m else str(s)).strip().upper()
        if key in _ROUNDS:
            return _ROUNDS[key]
        if s is raw_round:
            return str(s).strip()
    return None


_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()


def parse_date(raw: str | None) -> date | None:
    """ISO dates, US dates, and TFRRS meet ranges such as 'Apr 25-27, 2024'
    or 'Feb 27 - Mar 1, 2026' (the first day is used)."""
    if not raw or str(raw).lower() == "nan":
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.match(r"^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}).*?(\d{4})\s*$", s)
    if m and m.group(1).lower() in _MONTHS:
        return date(int(m.group(3)), _MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)))
    return None


def infer_season(event: str, when: date | None, raw_season: str | None) -> tuple[str | None, int | None]:
    """Return (season_type, season_year). season_type is indoor/outdoor/xc.
    An indoor season that starts in December belongs to the next year."""
    st = None
    if raw_season and str(raw_season).lower() != "nan":
        r = str(raw_season).lower()
        if "indoor" in r:
            st = "indoor"
        elif "outdoor" in r:
            st = "outdoor"
        elif "xc" in r or "cross" in r:
            st = "xc"
    ev = events.get(event)
    if st is None:
        if ev.xc:
            st = "xc"
        elif ev.indoor_only:
            st = "indoor"
        elif when is not None:
            if when.month in (12, 1, 2) or (when.month == 3 and when.day <= 15):
                st = "indoor"
            else:
                st = "outdoor"
    year = None
    if when is not None:
        year = when.year + 1 if (st == "indoor" and when.month == 12) else when.year
    return st, year


def season_label(season_type: str | None, year: int | None) -> str | None:
    if not season_type or not year:
        return None
    return f"{year} {'XC' if season_type == 'xc' else season_type.title()}"


# --- raw -> clean ----------------------------------------------------------

def athlete_key(name: str, athlete_id: str | None, gender: str | None) -> str:
    if athlete_id and str(athlete_id).strip() and str(athlete_id).lower() != "nan":
        return f"id:{str(athlete_id).strip()}"
    return f"name:{re.sub(r'\s+', ' ', str(name).strip().lower())}|{normalize_gender(gender) or ''}"


def normalize_gender(raw: str | None) -> str | None:
    s = str(raw or "").strip().lower()
    if s in {"m", "men", "male", "man", "mens", "men's"}:
        return "men"
    if s in {"f", "w", "women", "female", "woman", "womens", "women's"}:
        return "women"
    return None


def clean_row(raw: dict) -> dict:
    """One raw row -> one clean row. Unknown events keep event=None."""
    event = events.normalize_event(raw.get("event"))
    out = {
        "raw_id": raw.get("raw_id"),
        "athlete_key": athlete_key(raw.get("athlete_name", ""), raw.get("athlete_id"), raw.get("gender")),
        "athlete": re.sub(r"\s+", " ", str(raw.get("athlete_name") or "").strip()),
        "gender": normalize_gender(raw.get("gender")),
        "event_raw": raw.get("event"),
        "event": event,
        "event_group": events.get(event).group if event else None,
        "mark_raw": raw.get("mark"),
        "meet": (raw.get("meet") or "").strip() or None,
        "place": parse_place(raw.get("place")),
        "round": parse_round(raw.get("round"), raw.get("place")),
    }
    when = parse_date(raw.get("date"))
    out["date"] = when.isoformat() if when else None
    if event is None:
        out.update(mark_value=None, units=None, status="UNKNOWN_EVENT", wind=None,
                   wind_aided=False, hand_timed=False, legal=False,
                   season_type=None, season_year=None, season=None)
        return out

    mark = parse_mark(raw.get("mark"), event)
    wind = parse_wind(raw.get("wind"))
    if wind is None:
        wind = mark.wind
    st, year = infer_season(event, when, raw.get("season"))
    ev = events.get(event)
    wind_aided = bool(mark.status == "OK" and ev.wind_affected and st != "indoor"
                      and ((wind is not None and wind > WIND_LIMIT) or mark.wind_flag))
    out.update(
        mark_value=mark.value,
        units=ev.units,
        status=mark.status,
        wind=wind,
        wind_aided=wind_aided,
        hand_timed=bool(mark.hand_timed and ev.kind == "time"),
        season_type=st,
        season_year=year,
        season=season_label(st, year),
    )
    out["legal"] = bool(out["status"] == "OK" and out["mark_value"] is not None
                        and not out["wind_aided"] and not out["hand_timed"])
    return out


def clean_rows(raw_rows: list[dict]) -> list[dict]:
    """Clean every raw row, then drop exact duplicates that come from
    importing the same results twice (e.g. a re-saved athlete page).
    The newest raw row wins; raw rows themselves are never touched."""
    seen: dict[tuple, dict] = {}
    for raw in sorted(raw_rows, key=lambda r: r.get("raw_id") or 0):
        row = clean_row(raw)
        key = (row["athlete_key"], row["event_raw"], str(row["mark_raw"]).strip(),
               row["meet"], row["date"], row["round"])
        seen[key] = row
    return list(seen.values())


# --- TFRRS HTML (saved pages) ----------------------------------------------
# NOTE: written from the general layout of TFRRS athlete pages; check it
# against a real saved page before trusting it (see README).

def parse_tfrrs_athlete_page(html: str, gender: str | None = None,
                             athlete_id: str | None = None) -> list[dict]:
    """Extract raw rows from a saved TFRRS athlete profile page.
    Each meet is a table whose header holds the meet name and date; each
    body row holds event, mark (with optional wind) and place/round."""
    soup = BeautifulSoup(html, "lxml")
    name = _athlete_name(soup)
    if athlete_id is None:
        link = soup.find("link", rel="canonical") or soup.find("meta", property="og:url")
        href = (link.get("href") or link.get("content")) if link else ""
        m = re.search(r"/athletes/(\d+)", href or "")
        athlete_id = m.group(1) if m else None
    if gender is None:
        team_link = soup.find("a", href=re.compile(r"/teams/.*_[mf]_"))
        if team_link:
            gender = "m" if "_m_" in team_link["href"] else "f"

    rows = []
    container = soup.find(id="meet-results") or soup
    for table in container.find_all("table"):
        head = table.find("thead") or table.find("tr")
        if head is None:
            continue
        meet_link = head.find("a")
        date_el = head.find("span")
        meet = (meet_link or head).get_text(" ", strip=True)
        date_txt = date_el.get_text(" ", strip=True) if date_el else ""
        if date_txt and meet.endswith(date_txt):
            meet = meet[: -len(date_txt)].strip()
        if parse_date(date_txt) is None:
            continue  # not a meet table (e.g. the PR summary)
        body_rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")[1:]
        for tr in body_rows:
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue
            event = cells[0].get_text(" ", strip=True)
            mark_cell = cells[1]
            wind = None
            spans = mark_cell.find_all("span")
            for sp in spans:
                w = parse_wind(sp.get_text(strip=True))
                if w is not None:
                    wind = sp.get_text(strip=True).strip("()")
                    sp.extract()
            mark_link = mark_cell.find("a")
            mark = (mark_link or mark_cell).get_text(" ", strip=True)
            place = cells[2].get_text(" ", strip=True) if len(cells) > 2 else ""
            rows.append({
                "athlete_name": name, "athlete_id": athlete_id, "gender": gender,
                "team": None, "event": event, "mark": mark, "wind": wind,
                "meet": meet, "date": date_txt, "season": None,
                "place": place, "round": None,
            })
    return rows


def _athlete_name(soup: BeautifulSoup) -> str:
    for sel in ("h3.panel-title", "div.panel-heading h3", "h3", "title"):
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            text = el.get_text(" ", strip=True)
            text = re.split(r"\s+[|-]\s+|\s{2,}", text)[0]
            return re.sub(r"\s+", " ", text).strip().title() if text.isupper() else text.strip()
    return "Unknown"


def parse_tfrrs_roster_page(html: str, base_url: str = "https://www.tfrrs.org") -> list[str]:
    """Athlete profile URLs listed on a TFRRS team roster page."""
    soup = BeautifulSoup(html, "lxml")
    urls = []
    for a in soup.find_all("a", href=re.compile(r"/athletes/\d+")):
        href = a["href"]
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = base_url + href
        if href not in urls:
            urls.append(href)
    return urls
