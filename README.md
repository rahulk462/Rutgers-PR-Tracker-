# Rutgers Track & Field PR Tracker

For each athlete: season best, lifetime PR, meet-by-meet progression, and
how far they are from the Big Ten and NCAA standards you set.

```
pip install -r requirements.txt
python scraper.py import-csv data/sample/demo_results.csv   # fake demo athletes
STANDARDS_FILE=standards.example.yaml streamlit run app.py
```

## Getting results in

**Read this first: TFRRS doesn't allow scraping without permission.** Its
[Terms of Use](https://www.tfrrs.org/tos.html) say you may not use "any robot,
spider, scraper, or other automated means to access the sites for any purpose
without our express written permission", and its robots.txt blocks
`/all_performances`, `/top_performances` and similar list pages for everyone.
Permission comes from DirectAthletics (info@directathletics.com).

So there are three ways in, all landing in the same raw tables:

| Command | Use it when |
|---|---|
| `python scraper.py import-csv FILE.csv` | You have results in a spreadsheet (typed in, exported from meet software, etc.) |
| `python scraper.py import-html PAGE.html --gender women` | You saved TFRRS athlete pages from your browser |
| `TFRRS_WRITTEN_PERMISSION=yes python scraper.py fetch --team-url URL` | DirectAthletics has given you written permission |

`fetch` refuses to contact tfrrs.org unless `TFRRS_WRITTEN_PERMISSION=yes` is set.
With it set, it still behaves politely: obeys robots.txt, waits 5 s between
requests (`--delay`), caches every page for 24 h, and re-checks stale pages
with `If-None-Match` / `If-Modified-Since` so unchanged pages aren't downloaded
again. Pass the men's and women's team pages as two `--team-url`s
(team URLs contain `_m_` or `_f_`, which is how gender is set).

The TFRRS page parser was written from the general layout of TFRRS athlete
pages and has **not yet been checked against a real saved page**. Import one
page and compare it with the site before relying on it.

### CSV format

One row per performance. Header names are case-insensitive; blank is fine
for anything optional.

| Column | Example | Notes |
|---|---|---|
| athlete | Jane Doe | required |
| athlete_id | 7654321 | optional; TFRRS id keeps same-name athletes apart |
| gender | women | men/women or m/f |
| event | 60 Hurdles | most spellings work: `100`, `100m`, `100 Meters`, `LJ`, `Long Jump`, `8K` |
| mark | 1:52.34 | `10.45`, `7.12m`, `23-4.5`, `23' 4.5"`, `10.4h`, `DNF`, `DNS`, `DQ`, `FOUL`, `NM`, `NH` |
| wind | +1.8 | m/s; blank or `NWI` if none |
| meet | Penn Relays | |
| date | 2026-04-25 | also `04/25/2026`, `Apr 25-27, 2026` |
| season | Outdoor | optional; inferred from event and date if blank |
| place | 3 | |
| round | F | F/P/SF or Final/Prelim |

## How marks are handled

- Running events are stored in seconds, field events in meters, multis in points.
  Feet-inches are converted to meters.
- **Lower is better for running, higher for field and multis.** That rule lives
  only in `events.py` (`sort_key`, `is_better`, `pct_off`).
- **Wind-aided** (wind over +2.0 m/s, outdoor 100/200/100H/110H/LJ/TJ, or a `w`
  on the mark) and **hand times** (an `h` on the mark) are kept and shown, but
  don't count toward PRs or season bests unless you tick
  "Count wind-aided and hand times". Exactly +2.0 is legal.
- Indoor, outdoor and XC are separate: the PR shown next to an indoor 200m is the
  best indoor 200m.
- DNF/DNS/DQ/FOUL/NM/NH are kept in the athlete's history. Anything unreadable is
  kept as `UNPARSED` rather than dropped. Relays are recognised but left out of
  individual PRs.

## Standards

`standards.yaml` is yours to fill in from the official documents. It starts
blank, and the tracker never guesses a value. Write marks as they appear in
results (`"10.25"`, `"1:47.50"`, `"7.80m"`). You can add standards (e.g. `"NCAA East"`)
by adding them to the `standards:` list. `standards.example.yaml` has **made-up**
numbers for trying the demo only.

"% off" is how far the season best is from the standard: 0 or below means met.

## Data storage

SQLite at `data/tracker.db` (ignored by git).

- **Raw first:** every imported file or page is saved under `data/raw/` by content
  hash and never overwritten. Its rows go into `raw_performances` exactly as found;
  database triggers block any UPDATE or DELETE on raw tables.
- **Clean second:** `performances` is rebuilt from raw on every import
  (`python scraper.py rebuild` to redo it by hand). Re-importing the same
  results doesn't create duplicates.

## Code

| File | Job |
|---|---|
| `events.py` | event names, groups, lower/higher-is-better, formatting |
| `parse.py` | marks, wind, dates, seasons, raw → clean, TFRRS page parsing |
| `scraper.py` | imports and the permission-gated polite fetcher (CLI) |
| `db.py` | SQLite schema, raw insert, clean rebuild |
| `analysis.py` | season bests, PRs, progression, % off standards |
| `app.py` | Streamlit dashboard |

Tests: `python -m pytest`
