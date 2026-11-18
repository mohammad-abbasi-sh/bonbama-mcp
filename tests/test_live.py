"""Live tests — hit the real bonbama.ir. Cautious: few requests, then stop.

Run:  pytest tests/test_live.py -v
Skip: pytest -m "not live"  (or set BONBAMA_SKIP_LIVE=1)
"""
import os
import pathlib
import sys
import time
import unittest

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from bonbama_mcp import bonbama as _bb
from bonbama_mcp import http as _http

pytestmark = pytest.mark.live
SKIP = os.environ.get("BONBAMA_SKIP_LIVE") == "1"


@pytest.mark.skipif(SKIP, reason="BONBAMA_SKIP_LIVE=1")
class TestLive(unittest.TestCase):
    def test_health_ok(self):
        result = _http.health_check()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["http_status"], 200)
        time.sleep(1)

    def test_business_testino_live(self):
        page, url = _http.fetch_business_page("testino")
        d = _bb.parse_business_page(page, url)
        self.assertEqual(d["name"], "تستینو")
        self.assertGreaterEqual(d["campaign_count"], 1)
        print(f"\nLIVE testino: {d['campaign_count']} campaign(s), "
              f"rating {d['rating']} ({d['review_count']} reviews)")
        time.sleep(1)

    def test_business_companies_path_live(self):
        # takchh is listed under /companies/ in the sitemap; both URL
        # styles serve directly (verified: no redirect either way)
        page, url = _http.fetch_business_page("takchh")
        self.assertIn("takchh", url)
        d = _bb.parse_business_page(page, url)
        self.assertIn("طاقچه", d["name"])
        self.assertGreaterEqual(d["campaign_count"], 1)
        time.sleep(1)

    def test_search_companies_live(self):
        page = _http.fetch_search("تستینو", mode="company")
        results = _bb.parse_search_companies(page)
        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(any(r["slug"] == "testino" for r in results))
        time.sleep(1)

    def test_search_campaigns_live(self):
        page = _http.fetch_search("تخفیف", mode="campaign")
        results = _bb.parse_search_campaigns(page)
        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(all(r["title"] for r in results))
        print(f"\nLIVE campaigns for 'تخفیف': {len(results)} on page 1, "
              f"first: {results[0]['business']} — {results[0]['title']}")
        time.sleep(1)

    def test_categories_live(self):
        page = _http.fetch_home()
        cats = _bb.parse_home_categories(page)
        self.assertGreaterEqual(len(cats), 30)
        self.assertTrue(any(c["slug"] == "zban" for c in cats))
        time.sleep(1)

    def test_unknown_business_404(self):
        with self.assertRaises(_http.BonbamaError):
            _http.fetch_business_page("definitely-not-a-real-business-xyz")
