"""Event definitions: canonical names, event groups, mark kind, and
which direction is "better".

This is the ONLY module that knows whether lower or higher is better.
Everything else asks it through `sort_key`, `is_better` and `pct_off`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

GROUPS = ["sprints", "hurdles", "distance", "jumps", "throws", "multis"]


@dataclass(frozen=True)
class Event:
    name: str          # canonical display name, e.g. "100m", "LJ"
    group: str         # sprints / hurdles / distance / jumps / throws / multis / relays
    kind: str          # "time" (seconds), "distance" (meters), "points"
    wind_affected: bool = False  # outdoor marks can be wind-aided
    indoor_only: bool = False
    xc: bool = False

    @property
    def units(self) -> str:
        return {"time": "s", "distance": "m", "points": "pts"}[self.kind]


_EVENTS = [
    # sprints
    Event("55m", "sprints", "time", indoor_only=True),
    Event("60m", "sprints", "time", indoor_only=True),
    Event("100m", "sprints", "time", wind_affected=True),
    Event("200m", "sprints", "time", wind_affected=True),
    Event("300m", "sprints", "time", indoor_only=True),
    Event("400m", "sprints", "time"),
    Event("500m", "sprints", "time", indoor_only=True),
    Event("600m", "sprints", "time", indoor_only=True),
    # hurdles
    Event("55mH", "hurdles", "time", indoor_only=True),
    Event("60mH", "hurdles", "time", indoor_only=True),
    Event("100mH", "hurdles", "time", wind_affected=True),
    Event("110mH", "hurdles", "time", wind_affected=True),
    Event("400mH", "hurdles", "time"),
    # distance
    Event("800m", "distance", "time"),
    Event("1000m", "distance", "time", indoor_only=True),
    Event("1500m", "distance", "time"),
    Event("Mile", "distance", "time"),
    Event("3000m", "distance", "time"),
    Event("3000mSC", "distance", "time"),
    Event("5000m", "distance", "time"),
    Event("10000m", "distance", "time"),
    Event("XC 5K", "distance", "time", xc=True),
    Event("XC 6K", "distance", "time", xc=True),
    Event("XC 8K", "distance", "time", xc=True),
    Event("XC 10K", "distance", "time", xc=True),
    # jumps
    Event("HJ", "jumps", "distance"),
    Event("PV", "jumps", "distance"),
    Event("LJ", "jumps", "distance", wind_affected=True),
    Event("TJ", "jumps", "distance", wind_affected=True),
    # throws
    Event("SP", "throws", "distance"),
    Event("DT", "throws", "distance"),
    Event("HT", "throws", "distance"),
    Event("JT", "throws", "distance"),
    Event("WT", "throws", "distance", indoor_only=True),
    # multis
    Event("Pentathlon", "multis", "points", indoor_only=True),
    Event("Heptathlon", "multis", "points"),
    Event("Decathlon", "multis", "points"),
    # relays: kept so they're recognised, but they are not individual marks
    Event("4x100", "relays", "time"),
    Event("4x200", "relays", "time"),
    Event("4x400", "relays", "time"),
    Event("4x800", "relays", "time"),
    Event("DMR", "relays", "time"),
    Event("SMR", "relays", "time"),
]
EVENTS: dict[str, Event] = {e.name: e for e in _EVENTS}

# Aliases are matched against a "compacted" name: lowercase, no spaces,
# punctuation or the words meter(s)/dash/run.
_ALIASES = {
    "55": "55m", "60": "60m", "100": "100m", "200": "200m", "300": "300m",
    "400": "400m", "500": "500m", "600": "600m", "800": "800m",
    "1000": "1000m", "1500": "1500m", "3000": "3000m", "5000": "5000m",
    "10000": "10000m", "mile": "Mile", "1mile": "Mile",
    "55h": "55mH", "55hurdles": "55mH",
    "60h": "60mH", "60hurdles": "60mH",
    "100h": "100mH", "100hurdles": "100mH",
    "110h": "110mH", "110hurdles": "110mH",
    "400h": "400mH", "400hurdles": "400mH", "400ih": "400mH",
    "3000sc": "3000mSC", "3000s": "3000mSC", "3000steeple": "3000mSC",
    "3000steeplechase": "3000mSC", "steeplechase": "3000mSC", "steeple": "3000mSC",
    "5k": "XC 5K", "6k": "XC 6K", "8k": "XC 8K", "10k": "XC 10K",
    "6000": "XC 6K", "8000": "XC 8K",
    "xc5k": "XC 5K", "xc6k": "XC 6K", "xc8k": "XC 8K", "xc10k": "XC 10K",
    "hj": "HJ", "highjump": "HJ", "pv": "PV", "polevault": "PV",
    "lj": "LJ", "longjump": "LJ", "tj": "TJ", "triplejump": "TJ",
    "sp": "SP", "shot": "SP", "shotput": "SP",
    "dt": "DT", "discus": "DT", "discusthrow": "DT",
    "ht": "HT", "hammer": "HT", "hammerthrow": "HT",
    "jt": "JT", "jav": "JT", "javelin": "JT", "javelinthrow": "JT",
    "wt": "WT", "weight": "WT", "weightthrow": "WT",
    "35lbweight": "WT", "35lbweightthrow": "WT", "20lbweight": "WT", "20lbweightthrow": "WT",
    "pent": "Pentathlon", "pentathlon": "Pentathlon",
    "hep": "Heptathlon", "heptathlon": "Heptathlon",
    "dec": "Decathlon", "decathlon": "Decathlon",
    "4x100": "4x100", "4x100relay": "4x100", "4x200": "4x200", "4x200relay": "4x200",
    "4x400": "4x400", "4x400relay": "4x400", "4x800": "4x800", "4x800relay": "4x800",
    "dmr": "DMR", "distancemedley": "DMR", "distancemedleyrelay": "DMR",
    "smr": "SMR", "sprintmedley": "SMR", "sprintmedleyrelay": "SMR",
}


def _compact(raw: str) -> str:
    s = raw.lower().replace(",", "")
    s = re.sub(r"\b(meters?|metres?|dash|run|m)\b", "", s)
    s = re.sub(r"(\d)m\b", r"\1", s)          # "100m" -> "100"
    s = re.sub(r"(\d)mh\b", r"\1h", s)        # "60mh" -> "60h"
    s = re.sub(r"(\d)msc\b", r"\1sc", s)
    return re.sub(r"[^a-z0-9]", "", s)


def normalize_event(raw: str | None) -> str | None:
    """Map a raw event label ("100 Meters", "60H", "Long Jump") to a
    canonical name, or None if it isn't recognised."""
    if not raw:
        return None
    if raw in EVENTS:
        return raw
    return _ALIASES.get(_compact(raw))


def get(name: str) -> Event:
    return EVENTS[name]


# --- direction: the one place that knows lower vs higher is better ---------

def lower_is_better(event: str) -> bool:
    return EVENTS[event].kind == "time"


def sort_key(value: float, event: str) -> float:
    """A key where smaller always means better, for any event."""
    return value if lower_is_better(event) else -value


def is_better(a: float, b: float, event: str) -> bool:
    return sort_key(a, event) < sort_key(b, event)


def pct_off(mark: float, standard: float, event: str) -> float:
    """Percent the mark is short of the standard. 0 or negative means the
    standard is met; positive means that many percent away."""
    if lower_is_better(event):
        return (mark - standard) / standard * 100.0
    return (standard - mark) / standard * 100.0


# --- display ---------------------------------------------------------------

def format_mark(value: float | None, event: str) -> str:
    if value is None or value != value:  # None or NaN
        return ""
    kind = EVENTS[event].kind
    if kind == "points":
        return f"{int(round(value))}"
    if kind == "distance":
        return f"{value:.2f}m"
    # time
    hours, rem = divmod(value, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours >= 1:
        return f"{int(hours)}:{int(minutes):02d}:{seconds:05.2f}"
    if minutes >= 1:
        return f"{int(minutes)}:{seconds:05.2f}"
    return f"{seconds:.2f}"
