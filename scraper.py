"""Get results into the raw tables.

Three ways in:
  import-csv   a CSV with one row per performance (see README for columns)
  import-html  TFRRS athlete pages you saved from your browser
  fetch        live download from TFRRS, ONLY with written permission

TFRRS's Terms of Use (tfrrs.org/tos.html) forbid any robot, spider or
scraper "for any purpose without our express written permission"
(DirectAthletics: info@directathletics.com). So `fetch` refuses to touch
tfrrs.org unless you set TFRRS_WRITTEN_PERMISSION=yes, confirming you
have that permission. Even then it is polite: it obeys robots.txt, waits
between requests, caches every page, and sends conditional requests so
unchanged pages are not downloaded again.

Usage:
  python scraper.py import-csv results.csv
  python scraper.py import-html saved_pages/*.html --gender women
  TFRRS_WRITTEN_PERMISSION=yes python scraper.py fetch --team-url URL [--team-url URL]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

import db
import parse

DATA_DIR = Path(__file__).parent / "data"
RAW_HTML_DIR = DATA_DIR / "raw" / "html"
RAW_CSV_DIR = DATA_DIR / "raw" / "csv"

USER_AGENT = "RutgersPRTracker/0.1 (personal coaching tool; low-rate)"
PERMISSION_ENV = "TFRRS_WRITTEN_PERMISSION"
RESTRICTED_HOSTS = ("tfrrs.org",)


class PermissionRequired(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def store_raw_file(data: bytes, directory: Path, suffix: str) -> tuple[str, Path]:
    """Save content under its hash. Existing files are never overwritten."""
    directory.mkdir(parents=True, exist_ok=True)
    sha = db.content_hash(data)
    path = directory / f"{sha}{suffix}"
    if not path.exists():
        path.write_bytes(data)
    return sha, path


class PoliteFetcher:
    """Cached, rate-limited, robots-respecting HTTP GET."""

    def __init__(self, cache_dir: Path = RAW_HTML_DIR, delay: float = 5.0,
                 max_age_hours: float = 24.0, session: requests.Session | None = None):
        self.cache_dir = Path(cache_dir)
        self.index_path = self.cache_dir / "index.json"
        self.delay = delay
        self.max_age = max_age_hours * 3600
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last_request = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self.index = json.loads(self.index_path.read_text()) if self.index_path.exists() else {}

    # -- guards --
    @staticmethod
    def check_permission(url: str) -> None:
        host = urlparse(url).hostname or ""
        restricted = any(host == h or host.endswith("." + h) for h in RESTRICTED_HOSTS)
        if restricted and os.environ.get(PERMISSION_ENV, "").lower() != "yes":
            raise PermissionRequired(
                f"{host} does not allow automated access without written permission "
                f"(see https://www.tfrrs.org/tos.html). Once DirectAthletics has given you "
                f"permission, set {PERMISSION_ENV}=yes. Until then use import-csv or import-html.")

    def _wait(self) -> None:
        gap = time.monotonic() - self._last_request
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last_request = time.monotonic()

    def allowed_by_robots(self, url: str) -> bool:
        parts = urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            self._wait()
            resp = self.session.get(root + "/robots.txt", timeout=30)
            rp.parse(resp.text.splitlines() if resp.ok else [])
            self._robots[root] = rp
        return self._robots[root].can_fetch(USER_AGENT, url)

    # -- fetch --
    def get(self, url: str) -> tuple[str, Path]:
        """Return (html, raw_file_path). Uses the cache when fresh, and a
        conditional request (ETag / Last-Modified) when stale."""
        self.check_permission(url)
        entry = self.index.get(url)
        if entry:
            age = time.time() - entry["fetched_ts"]
            path = self.cache_dir / entry["file"]
            if age < self.max_age and path.exists():
                return path.read_text(encoding="utf-8"), path
        if not self.allowed_by_robots(url):
            raise PermissionRequired(f"robots.txt disallows {url}")

        headers = {}
        if entry:
            if entry.get("etag"):
                headers["If-None-Match"] = entry["etag"]
            if entry.get("last_modified"):
                headers["If-Modified-Since"] = entry["last_modified"]
        resp = self._request(url, headers)
        if resp.status_code == 304 and entry:
            entry["fetched_ts"] = time.time()
            self._save_index()
            path = self.cache_dir / entry["file"]
            return path.read_text(encoding="utf-8"), path
        resp.raise_for_status()
        sha, path = store_raw_file(resp.content, self.cache_dir, ".html")
        self.index[url] = {"file": path.name, "sha": sha, "fetched_ts": time.time(),
                           "fetched_at": _now(), "etag": resp.headers.get("ETag"),
                           "last_modified": resp.headers.get("Last-Modified")}
        self._save_index()
        return resp.text, path

    def _request(self, url: str, headers: dict, tries: int = 3) -> requests.Response:
        for attempt in range(tries):
            self._wait()
            resp = self.session.get(url, headers=headers, timeout=30)
            if resp.status_code not in (429, 500, 502, 503, 504):
                return resp
            retry_after = resp.headers.get("Retry-After", "")
            time.sleep(float(retry_after) if retry_after.isdigit() else self.delay * 2 ** (attempt + 1))
        return resp

    def _save_index(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(self.index, indent=1))


# --- importers -------------------------------------------------------------

def import_csv(con, path: str | Path) -> int:
    data = Path(path).read_bytes()
    sha, saved = store_raw_file(data, RAW_CSV_DIR, ".csv")
    text = data.decode("utf-8-sig")
    rows = []
    for r in csv.DictReader(text.splitlines()):
        r = {k.strip().lower(): v for k, v in r.items() if k}
        if "athlete" in r and "athlete_name" not in r:
            r["athlete_name"] = r.pop("athlete")
        rows.append(r)
    return db.add_raw(con, sha, "csv", str(path), str(saved), rows)


def import_html(con, path: str | Path, gender: str | None = None, origin: str | None = None) -> int:
    data = Path(path).read_bytes()
    sha, saved = store_raw_file(data, RAW_HTML_DIR, ".html")
    rows = parse.parse_tfrrs_athlete_page(data.decode("utf-8", errors="replace"), gender=gender)
    return db.add_raw(con, sha, "tfrrs_html", origin or str(path), str(saved), rows)


def fetch_team(con, team_urls: list[str], fetcher: PoliteFetcher | None = None) -> int:
    fetcher = fetcher or PoliteFetcher()
    added = 0
    for team_url in team_urls:
        gender = "m" if "_m_" in team_url else "f" if "_f_" in team_url else None
        roster_html, _ = fetcher.get(team_url)
        athletes = parse.parse_tfrrs_roster_page(roster_html)
        print(f"{team_url}: {len(athletes)} athletes")
        for i, url in enumerate(athletes, 1):
            html, saved = fetcher.get(url)
            rows = parse.parse_tfrrs_athlete_page(html, gender=gender)
            added += db.add_raw(con, db.content_hash(html), "tfrrs_html", url, str(saved), rows)
            print(f"  [{i}/{len(athletes)}] {url} ({len(rows)} marks)")
    return added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import-csv"); p.add_argument("files", nargs="+")
    p = sub.add_parser("import-html"); p.add_argument("files", nargs="+")
    p.add_argument("--gender", choices=["men", "women"], help="if the page doesn't show it")
    p = sub.add_parser("fetch"); p.add_argument("--team-url", action="append", required=True)
    p.add_argument("--delay", type=float, default=5.0, help="seconds between requests")
    sub.add_parser("rebuild", help="re-derive the clean table from raw data")
    args = ap.parse_args(argv)

    con = db.connect(args.db)
    added = 0
    try:
        if args.cmd == "import-csv":
            added = sum(import_csv(con, f) for f in args.files)
        elif args.cmd == "import-html":
            added = sum(import_html(con, f, gender=args.gender) for f in args.files)
        elif args.cmd == "fetch":
            added = fetch_team(con, args.team_url, PoliteFetcher(delay=args.delay))
    except PermissionRequired as e:
        print(f"Stopped: {e}", file=sys.stderr)
        return 2
    n = db.rebuild_clean(con)
    print(f"{added} new raw rows; {n} clean performances.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
