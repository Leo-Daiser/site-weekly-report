import unittest

from app.link_checker import collect_links
from app.models import PageFetchResult, ResourceCheckResult, SiteReport
from app.report_builder import build_recommendations
from app.seo_checks import run_seo_checks
from app.utils import normalize_url

SAMPLE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <title>Тестовая страница для SEO-проверки</title>
  <meta name="description" content="Описание страницы достаточной длины для прохождения базовой SEO-проверки в тестах.">
  <link rel="canonical" href="https://example.com/">
</head>
<body>
  <h1>Главный заголовок</h1>
  <a href="/about">О нас</a>
  <a href="https://example.com/contact">Контакты</a>
  <a href="https://external.org/page">Внешняя</a>
</body>
</html>
"""

NO_TITLE_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta name="description" content="Описание страницы достаточной длины для прохождения базовой SEO-проверки в тестах.">
</head>
<body><h1>Заголовок</h1></body>
</html>
"""


class TestNormalizeUrl(unittest.TestCase):
    def test_adds_https_when_scheme_missing(self):
        self.assertEqual(normalize_url("example.com"), "https://example.com")

    def test_keeps_existing_scheme(self):
        self.assertEqual(normalize_url("http://example.com"), "http://example.com")


class TestSeoChecks(unittest.TestCase):
    def test_finds_title_description_h1_canonical(self):
        result = run_seo_checks(SAMPLE_HTML)
        self.assertEqual(result.title, "Тестовая страница для SEO-проверки")
        self.assertIn("Описание страницы", result.meta_description or "")
        self.assertEqual(result.h1_list, ["Главный заголовок"])
        self.assertEqual(result.canonical_url, "https://example.com/")

    def test_warning_when_title_missing(self):
        result = run_seo_checks(NO_TITLE_HTML)
        self.assertIn("title отсутствует", result.warnings)


class TestCollectLinks(unittest.TestCase):
    def test_splits_internal_and_external_links(self):
        page_url = "https://example.com/"
        internal, external = collect_links(SAMPLE_HTML, page_url)

        self.assertIn("https://example.com/about", internal)
        self.assertIn("https://example.com/contact", internal)
        self.assertIn("https://external.org/page", external)
        self.assertTrue(all("example.com" in url for url in internal))
        self.assertTrue(all("external.org" in url for url in external))


class TestRecommendations(unittest.TestCase):
    def test_single_robots_recommendation_when_missing(self):
        report = SiteReport(
            source_url="https://example.com",
            page=PageFetchResult(source_url="https://example.com"),
            robots=ResourceCheckResult(
                resource_type="robots.txt",
                url="https://example.com/robots.txt",
                exists=False,
            ),
            all_warnings=["robots.txt не найден или недоступен"],
        )
        recs = build_recommendations(report)
        robots_recs = [r for r in recs if "robots" in r.lower()]
        self.assertEqual(len(robots_recs), 1)
        self.assertEqual(robots_recs[0], "Добавить robots.txt.")


if __name__ == "__main__":
    unittest.main()
