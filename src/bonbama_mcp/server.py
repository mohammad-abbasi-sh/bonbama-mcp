"""MCP server: unofficial read-only access to bonbama.ir (Gorgan discounts).

Two transports, one tool set:
- stdio (default, local use via uvx):  `bonbama-mcp`
- streamable HTTP (hosted, e.g. for Bazaar MCP Hub):
  `bonbama-mcp --transport streamable-http --host 0.0.0.0 --port 8000`
  serves MCP at /mcp and a liveness probe at /health (no network call).
  Or with uvicorn directly: `uvicorn bonbama_mcp.server:app --port 8000`.

All data is read LIVE from bonbama.ir public pages at call time — campaigns,
codes, prices and expiries are never hardcoded.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from . import bonbama as _bb
from . import http as _http

mcp = FastMCP(
    "bonbama-mcp",
    instructions=(
        "Unofficial read-only MCP server for bonbama.ir — Gorgan's discount "
        "platform: local businesses, discount codes and campaigns, business "
        "categories, and magazine articles. All data is read live from "
        "bonbama.ir public pages at call time; codes, prices and expiries "
        "change, so always report the fetched_at time and tell the user to "
        "verify on the business page before buying. Discount codes shown "
        "come from the business page text; some campaigns need the user to "
        "press «دریافت کد» on bonbama.ir (free, needs a free account) to "
        "generate their personal code/QR.\n"
        "Built by Mohammad Abbasi (mohammad-abbasi-sh) — "
        "https://almanibama.ir · https://mabbasi.ir"
    ),
    host=os.environ.get("BONBAMA_MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("BONBAMA_MCP_PORT", "8000")),
    streamable_http_path="/mcp",
    stateless_http=True,  # no session affinity — safe behind any proxy
)

INSTRUCTIONS = mcp.instructions or ""

_SOURCE = "bonbama.ir"
_DISCLAIMER = (
    "Unofficial read-only data from bonbama.ir; "
    "verify codes and expiries on the business page before acting on them."
)


def _envelope() -> dict:
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": _SOURCE,
        "disclaimer": _DISCLAIMER,
    }


def _ok(payload: dict) -> str:
    return json.dumps({**_envelope(), **payload}, ensure_ascii=False)


def _limit_arg(limit: int, default: int = 10, cap: int = 30) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(cap, n))


@mcp.tool()
def bb_search_businesses(query: str = "", category: str = "", limit: int = 10) -> str:
    """Search Bonbama businesses by keyword and/or category.

    query: Persian/English keyword (e.g. "ناخن", "testino"). category: a
    category slug from bb_list_categories (e.g. "zban", "rstoran").
    Give at least one of query/category. Returns name, URL, slug and
    active-campaign count per business.
    """
    limit = _limit_arg(limit)
    query = (query or "").strip()
    category = (category or "").strip().strip("/")
    try:
        if category:
            page = _http.fetch_category_page(category)
            results = _bb.parse_category_businesses(page)
            if query:
                q = query.lower()
                results = [
                    r
                    for r in results
                    if q in (r.get("name") or "").lower()
                    or q in r.get("slug", "").lower()
                ]
            scope = {"category": category, "query": query or None}
        elif query:
            page = _http.fetch_search(query, mode="company")
            results = _bb.parse_search_companies(page)
            scope = {"query": query}
        else:
            return _ok(
                {
                    "error": "give a query and/or a category slug "
                    "(see bb_list_categories)"
                }
            )
    except _http.BonbamaError as e:
        return _ok({"error": str(e)})
    return _ok({**scope, "count": len(results[:limit]), "businesses": results[:limit]})


@mcp.tool()
def bb_get_business(slug: str) -> str:
    """Full details for one business: name, description, city, address,
    rating, category, ACTIVE campaigns (title, discount, expiry — read
    live from the page) and any literal discount codes published on the
    page. slug: e.g. "testino", "takchh" (from bb_search_businesses)."""
    slug = (slug or "").strip().strip("/")
    if not slug:
        return _ok({"error": "slug is required"})
    try:
        page, url = _http.fetch_business_page(slug)
    except _http.BonbamaError as e:
        return _ok({"error": str(e)})
    return _ok(_bb.parse_business_page(page, url))


@mcp.tool()
def bb_list_categories() -> str:
    """All Bonbama business categories with Persian names and (where the
    homepage publishes them) business/campaign counts. Use the slug with
    bb_search_businesses(category=...)."""
    try:
        page = _http.fetch_home()
    except _http.BonbamaError as e:
        return _ok({"error": str(e)})
    cats = _bb.parse_home_categories(page)
    return _ok({"count": len(cats), "categories": cats})


@mcp.tool()
def bb_search_discounts(query: str = "", limit: int = 10) -> str:
    """Search ACTIVE discount campaigns site-wide by keyword (e.g. "کفش",
    "شهربازی"). With no query, returns current popular campaigns.
    Each result: business, campaign title, discount, Jalali expiry,
    campaign URL and how many codes were sent."""
    limit = _limit_arg(limit)
    query = (query or "").strip()
    try:
        # No query: the site has no "all campaigns" feed, so search the
        # generic term — it matches essentially every discount campaign.
        page = _http.fetch_search(query or "تخفیف", mode="campaign")
        results = _bb.parse_search_campaigns(page)
    except _http.BonbamaError as e:
        return _ok({"error": str(e)})
    return _ok(
        {
            "query": query or None,
            "count": len(results[:limit]),
            "campaigns": results[:limit],
        }
    )


@mcp.tool()
def bb_search_articles(query: str, limit: int = 10) -> str:
    """Search the Bonbama magazine (buying guides, discount explainers,
    best-of-Gorgan lists). query: Persian/English keyword. Matches
    article titles on the latest index pages and URL slugs."""
    limit = _limit_arg(limit)
    query = (query or "").strip()
    if not query:
        return _ok({"error": "query is required"})
    q = query.lower()
    matches: list[dict] = []
    seen: set[str] = set()
    try:
        # Latest-first index pages; stop once we have enough (max 4 pages).
        for page_no in range(1, 5):
            page = _http.fetch_articles_page(page_no)
            for art in _bb.parse_articles_index(page):
                if art["url"] in seen:
                    continue
                seen.add(art["url"])
                if q in art["title"].lower() or q in art["slug"].lower():
                    matches.append(art)
                    if len(matches) >= limit:
                        break
            if len(matches) >= limit:
                break
        # Slug fallback: the sitemap lists every article URL (transliterated
        # slugs match Latin keywords like "black-friday").
        if len(matches) < limit:
            try:
                sm = _bb.parse_sitemap(_http.fetch_sitemap("articles"))
            except _http.BonbamaError:
                sm = []
            for entry in sm:
                url = entry["url"]
                if url in seen:
                    continue
                slug = url.rstrip("/").rsplit("/", 1)[-1]
                if q in slug.lower():
                    seen.add(url)
                    matches.append(
                        {
                            "title": None,
                            "url": url,
                            "slug": slug,
                            "date_jalali": None,
                            "views": None,
                            "note": "title not fetched; matched by URL slug",
                        }
                    )
                    if len(matches) >= limit:
                        break
    except _http.BonbamaError as e:
        return _ok({"error": str(e)})
    return _ok({"query": query, "count": len(matches), "articles": matches})


@mcp.tool()
def bb_health() -> str:
    """Check whether bonbama.ir is reachable right now.

    Returns status ok (HTTP 200), blocked (HTTP 403/429 — bot wall or
    rate limit) or error, plus the HTTP status and the probed URL.
    One polite request; it does not fetch any listings."""
    return _ok(_http.health_check())


# ------------------------------------------------------------------ HTTP app

def _build_http_app():
    """Starlette app: MCP streamable HTTP at /mcp + liveness at /health.

    /health is a plain liveness probe (no network call) for load
    balancers / Docker HEALTHCHECK. The live bonbama.ir probe is the
    bb_health tool.
    """
    from contextlib import asynccontextmanager

    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        # The session manager's task group is started by the MCP app's
        # lifespan — a plain Mount never runs it, so run it explicitly.
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    async def health(request):
        return JSONResponse(
            {
                "status": "ok",
                "server": "bonbama-mcp",
                "transport": "streamable-http",
                "mcp_path": "/mcp",
            }
        )

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Mount("/", app=mcp_app),
        ],
        lifespan=lifespan,
    )


# ASGI entrypoint for uvicorn/gunicorn: `uvicorn bonbama_mcp.server:app`
app = _build_http_app()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bonbama-mcp",
        description="Unofficial read-only MCP server for bonbama.ir",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="stdio (default, local uvx use) or streamable-http (hosted)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("BONBAMA_MCP_HOST", "127.0.0.1"),
        help="host for streamable-http (default 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("BONBAMA_MCP_PORT", "8000")),
        help="port for streamable-http (default 8000)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
        return
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())
