import pytest

import events


@pytest.mark.parametrize("raw,expected", [
    ("100", "100m"), ("100m", "100m"), ("100 Meters", "100m"), ("100 Meter Dash", "100m"),
    ("60H", "60mH"), ("60 Hurdles", "60mH"), ("60m Hurdles", "60mH"), ("110H", "110mH"),
    ("400 Hurdles", "400mH"), ("3000 Steeplechase", "3000mSC"), ("3000SC", "3000mSC"),
    ("Mile", "Mile"), ("Mile Run", "Mile"), ("10,000", "10000m"), ("8K", "XC 8K"),
    ("6k", "XC 6K"), ("Long Jump", "LJ"), ("HJ", "HJ"), ("Shot Put", "SP"),
    ("Weight Throw", "WT"), ("35 lb Weight", "WT"), ("Javelin", "JT"), ("Hammer", "HT"),
    ("Heptathlon", "Heptathlon"), ("4x400 Relay", "4x400"), ("DMR", "DMR"),
])
def test_normalize_event(raw, expected):
    assert events.normalize_event(raw) == expected


def test_unknown_event():
    assert events.normalize_event("Egg and spoon") is None


def test_direction_lives_in_one_place():
    assert events.is_better(10.1, 10.2, "100m")
    assert events.is_better(7.5, 7.4, "LJ")
    assert events.is_better(6000, 5900, "Heptathlon")
    assert events.sort_key(10.1, "100m") < events.sort_key(10.2, "100m")
    assert events.sort_key(7.5, "LJ") < events.sort_key(7.4, "LJ")


def test_pct_off():
    assert events.pct_off(10.5, 10.0, "100m") == pytest.approx(5.0)
    assert events.pct_off(9.9, 10.0, "100m") < 0          # met
    assert events.pct_off(7.6, 8.0, "LJ") == pytest.approx(5.0)
    assert events.pct_off(8.1, 8.0, "LJ") < 0             # met


@pytest.mark.parametrize("value,event,expected", [
    (10.4, "100m", "10.40"), (112.34, "800m", "1:52.34"), (3725.5, "10000m", "1:02:05.50"),
    (7.123, "LJ", "7.12m"), (5432.0, "Heptathlon", "5432"),
])
def test_format_mark(value, event, expected):
    assert events.format_mark(value, event) == expected
