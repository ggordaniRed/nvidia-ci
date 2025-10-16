import json
import os
import tempfile
import unittest
from unittest import mock, TestCase

# Updated imports for refactored structure
from workflows.common.operator_dashboard import (
    merge_and_save_results, NNO_CONFIG, STATUS_SUCCESS, STATUS_FAILURE, STATUS_ABORTED
)
from workflows.nno_dashboard.fetch_ci_data import (
    OCP_FULL_VERSION, NNO_OPERATOR_VERSION
)

# Testing final logic of fetch_ci_data.py which stores the JSON test data


class TestSaveToJson(TestCase):
    def setUp(self):
        # Create a temporary directory for test files
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = self.temp_dir.name
        self.test_file = "test_data.json"

    def tearDown(self):
        # Clean up the temporary directory
        self.temp_dir.cleanup()

    def test_save_new_data_to_empty_existing(self):
        """Test saving new data when existing_data is empty."""
        new_data = {
            "4.14": {
                "release_tests": [
                    {
                        OCP_FULL_VERSION: "4.14.1",
                        NNO_OPERATOR_VERSION: "24.10.0",
                        "test_status": STATUS_SUCCESS,
                        "prow_job_url": "https://prow.ci.openshift.org/view/gs/test-platform-results/pr-logs/pull/rh-ecosystem-edge_nvidia-ci/123/pull-ci-rh-ecosystem-edge-nvidia-ci-main-4.14-stable-nvidia-network-operator-e2e-24-10-x/456",
                        "job_timestamp": "1712345678"
                    }
                ],
                "bundle_tests": []
            }
        }
        existing_data = {}

        data_file = os.path.join(self.output_dir, self.test_file)
        merge_and_save_results(new_data, data_file, existing_data, bundle_result_limit=None, config=NNO_CONFIG)

        # Read the saved file and verify its contents
        with open(data_file, 'r') as f:
            saved_data = json.load(f)

        # The saved data should have the separated structure
        self.assertIn("4.14", saved_data)
        self.assertIn("release_tests", saved_data["4.14"])
        self.assertEqual(len(saved_data["4.14"]["release_tests"]), 1)
        self.assertEqual(
            saved_data["4.14"]["release_tests"][0][OCP_FULL_VERSION], "4.14.1")
        self.assertEqual(
            saved_data["4.14"]["release_tests"][0][NNO_OPERATOR_VERSION], "24.10.0")

    def test_merge_data_with_existing(self):
        """Test merging new data with existing data."""
        existing_data = {
            "4.14": {
                "release_tests": [
                    {
                        OCP_FULL_VERSION: "4.14.1",
                        NNO_OPERATOR_VERSION: "24.10.0",
                        "test_status": STATUS_SUCCESS,
                        "prow_job_url": "https://prow.ci.openshift.org/view/gs/old",
                        "job_timestamp": "1712345678"
                    }
                ],
                "bundle_tests": []
            }
        }

        new_data = {
            "4.14": {
                "release_tests": [
                    {
                        OCP_FULL_VERSION: "4.14.2",
                        NNO_OPERATOR_VERSION: "24.10.1",
                        "test_status": STATUS_SUCCESS,
                        "prow_job_url": "https://prow.ci.openshift.org/view/gs/new",
                        "job_timestamp": "1712345679"
                    }
                ],
                "bundle_tests": []
            }
        }

        data_file = os.path.join(self.output_dir, self.test_file)
        merge_and_save_results(new_data, data_file, existing_data, bundle_result_limit=None, config=NNO_CONFIG)

        # Read and verify
        with open(data_file, 'r') as f:
            saved_data = json.load(f)

        # Should have both results
        self.assertEqual(len(saved_data["4.14"]["release_tests"]), 2)


if __name__ == '__main__':
    unittest.main()

