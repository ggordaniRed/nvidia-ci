import unittest
from unittest import TestCase

# Updated imports for refactored structure
from workflows.common.operator_dashboard import NNO_CONFIG
from workflows.common.operator_dashboard_ui import (
    build_catalog_table_rows, build_notes, build_toc, build_bundle_info
)
from workflows.nno_dashboard.generate_ci_dashboard import (
    OCP_FULL_VERSION, NNO_OPERATOR_VERSION
)


class TestGenerateUI(TestCase):

    def test_build_catalog_table_rows(self):
        """Test that catalog table rows are generated correctly."""
        test_data = [
            {
                OCP_FULL_VERSION: "4.14.1",
                NNO_OPERATOR_VERSION: "24.10.0",
                "test_status": "SUCCESS",
                "prow_job_url": "https://example.com/job1",
                "job_timestamp": "1712345678"
            },
            {
                OCP_FULL_VERSION: "4.14.2",
                NNO_OPERATOR_VERSION: "24.10.1",
                "test_status": "SUCCESS",
                "prow_job_url": "https://example.com/job2",
                "job_timestamp": "1712345679"
            }
        ]

        result = build_catalog_table_rows(test_data, NNO_CONFIG)

        # Should contain both OCP versions
        self.assertIn("4.14.1", result)
        self.assertIn("4.14.2", result)
        # Should contain NNO versions
        self.assertIn("24.10.0", result)
        self.assertIn("24.10.1", result)
        # Should have links
        self.assertIn("https://example.com/job1", result)
        self.assertIn("https://example.com/job2", result)

    def test_build_notes(self):
        """Test that notes are generated correctly."""
        notes = ["Note 1", "Note 2", "Note 3"]
        result = build_notes(notes)

        # Should contain all notes
        for note in notes:
            self.assertIn(note, result)
        # Should be in a list
        self.assertIn("<ul>", result)
        self.assertIn("<li", result)

    def test_build_notes_empty(self):
        """Test that empty notes return empty string."""
        result = build_notes([])
        self.assertEqual(result, "")

    def test_build_toc(self):
        """Test that table of contents is generated correctly."""
        ocp_versions = ["4.17", "4.16", "4.15"]
        result = build_toc(ocp_versions)

        # Should contain all versions
        for version in ocp_versions:
            self.assertIn(version, result)
        # Should have proper structure
        self.assertIn("class=\"toc\"", result)
        self.assertIn("href=", result)

    def test_build_bundle_info(self):
        """Test that bundle info is generated correctly."""
        bundle_data = [
            {
                "test_status": "SUCCESS",
                "prow_job_url": "https://example.com/bundle1",
                "job_timestamp": "1712345678"
            },
            {
                "test_status": "FAILURE",
                "prow_job_url": "https://example.com/bundle2",
                "job_timestamp": "1712345679"
            }
        ]

        result = build_bundle_info(bundle_data)

        # Should contain bundle info
        self.assertIn("From main branch", result)
        self.assertIn("history-success", result)
        self.assertIn("history-failure", result)
        # Should have clickable elements
        self.assertIn("onclick=", result)
        self.assertIn("https://example.com/bundle1", result)

    def test_build_bundle_info_empty(self):
        """Test that empty bundle data returns empty string."""
        result = build_bundle_info([])
        self.assertEqual(result, "")


if __name__ == '__main__':
    unittest.main()

