"""HTTP layer for bonbama_mcp — plain httpx against bonbama.ir's public pages.

bonbama.ir is server-rendered HTML (no JS framework, no login, no key).
We only ever GET public pages: sitemaps, search, business/category/article
pages and the homepage. Respectful: one retry on transient errors, polite
timeouts, a real browser User-Agent.
"""
from __future__ import annotations

import os
import time
import urllib.parse

import httpx

BASE = "https://bonbama.ir"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
TIMEOUT = 30.0  # bonbama pages are large (up to ~800KB)


class BonbamaError(RuntimeError):
    pass


def _client() -> httpx.Client:
    # NOTE: we read the proxy URL from the environment but never log it.
    # trust_env=False because httpx fails to parse bracketed IPv6 entries
    # (e.g. [::1]) that some environments put in no_proxy.
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    return httpx.Client(
        headers={"User-Agent": UA, "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8"},
        timeout=TIMEOUT,
        proxy=proxy or None,
        trust_env=False,
        follow_redirects=True,
    )


def _get(url: str) -> str:
    last_exc: Exception | None = None
    r: httpx.Response | None = None
    for attempt in range(2):
        try:
            with _client() as c:
                r = c.get(url)
        except httpx.HTTPError as e:
            last_exc = e
            if attempt == 0:
                time.sleep(1.0)
                continue
            raise BonbamaError(f"network error fetching {url}: {e}") from e
        if r.status_code in (429, 500, 502, 503):
            if attempt == 0:
                time.sleep(1.5)
                continue
        break
    assert r is not None  # loop always assigns r or raises
    if r.status_code == 404:
        raise BonbamaError(f"not found (HTTP 404): {url}")
    if r.status_code == 429:
        raise BonbamaError(
            "bonbama.ir rate-limited the request (HTTP 429) — try again later"
        )
    if r.status_code == 403:
        raise BonbamaError(f"bonbama.ir refused the request (HTTP 403): {url}")
    if r.status_code != 200:
        raise BonbamaError(f"bonbama.ir returned HTTP {r.status_code} for {url}")
    r.encoding = "utf-8"
    return r.text


def fetch_business_page(slug: str) -> tuple[str, str]:
    """Fetch a business page by slug.

    Tries /b/<slug> first, then /companies/<slug> (both URL styles exist).
    Returns (html, resolved_url). Raises BonbamaError if neither exists.
    """
    slug = slug.strip().strip("/")
    for path in (f"/b/{slug}", f"/companies/{slug}"):
        try:
            return _get(f"{BASE}{path}"), f"{BASE}{path}"
        except BonbamaError as e:
            if "404" not in str(e):
                raise
    raise BonbamaError(
        f"no business page found for slug {slug!r} "
        "(tried /b/<slug> and /companies/<slug>)"
    )


def fetch_search(query: str, mode: str = "company") -> str:
    """Fetch the site search page. mode: 'company' or 'campaign'."""
    q = urllib.parse.quote_plus(query)
    return _get(f"{BASE}/search?q={q}&mode={mode}")


def fetch_category_page(slug: str) -> str:
    """Fetch a business-category page (/company-categories/<slug>)."""
    return _get(f"{BASE}/company-categories/{slug.strip().strip('/')}")


def fetch_home() -> str:
    """Fetch the homepage (category directory + popular campaigns)."""
    return _get(f"{BASE}/")


def fetch_sitemap(kind: str) -> str:
    """Fetch one sitemap: 'companies', 'categories', 'articles' or 'pages'."""
    if kind not in ("companies", "categories", "articles", "pages"):
        raise BonbamaError(f"unknown sitemap kind {kind!r}")
    if kind == "pages":
        return _get(f"{BASE}/sitemap-pages.xml")
    return _get(f"{BASE}/sitemap-{kind}-1.xml")


def fetch_articles_page(page: int = 1) -> str:
    """Fetch one page of the articles index (/articles?page=N)."""
    if page <= 1:
        return _get(f"{BASE}/articles")
    return _get(f"{BASE}/articles?page={page}")


def health_check() -> dict:
    """One polite probe of the source site.

    Returns {"status": "ok"|"blocked"|"error", "http_status": int|None,
    "url": ..., "detail": ...}. Used by the `bb_health` tool
    and the daily smoke CI.
    """
    url = f"{BASE}/sitemap.xml"
    try:
        _get(url)
    except BonbamaError as e:
        msg = str(e)
        if "403" in msg:
            return {"status": "blocked", "http_status": 403, "url": url, "detail": msg}
        if "429" in msg:
            return {"status": "blocked", "http_status": 429, "url": url, "detail": msg}
        return {"status": "error", "http_status": None, "url": url, "detail": msg}
    return {"status": "ok", "http_status": 200, "url": url}
