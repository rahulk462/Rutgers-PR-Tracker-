import pytest

import scraper


class FakeResp:
    def __init__(self, status=200, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}
        self.content = text.encode()
        self.ok = status < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls, self.headers = pages, [], {}

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, dict(headers or {})))
        return self.pages[url](headers or {})


def test_tfrrs_requires_written_permission(monkeypatch, tmp_path):
    monkeypatch.delenv(scraper.PERMISSION_ENV, raising=False)
    f = scraper.PoliteFetcher(cache_dir=tmp_path, delay=0, session=FakeSession({}))
    with pytest.raises(scraper.PermissionRequired):
        f.get("https://www.tfrrs.org/teams/tf/X.html")
    assert f.session.calls == []


def test_cache_conditional_requests_and_robots(monkeypatch, tmp_path):
    monkeypatch.setenv(scraper.PERMISSION_ENV, "yes")
    url = "https://www.tfrrs.org/athletes/1/A.html"
    pages = {
        "https://www.tfrrs.org/robots.txt": lambda h: FakeResp(text="User-agent: *\nDisallow: /all_performances\n"),
        url: lambda h: FakeResp(304) if h.get("If-None-Match") == "v1" else FakeResp(text="<html>A</html>",
                                                                                    headers={"ETag": "v1"}),
        "https://www.tfrrs.org/all_performances/x": lambda h: FakeResp(text="nope"),
    }
    s = FakeSession(pages)
    f = scraper.PoliteFetcher(cache_dir=tmp_path, delay=0, session=s)
    html, path = f.get(url)
    assert html == "<html>A</html>" and path.exists()
    f.get(url)                                    # fresh cache: no request
    assert [c[0] for c in s.calls].count(url) == 1
    f.max_age = 0                                 # stale: conditional request -> 304
    html2, path2 = f.get(url)
    assert html2 == html and path2 == path
    assert s.calls[-1][1].get("If-None-Match") == "v1"
    with pytest.raises(scraper.PermissionRequired):
        f.get("https://www.tfrrs.org/all_performances/x")
