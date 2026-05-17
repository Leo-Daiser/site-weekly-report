import gc
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.diff import FIRST_CHECK_MESSAGE, build_report_diff
from app.models import (
    LinkCheckResult,
    PageFetchResult,
    SeoCheckResult,
    SiteReport,
    StoredCheck,
)
from app.storage import get_latest_check, init_db, save_check
from app.utils import normalize_domain

SAMPLE_REPORT = SiteReport(
    source_url="https://www.example.com",
    page=PageFetchResult(
        source_url="https://www.example.com",
        final_url="https://www.example.com/",
        status_code=200,
        response_time_ms=420.0,
    ),
    seo=SeoCheckResult(
        title="Old title",
        title_length=9,
        meta_description="Old description long enough for tests here",
        meta_description_length=40,
        h1_count=1,
        canonical_url="https://example.com/",
    ),
    links=LinkCheckResult(broken_count=0),
    all_warnings=["warn1"],
)


def _stored(**overrides) -> StoredCheck:
    data = {
        "id": 1,
        "created_at": "2026-01-01T10:00:00",
        "input_url": "https://example.com",
        "final_url": "https://example.com/",
        "normalized_domain": "example.com",
        "status_code": 200,
        "response_time_ms": 420.0,
        "title": "Old title",
        "description": "Old description",
        "h1_count": 1,
        "canonical_url": "https://example.com/",
        "robots_exists": 1,
        "sitemap_exists": 0,
        "forms_count": 0,
        "broken_links_count": 0,
        "warnings_count": 1,
    }
    data.update(overrides)
    return StoredCheck(**data)


class TestNormalizeDomain(unittest.TestCase):
    def test_strips_www_only(self):
        self.assertEqual(
            normalize_domain("https://www.example.com/page?a=1"),
            "example.com",
        )

    def test_keeps_subdomain(self):
        self.assertEqual(normalize_domain("https://sub.example.com"), "sub.example.com")


class TestStorage(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tmp.name) / "test.sqlite"

    def tearDown(self) -> None:
        gc.collect()
        self.tmp.cleanup()

    def test_creates_site_checks_table(self) -> None:
        init_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='site_checks'"
            ).fetchone()
            self.assertIsNotNone(row)
        finally:
            conn.close()

    def test_saves_and_fetches_latest_by_domain(self) -> None:
        report = SiteReport(
            source_url="https://www.example.com",
            page=PageFetchResult(
                source_url="https://www.example.com",
                final_url="https://www.example.com/",
                status_code=200,
            ),
            all_warnings=[],
        )
        save_check(self.db_path, report, "example.com")
        latest = get_latest_check(self.db_path, "example.com")
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest.normalized_domain, "example.com")
        self.assertEqual(latest.status_code, 200)
        self.assertIn("source_url", latest.raw_json or "")
        gc.collect()


class TestDiff(unittest.TestCase):
    def test_no_previous_returns_first_check_message(self) -> None:
        diff = build_report_diff(None, SAMPLE_REPORT)
        self.assertFalse(diff.has_previous)
        self.assertEqual(diff.first_check_message, FIRST_CHECK_MESSAGE)
        self.assertEqual(diff.change_count, 0)

    def test_broken_links_increase_is_warning(self) -> None:
        previous = _stored(broken_links_count=0)
        current = SAMPLE_REPORT.model_copy(
            update={
                "links": LinkCheckResult(broken_count=3),
                "all_warnings": ["a", "b", "c"],
            }
        )
        diff = build_report_diff(previous, current)
        broken_changes = [c for c in diff.changes if "битых" in c.message.lower()]
        self.assertEqual(len(broken_changes), 1)
        self.assertEqual(broken_changes[0].severity, "warning")
        self.assertIn("0 → 3", broken_changes[0].message)

    def test_title_change_is_neutral(self) -> None:
        desc = "Same description for diff test long enough here"
        previous = _stored(title="Old title", description=desc)
        current = SAMPLE_REPORT.model_copy(
            update={
                "seo": SAMPLE_REPORT.seo.model_copy(
                    update={"title": "New title", "meta_description": desc}
                )
            }
        )
        diff = build_report_diff(previous, current)
        title_changes = [c for c in diff.changes if "Title" in c.message]
        self.assertEqual(len(title_changes), 1)
        self.assertEqual(title_changes[0].severity, "neutral")

    def test_status_200_to_500_is_critical(self) -> None:
        previous = _stored(status_code=200)
        current = SAMPLE_REPORT.model_copy(
            update={
                "page": SAMPLE_REPORT.page.model_copy(update={"status_code": 500}),
            }
        )
        diff = build_report_diff(previous, current)
        status_changes = [c for c in diff.changes if "HTTP-статус" in c.message]
        self.assertEqual(len(status_changes), 1)
        self.assertEqual(status_changes[0].severity, "critical")
        self.assertIn("200 → 500", status_changes[0].message)

    def _rt_changes(self, old_ms: float, new_ms: float) -> list:
        previous = _stored(response_time_ms=old_ms)
        current = SAMPLE_REPORT.model_copy(
            update={
                "page": SAMPLE_REPORT.page.model_copy(
                    update={"response_time_ms": new_ms}
                )
            }
        )
        diff = build_report_diff(previous, current)
        return [c for c in diff.changes if "Время ответа" in c.message]

    def test_response_time_small_delta_not_reported(self) -> None:
        self.assertEqual(self._rt_changes(420, 450), [])

    def test_response_time_large_increase_reported(self) -> None:
        changes = self._rt_changes(420, 620)
        self.assertEqual(len(changes), 1)
        self.assertIn("420", changes[0].message)
        self.assertIn("620", changes[0].message)

    def test_response_time_large_decrease_reported(self) -> None:
        changes = self._rt_changes(1000, 650)
        self.assertEqual(len(changes), 1)


if __name__ == "__main__":
    unittest.main()
