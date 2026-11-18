"""Parsers for bonbama.ir public pages — stdlib only (re, json, html, xml).

Data sources (all public, server-rendered HTML, no login):
- Business pages: JSON-LD (LocalBusiness/Organization + makesOffer) is the
  primary source; the visible description text carries literal discount
  codes ("کدهای تخفیف فعال … OFF50 — …").
- Search pages (/search?q=…&mode=company|campaign): result cards live in
  the #companies-feed container.
- Category pages (/company-categories/<slug>): business cards under the
  "کسب‌وکارهای …" heading.
- Homepage: the category directory (names + business/campaign counts).
- Articles index (/articles?page=N): article cards with <h2> titles.
- Sitemaps: full URL inventories (companies, categories, articles).

Nothing is hardcoded: every campaign, code, price and expiry is read live
from the page at call time.
"""
from __future__ import annotations

import html as _html
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET

BASE = "https://bonbama.ir"

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"


def fa_to_en(text: str) -> str:
    """Normalize Persian/Arabic-Indic digits to ASCII digits."""
    return text.translate(_FA_DIGITS)


def _to_int(text: str | None) -> int | None:
    if not text:
        return None
    try:
        return int(fa_to_en(text).replace(",", "").replace("٬", "").strip())
    except ValueError:
        return None


def strip_tags(fragment: str) -> str:
    """Strip HTML tags + scripts/styles, unescape entities, collapse space."""
    fragment = re.sub(r"<script[^>]*>.*?</script>", " ", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<style[^>]*>.*?</style>", " ", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = _html.unescape(fragment)
    return re.sub(r"\s+", " ", fragment).strip()


def _meta_content(page: str, key: str) -> str | None:
    m = re.search(
        r'<meta[^>]+(?:name|property)=["\']%s["\'][^>]+content=["\']([^"\']*)["\']'
        % re.escape(key),
        page,
        re.I,
    )
    if not m:
        m = re.search(
            r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:name|property)=["\']%s["\']'
            % re.escape(key),
            page,
            re.I,
        )
    return _html.unescape(m.group(1)).strip() if m else None


def _page_title(page: str) -> str | None:
    m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    return _html.unescape(m.group(1)).strip() if m else None


# ---------------------------------------------------------------- sitemap

def parse_sitemap(xml_text: str) -> list[dict]:
    """Parse a sitemap XML file -> [{url, lastmod}]."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"invalid sitemap XML: {e}") from e
    out: list[dict] = []
    for url_el in root.iter():
        if not url_el.tag.endswith("url"):
            continue
        loc = lastmod = None
        for child in url_el:
            if child.tag.endswith("loc"):
                loc = (child.text or "").strip()
            elif child.tag.endswith("lastmod"):
                lastmod = (child.text or "").strip()
        if loc:
            out.append({"url": loc, "lastmod": lastmod})
    return out


# ---------------------------------------------------------------- business page

_JSONLD_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.S | re.I
)
_CODE_SECTION_RE = re.compile(r"کدهای تخفیف فعال")
_CODE_LINE_RE = re.compile(
    r"([A-Z][A-Z0-9]{2,15})\s*[—–\-:]\s*([^؛.\n]{5,150})"
)


def _jsonld_graphs(page: str) -> list[dict]:
    graphs: list[dict] = []
    for raw in _JSONLD_RE.findall(page):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            graphs.append(data)
    return graphs


def _business_node(page: str, url: str) -> dict | None:
    """The JSON-LD LocalBusiness/Organization node for THIS business page.

    The site-wide Organization (bonbama.ir/#organization) is excluded: we
    want the node whose @id points at this business URL, or (fallback) the
    node that carries makesOffer.
    """
    fallback = None
    for data in _jsonld_graphs(page):
        for node in data.get("@graph", []) or []:
            if not isinstance(node, dict):
                continue
            if node.get("@type") not in ("LocalBusiness", "Organization"):
                continue
            node_id = node.get("@id", "")
            if node_id.startswith(url):
                return node
            if node.get("makesOffer") and fallback is None:
                fallback = node
    return fallback


def _breadcrumb_category(page: str) -> dict | None:
    for data in _jsonld_graphs(page):
        for node in data.get("@graph", []) or []:
            if not isinstance(node, dict) or node.get("@type") != "BreadcrumbList":
                continue
            items = node.get("itemListElement", []) or []
            if len(items) >= 2:
                cat = items[1]
                return {"name": cat.get("name"), "url": cat.get("item")}
    return None


def _extract_codes(page: str) -> list[dict]:
    """Literal discount codes from the visible description text.

    Editors maintain a "کدهای تخفیف فعال <name> (آخرین بررسی: …)" section
    with lines like "OFF50 — ۵۰٪ تخفیف اولین خرید؛ …". Only codes from
    that section are returned; nothing is guessed. Codes generated
    per-user behind the "دریافت کد" button (login) are NOT public and
    are never returned.
    """
    text = strip_tags(page)
    m = _CODE_SECTION_RE.search(text)
    if not m:
        return []
    window = text[m.start():m.start() + 2500]
    codes: list[dict] = []
    seen: set[str] = set()
    for code, note in _CODE_LINE_RE.findall(window):
        if code in seen:
            continue
        # skip tokens that are clearly not codes (long words, URLs parts)
        if len(code) > 12:
            continue
        seen.add(code)
        codes.append({"code": code, "note": note.strip()})
    return codes


def parse_business_page(page: str, url: str) -> dict:
    """Parse a business page (/b/<slug> or /companies/<slug>)."""
    node = _business_node(page, url)
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    out: dict = {"slug": slug, "url": url}

    if node:
        out["name"] = node.get("name")
        out["description"] = node.get("description") or _meta_content(
            page, "og:description"
        )
        out["image"] = node.get("image")
        addr = node.get("address") or {}
        out["city"] = node.get("areaServed") or addr.get("addressLocality")
        street = addr.get("streetAddress")
        locality = addr.get("addressLocality")
        out["address"] = (
            "، ".join(p for p in (street, locality) if p) or None
        )
        out["telephone"] = node.get("telephone")
        rating = node.get("aggregateRating") or {}
        out["rating"] = rating.get("ratingValue")
        out["review_count"] = _to_int(str(rating.get("reviewCount", "")))
        campaigns = []
        for offer in node.get("makesOffer", []) or []:
            discount = None
            for prop in offer.get("additionalProperty", []) or []:
                if prop.get("name") == "میزان تخفیف":
                    discount = prop.get("value")
            desc = (offer.get("description") or "").strip()
            campaigns.append(
                {
                    "title": offer.get("name"),
                    "description": desc[:300] if desc else None,
                    "url": offer.get("url"),
                    "valid_through": offer.get("validThrough"),
                    "discount": discount,
                    "availability": (offer.get("availability") or "").replace(
                        "https://schema.org/", ""
                    )
                    or None,
                }
            )
        out["campaigns"] = campaigns
    else:
        out["name"] = _page_title(page)
        out["description"] = _meta_content(page, "og:description")
        out["image"] = None
        out["city"] = out["address"] = out["telephone"] = None
        out["rating"] = out["review_count"] = None
        out["campaigns"] = []

    out["category"] = _breadcrumb_category(page)
    out["codes"] = _extract_codes(page)
    out["campaign_count"] = len(out["campaigns"])
    return out


# ---------------------------------------------------------------- search / feeds

def _feed_region(page: str) -> str:
    """The #companies-feed container (search results live here)."""
    start = page.find('id="companies-feed"')
    if start < 0:
        return ""
    end = page.find('id="companies-feed-end"', start)
    if end < 0:
        end = page.find('id="companies-feed-pagination"', start)
    if end < 0:
        end = len(page)
    return page[start:end]


_ANCHOR_RE = re.compile(
    r'<a\s+href="(https://bonbama\.ir/(?:b|companies)/[^"?#]+)"[^>]*>(.*?)</a>',
    re.S | re.I,
)
_CAMPAIGN_ANCHOR_RE = re.compile(
    r'<a\s+href="(https://bonbama\.ir/(?:b|companies)/[^"?#]+\?campaign=[^"#]+)"[^>]*>(.*?)</a>',
    re.S | re.I,
)


def _parse_company_card(url: str, inner: str) -> dict:
    # The card image alt is the clean business name ("تیچر یاسی"); the
    # visible text varies by page ("1 کمپین تستینو …" on search,
    # "<name> <category> <city> <rating> (N نظر) … N کمپین فعال" on
    # category pages), so alt wins and text is the fallback.
    alt = re.search(r'alt="([^"]+)"', inner)
    text = strip_tags(inner)
    campaigns = None
    m = re.search(r"([\d۰-۹]+)\s*کمپین فعال", text)
    if m:
        campaigns = _to_int(m.group(1))
    else:
        # search cards lead with "N کمپین <name>"
        m0 = re.match(r"([\d۰-۹]+)\s*کمپین\s+", text)
        if m0:
            campaigns = _to_int(m0.group(1))
    name = _html.unescape(alt.group(1)).strip() if alt else None
    if not name:
        m2 = re.match(r"([\d۰-۹]+)\s*کمپین\s+(.+)$", text)
        if m2:
            campaigns = _to_int(m2.group(1))
            name = m2.group(2)
        else:
            name = text
        name = re.split(r"\s*شهرهای فعال", name)[0].strip()
        name = re.sub(r"\s*ثبت نشده است\.?\s*$", "", name).strip()
    return {
        "name": name or None,
        "url": url,
        "slug": url.rstrip("/").rsplit("/", 1)[-1],
        "campaigns": campaigns,
    }


def parse_search_companies(page: str) -> list[dict]:
    """Business cards from a mode=company search page."""
    region = _feed_region(page)
    out, seen = [], set()
    for url, inner in _ANCHOR_RE.findall(region):
        if url in seen:
            continue
        seen.add(url)
        out.append(_parse_company_card(url, inner))
    return out


_CAMPAIGN_TEXT_RE = re.compile(
    r"^(?P<business>.+?)\s+اعتبار تا\s+(?P<expiry>\d{4}/\d{2}/\d{2})\s+"
    r"(?P<title>.+?)\s+"
    r"(?:تا\s*[٪%](?P<pct>[\d۰-۹]+)\s+تخفیف|(?P<amount>[\d,٬۰-۹]+)\s+تومان تخفیف)"
    r"\s+(?P<sent>[\d,٬۰-۹]+)\s+ارسال‌شده"
)


def _parse_campaign_card(url: str, inner: str) -> dict:
    text = strip_tags(inner)
    # Card text: "<business> اعتبار تا 1405/09/30 <title> تا ٪20 تخفیف
    # 1,105 ارسال‌شده مشاهده" (or "<amount> تومان تخفیف" instead of ٪).
    m = _CAMPAIGN_TEXT_RE.match(text)
    base_url = url.split("?")[0]
    card = {
        "url": url,
        "business_url": base_url,
        "business_slug": base_url.rstrip("/").rsplit("/", 1)[-1],
    }
    if m:
        card["business"] = m.group("business").strip()
        card["expiry_jalali"] = m.group("expiry")
        card["title"] = m.group("title").strip()
        pct = m.group("pct")
        amount = m.group("amount")
        card["discount"] = (
            f"{fa_to_en(pct)}%" if pct else f"{fa_to_en(amount)} تومان"
        )
        card["sent_count"] = _to_int(m.group("sent"))
    else:
        card["business"] = None
        card["expiry_jalali"] = None
        card["title"] = text[:200] or None
        card["discount"] = None
        card["sent_count"] = None
    return card


def parse_search_campaigns(page: str) -> list[dict]:
    """Campaign cards from a mode=campaign search page."""
    region = _feed_region(page)
    out, seen = [], set()
    for url, inner in _CAMPAIGN_ANCHOR_RE.findall(region):
        if url in seen:
            continue
        seen.add(url)
        out.append(_parse_campaign_card(url, inner))
    return out


# ---------------------------------------------------------------- category page

def parse_category_businesses(page: str) -> list[dict]:
    """Businesses listed on a /company-categories/<slug> page.

    The listing sits under the "کسب‌وکارهای …" heading; slice to it so
    sidebar/footer business links don't leak in. Falls back to the whole
    page when the heading markers are absent.
    """
    start = page.find("کسب‌وکارهای")
    if start >= 0:
        end = len(page)
        for marker in ("راهنمای «", "سؤالات متداول", "دسته‌های دیگر"):
            j = page.find(marker, start + 10)
            if j > start:
                end = min(end, j)
        region = page[start:end]
    else:
        region = page
    out, seen = [], set()
    for url, inner in _ANCHOR_RE.findall(region):
        if url in seen:
            continue
        seen.add(url)
        out.append(_parse_company_card(url, inner))
    return out


# ---------------------------------------------------------------- homepage categories

_CAT_ANCHOR_RE = re.compile(
    r'<a\s+href="https://bonbama\.ir/company-categories/([^"?#]+)"[^>]*>(.*?)</a>',
    re.S | re.I,
)
_CAT_COUNTS_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<biz>[\d۰-۹]+)\s*کسب‌وکار\s*،?\s*(?P<camp>[\d۰-۹]+)\s*تخفیف"
)


def parse_home_categories(page: str) -> list[dict]:
    """Category directory from the homepage: slug, Persian name, counts."""
    by_slug: dict[str, dict] = {}
    for slug, inner in _CAT_ANCHOR_RE.findall(page):
        text = strip_tags(inner)
        if not text:
            continue
        m = _CAT_COUNTS_RE.match(text)
        if m:
            entry = {
                "slug": slug,
                "name": m.group("name").strip(),
                "url": f"{BASE}/company-categories/{slug}",
                "businesses": _to_int(m.group("biz")),
                "campaigns": _to_int(m.group("camp")),
            }
        else:
            # parent categories carry promo text ("… تا 100% …") — the name
            # is the part before the first " تا ". Some links read
            # "همه «<name>»" (view-all) — unwrap that too.
            name = text.split(" تا ")[0].strip()
            m_all = re.fullmatch(r"همه «(.+)»", name)
            if m_all:
                name = m_all.group(1).strip()
            if not name or len(name) > 60:
                continue
            entry = {
                "slug": slug,
                "name": name,
                "url": f"{BASE}/company-categories/{slug}",
                "businesses": None,
                "campaigns": None,
            }
        prev = by_slug.get(slug)
        # prefer the entry that carries counts
        if prev is None or (prev["businesses"] is None and entry["businesses"] is not None):
            by_slug[slug] = entry
    return sorted(by_slug.values(), key=lambda c: c["slug"])


# ---------------------------------------------------------------- articles index

_ARTICLE_ANCHOR_RE = re.compile(
    r'<a\s+href="(https://bonbama\.ir/articles/([^"?#/]+))"[^>]*>(.*?)</a>',
    re.S | re.I,
)
_DATE_RE = re.compile(r"(\d{4}/\d{2}/\d{2})")
_VIEWS_RE = re.compile(r"([\d,٬۰-۹]+)\s*بازدید")


def parse_articles_index(page: str) -> list[dict]:
    """Article cards from an /articles index page."""
    out, seen = [], set()
    for url, slug, inner in _ARTICLE_ANCHOR_RE.findall(page):
        if url in seen:
            continue
        seen.add(url)
        # featured card uses <h2>, the rest <h3>
        h = re.search(r"<h[23][^>]*>(.*?)</h[23]>", inner, re.S | re.I)
        title = strip_tags(h.group(1)) if h else None
        if not title:
            continue
        text = strip_tags(inner)
        date_m = _DATE_RE.search(text)
        views_m = _VIEWS_RE.search(text)
        out.append(
            {
                "title": title,
                "url": url,
                "slug": urllib.parse.unquote(slug),
                "date_jalali": date_m.group(1) if date_m else None,
                "views": _to_int(views_m.group(1)) if views_m else None,
            }
        )
    return out
