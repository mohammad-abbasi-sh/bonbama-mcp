"""Offline tests — parse real captured bonbama.ir pages, no network."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from bonbama_mcp import bonbama as bb

FIX = pathlib.Path(__file__).resolve().parent / "fixtures"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class TestBusinessPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.testino = bb.parse_business_page(
            _read("business-testino.html"), "https://bonbama.ir/b/testino"
        )
        cls.takchh = bb.parse_business_page(
            _read("business-takchh.html"), "https://bonbama.ir/companies/takchh"
        )

    def test_testino_name_slug(self):
        self.assertEqual(self.testino["name"], "تستینو")
        self.assertEqual(self.testino["slug"], "testino")

    def test_testino_campaign(self):
        self.assertEqual(self.testino["campaign_count"], 1)
        camp = self.testino["campaigns"][0]
        self.assertIn("تعیین سطح رایگان", camp["title"])
        self.assertEqual(camp["valid_through"], "2026-12-22")
        self.assertEqual(
            camp["url"], "https://testinno.ir/level-check-page?ref=bonbama"
        )

    def test_testino_rating(self):
        self.assertEqual(self.testino["rating"], "5")
        self.assertEqual(self.testino["review_count"], 7)

    def test_testino_category_from_breadcrumbs(self):
        self.assertEqual(self.testino["category"]["name"], "زبان")
        self.assertEqual(
            self.testino["category"]["url"],
            "https://bonbama.ir/company-categories/zban",
        )

    def test_takchh_five_campaigns(self):
        self.assertEqual(self.takchh["campaign_count"], 5)
        titles = [c["title"] for c in self.takchh["campaigns"]]
        self.assertIn("۵۰٪ تخفیف اولین خرید طاقچه — فقط از طریق بن‌باما", titles)

    def test_takchh_discount_property(self):
        by_title = {c["title"]: c for c in self.takchh["campaigns"]}
        self.assertEqual(by_title["کد تخفیف ۵۰ درصدی طاقچه"]["discount"], "50%")
        self.assertEqual(
            by_title["کد تخفیف ۳۰ درصدی کتابهای الکترونیکی یا صوتی از طاقچه"][
                "discount"
            ],
            "30%",
        )

    def test_takchh_city(self):
        self.assertEqual(self.takchh["city"], "تهران")

    def test_takchh_literal_code_extracted(self):
        # The OFF50 code is published in the page's description text —
        # the parser must surface it, live, from the page.
        codes = {c["code"]: c["note"] for c in self.takchh["codes"]}
        self.assertIn("OFF50", codes)
        self.assertIn("۵۰٪ تخفیف اولین خرید", codes["OFF50"])

    def test_testino_has_no_literal_code(self):
        # Testino publishes no literal code string — never invent one.
        self.assertEqual(self.testino["codes"], [])

    def test_no_site_org_leak(self):
        # The site-wide Organization node ("بن با ما") must never be
        # mistaken for the business itself.
        self.assertNotEqual(self.testino["name"], "بن با ما")
        self.assertNotEqual(self.takchh["name"], "بن با ما")


class TestSearchCompanies(unittest.TestCase):
    def test_testino_result(self):
        results = bb.parse_search_companies(_read("search-companies.html"))
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["name"], "تستینو")
        self.assertEqual(r["slug"], "testino")
        self.assertEqual(r["campaigns"], 1)
        self.assertEqual(r["url"], "https://bonbama.ir/b/testino")

    def test_empty_feed(self):
        self.assertEqual(bb.parse_search_companies("<html><body>no feed</body></html>"), [])


class TestSearchCampaigns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camps = bb.parse_search_campaigns(_read("search-campaigns.html"))

    def test_count(self):
        self.assertEqual(len(self.camps), 8)

    def test_percent_campaign(self):
        dorato = self.camps[0]
        self.assertEqual(dorato["business"], "شهربازی دوراتو")
        self.assertEqual(dorato["expiry_jalali"], "1405/09/30")
        self.assertEqual(dorato["title"], "تخفیف ۲۰ درصدی شهربازی دوراتو")
        self.assertEqual(dorato["discount"], "20%")
        self.assertEqual(dorato["sent_count"], 1105)
        self.assertIn("?campaign=", dorato["url"])

    def test_toman_campaign(self):
        elynor = [c for c in self.camps if c["business"] == "الینور"][0]
        self.assertEqual(elynor["discount"], "1,000,000 تومان")
        self.assertEqual(elynor["sent_count"], 129)

    def test_business_slug(self):
        self.assertEqual(self.camps[0]["business_slug"], "shahrebazi-dorato")


class TestCategoryPage(unittest.TestCase):
    def test_zban_businesses(self):
        biz = bb.parse_category_businesses(_read("category-zban.html"))
        names = [b["name"] for b in biz]
        self.assertEqual(names, ["تیچر یاسی", "تستینو", "خانه زبان ایران"])
        self.assertTrue(all(b["campaigns"] == 1 for b in biz))


class TestHomeCategories(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cats = bb.parse_home_categories(_read("home-categories.html"))

    def test_count(self):
        self.assertGreaterEqual(len(self.cats), 40)

    def test_leaf_category_with_counts(self):
        by_slug = {c["slug"]: c for c in self.cats}
        nakhn = by_slug["nakhn"]
        self.assertEqual(nakhn["name"], "ناخن")
        self.assertEqual(nakhn["businesses"], 16)
        self.assertEqual(nakhn["campaigns"], 22)
        self.assertEqual(by_slug["zban"]["businesses"], 3)

    def test_parent_category_name_cleaned(self):
        by_slug = {c["slug"]: c for c in self.cats}
        self.assertEqual(by_slug["zybayy-o-araysh"]["name"], "زیبایی و آرایش")

    def test_all_have_url_and_name(self):
        for c in self.cats:
            self.assertTrue(c["name"])
            self.assertTrue(c["url"].startswith("https://bonbama.ir/company-categories/"))


class TestArticlesIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arts = bb.parse_articles_index(_read("articles-index.html"))

    def test_count(self):
        self.assertEqual(len(self.arts), 6)

    def test_featured_h2_card(self):
        faradars = self.arts[0]
        self.assertEqual(faradars["slug"], "kod-takhfif-faradars")
        self.assertIn("کد تخفیف فرادرس", faradars["title"])
        self.assertEqual(faradars["date_jalali"], "1405/08/27")
        self.assertEqual(faradars["views"], 14)

    def test_h3_cards(self):
        slugs = [a["slug"] for a in self.arts]
        self.assertIn("black-friday-1405", slugs)
        self.assertIn("kharid-ghesti-bedoon-bahre", slugs)

    def test_percent_encoded_slug_decoded(self):
        titles = [a["title"] for a in self.arts]
        self.assertTrue(any("بهترین ناخن کار گرگان" in t for t in titles))
        nail = [a for a in self.arts if "ناخن کار" in a["title"]][0]
        self.assertIn("بهترین-ناخن-کار", nail["slug"])


class TestSitemap(unittest.TestCase):
    def test_companies(self):
        urls = bb.parse_sitemap(_read("sitemap-companies.xml"))
        self.assertEqual(len(urls), 12)
        self.assertTrue(all(u["url"].startswith("https://bonbama.ir/") for u in urls))

    def test_categories(self):
        urls = bb.parse_sitemap(_read("sitemap-categories.xml"))
        self.assertEqual(len(urls), 37)

    def test_invalid_xml(self):
        with self.assertRaises(ValueError):
            bb.parse_sitemap("<not xml")


class TestDigits(unittest.TestCase):
    def test_fa_to_en(self):
        self.assertEqual(bb.fa_to_en("۱۴۰۵/۰۹/۳۰"), "1405/09/30")
        self.assertEqual(bb.fa_to_en("۱,۱۰۵"), "1,105")


if __name__ == "__main__":
    unittest.main()
