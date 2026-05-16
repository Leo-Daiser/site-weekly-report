import unittest

from app.utils import report_output_filenames


class TestReportFilenames(unittest.TestCase):
    def test_html_and_pdf_share_timestamp(self) -> None:
        html_name, pdf_name = report_output_filenames(
            "https://example.com",
            timestamp="2026-05-16_12-00-00",
        )
        self.assertEqual(html_name, "example_com_2026-05-16_12-00-00.html")
        self.assertEqual(pdf_name, "example_com_2026-05-16_12-00-00.pdf")


if __name__ == "__main__":
    unittest.main()
