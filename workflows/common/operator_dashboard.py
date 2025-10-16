#!/usr/bin/env python
"""
Shared dashboard functionality for NVIDIA operator CI test results.

This module provides common functionality that can be used by both
GPU Operator and Network Operator dashboards, reducing code duplication.
"""

import argparse
import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Set

import requests
from pydantic import BaseModel
import semver

from workflows.common.utils import logger


# Constants for job statuses
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILURE = "FAILURE"
STATUS_ABORTED = "ABORTED"

# GCS API configuration
GCS_API_BASE_URL = "https://storage.googleapis.com/storage/v1/b/test-platform-results/o"
GCS_MAX_RESULTS_PER_REQUEST = 1000


class OperatorConfig:
    """Configuration for a specific operator dashboard."""
    
    def __init__(
        self,
        operator_name: str,
        operator_display_name: str,
        job_pattern: str,
        artifact_subdir: str,
        version_field_name: str
    ):
        """
        Initialize operator configuration.
        
        Args:
            operator_name: Short name (e.g., "gpu", "nno")
            operator_display_name: Display name (e.g., "GPU Operator", "Network Operator")
            job_pattern: Regex pattern component for job names (e.g., "nvidia-gpu-operator-e2e")
            artifact_subdir: Subdirectory in artifacts (e.g., "gpu-operator-e2e")
            version_field_name: JSON field name for operator version (e.g., "gpu_operator_version")
        """
        self.operator_name = operator_name
        self.operator_display_name = operator_display_name
        self.job_pattern = job_pattern
        self.artifact_subdir = artifact_subdir
        self.version_field_name = version_field_name
        self.ocp_version_field = "ocp_full_version"
        
        # Build regex pattern
        self.regex = re.compile(
            r"pr-logs/pull/(?P<repo>[^/]+)/(?P<pr_number>\d+)/"
            r"(?P<job_name>(?:rehearse-\d+-)?pull-ci-rh-ecosystem-edge-nvidia-ci-main-"
            rf"(?P<ocp_version>\d+\.\d+)-stable-{job_pattern}-(?P<op_version>\d+-\d+-x|master))/"
            r"(?P<build_id>[^/]+)"
        )


# Pre-configured operator configurations
GPU_CONFIG = OperatorConfig(
    operator_name="gpu",
    operator_display_name="GPU Operator",
    job_pattern="nvidia-gpu-operator-e2e",
    artifact_subdir="gpu-operator-e2e",
    version_field_name="gpu_operator_version"
)

NNO_CONFIG = OperatorConfig(
    operator_name="nno",
    operator_display_name="Network Operator",
    job_pattern="nvidia-network-operator-e2e",
    artifact_subdir="network-operator-e2e",
    version_field_name="nno_operator_version"
)


# =============================================================================
# Shared Data Fetching Functions
# =============================================================================

def http_get_json(url: str, params: Dict[str, Any] = None, headers: Dict[str, str] = None) -> Dict[str, Any]:
    """Send an HTTP GET request and return the JSON response."""
    response = requests.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_gcs_file_content(file_path: str) -> str:
    """Fetch the raw text content from a file in GCS."""
    logger.info(f"Fetching file content for {file_path}")
    response = requests.get(
        url=f"{GCS_API_BASE_URL}/{urllib.parse.quote_plus(file_path)}",
        params={"alt": "media"},
        timeout=30,
    )
    response.raise_for_status()
    return response.content.decode("UTF-8")


def build_prow_job_url(finished_json_path: str) -> str:
    """Build Prow job URL from finished.json path."""
    directory_path = finished_json_path[:-len('/finished.json')]
    return f"https://gcsweb-ci.apps.ci.l2s4.p1.openshiftapps.com/gcs/test-platform-results/{directory_path}"


class TestResultKey(BaseModel):
    """Pydantic model for test result composite key."""
    ocp_full_version: str
    operator_version: str
    test_status: str
    pr_number: str
    job_name: str
    build_id: str

    class Config:
        frozen = True


@dataclass(frozen=True)
class TestResult:
    """Represents a single test run result."""
    ocp_full_version: str
    operator_version: str
    test_status: str
    prow_job_url: str
    job_timestamp: str
    config: OperatorConfig

    def to_dict(self) -> Dict[str, Any]:
        return {
            self.config.ocp_version_field: self.ocp_full_version,
            self.config.version_field_name: self.operator_version,
            "test_status": self.test_status,
            "prow_job_url": self.prow_job_url,
            "job_timestamp": self.job_timestamp,
        }

    def build_key(self) -> Tuple[str, str, str]:
        """Get the PR number, job name and build ID for deduplication purposes."""
        repo, pr_number, job_name, build_id = extract_build_components(self.prow_job_url, self.config)
        return (pr_number, job_name, build_id)

    def has_exact_versions(self) -> bool:
        """Check if this result has exact semantic versions (not base versions from URL)."""
        try:
            ocp = self.ocp_full_version
            op = self.operator_version.split("(")[0].strip()
            semver.VersionInfo.parse(ocp)
            semver.VersionInfo.parse(op)
        except (ValueError, TypeError):
            return False
        else:
            return True


def extract_build_components(path: str, config: OperatorConfig) -> Tuple[str, str, str, str]:
    """Extract build components from URL or file path."""
    original_path = path
    if '/artifacts/' in path:
        path = path.split('/artifacts/')[0] + '/'

    match = config.regex.search(path)
    if not match:
        msg = f"{config.operator_display_name} path regex mismatch" if config.job_pattern in original_path else "Unexpected path format"
        raise ValueError(msg)

    return (
        match.group("repo"),
        match.group("pr_number"),
        match.group("job_name"),
        match.group("build_id")
    )


def fetch_filtered_files(pr_number: str, glob_pattern: str) -> List[Dict[str, Any]]:
    """Fetch files matching a specific glob pattern for a PR."""
    logger.info(f"Fetching files matching pattern: {glob_pattern}")

    params = {
        "prefix": f"pr-logs/pull/rh-ecosystem-edge_nvidia-ci/{pr_number}/",
        "alt": "json",
        "matchGlob": glob_pattern,
        "maxResults": str(GCS_MAX_RESULTS_PER_REQUEST),
        "projection": "noAcl",
    }
    headers = {"Accept": "application/json"}

    all_items = []
    next_page_token = None

    while True:
        if next_page_token:
            params["pageToken"] = next_page_token

        response_data = http_get_json(GCS_API_BASE_URL, params=params, headers=headers)
        items = response_data.get("items", [])
        all_items.extend(items)

        next_page_token = response_data.get("nextPageToken")
        if not next_page_token:
            break

    logger.info(f"Found {len(all_items)} files matching {glob_pattern}")
    return all_items


def fetch_pr_files(pr_number: str, config: OperatorConfig) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fetch all required file types for a PR using targeted filtering."""
    logger.info(f"Fetching files for PR #{pr_number}")

    all_finished_files = fetch_filtered_files(pr_number, "**/finished.json")
    ocp_version_files = fetch_filtered_files(
        pr_number, f"**/{config.artifact_subdir}/artifacts/ocp.version")
    op_version_files = fetch_filtered_files(
        pr_number, f"**/{config.artifact_subdir}/artifacts/operator.version")

    return all_finished_files, ocp_version_files, op_version_files


def filter_finished_files(
    all_finished_files: List[Dict[str, Any]], 
    config: OperatorConfig
) -> Tuple[List[Dict[str, Any]], Dict[Tuple[str, str, str], Dict[str, Dict[str, Any]]]]:
    """Filter operator E2E finished.json files, preferring nested when available."""
    preferred_files = {}
    all_build_files = {}

    for file_item in all_finished_files:
        path = file_item.get("name", "")

        if not (config.job_pattern in path and path.endswith('/finished.json')):
            continue

        is_nested = f'/artifacts/{config.job_pattern}-' in path and f'/{config.artifact_subdir}/finished.json' in path
        is_top_level = not is_nested and '/artifacts/' not in path

        if not (is_nested or is_top_level):
            continue

        try:
            repo, pr_number, job_name, build_id = extract_build_components(path, config)
            build_key = (pr_number, job_name, build_id)
        except ValueError:
            continue

        if build_key not in all_build_files:
            all_build_files[build_key] = {}

        if is_nested:
            all_build_files[build_key]['nested'] = file_item
        else:
            all_build_files[build_key]['top_level'] = file_item

        if build_key not in preferred_files or is_nested:
            preferred_files[build_key] = (file_item, is_nested)

    result = [file_item for file_item, _ in preferred_files.values()]
    dual_builds = {k: v for k, v in all_build_files.items()
                   if 'nested' in v and 'top_level' in v}

    return result, dual_builds


def int_or_none(value: Optional[str]) -> Optional[int]:
    """Convert string to int or None for unlimited."""
    if value is None:
        return None
    if value.lower() in ('none', 'unlimited'):
        return None
    return int(value)


def create_argument_parser(config: OperatorConfig) -> argparse.ArgumentParser:
    """Create argument parser for operator dashboard."""
    parser = argparse.ArgumentParser(
        description=f"{config.operator_display_name} Test Matrix Utility"
    )
    parser.add_argument("--pr_number", default="all",
                        help="PR number to process; use 'all' for full history")
    parser.add_argument("--baseline_data_filepath", required=True,
                        help="Path to the baseline data file")
    parser.add_argument("--merged_data_filepath", required=True,
                        help="Path to the updated (merged) data file")
    parser.add_argument("--bundle_result_limit", type=int_or_none, default=None,
                        help="Number of latest bundle results to keep per version (default: unlimited)")
    return parser


def build_files_lookup(
    finished_files: List[Dict[str, Any]],
    ocp_version_files: List[Dict[str, Any]],
    op_version_files: List[Dict[str, Any]],
    config: OperatorConfig
) -> Tuple[Dict[Tuple[str, str, str], Dict[str, Dict[str, Any]]], Set[Tuple[str, str, str]]]:
    """Build a single lookup dictionary mapping build keys to all their related files."""
    build_files = {}
    all_builds = set()

    # Combine all files into a single list with their file type
    all_files_with_type = []
    for file_item in finished_files:
        all_files_with_type.append((file_item, 'finished'))
    for file_item in ocp_version_files:
        all_files_with_type.append((file_item, 'ocp'))
    for file_item in op_version_files:
        all_files_with_type.append((file_item, 'operator'))

    # Process all files in a single pass
    for file_item, file_type in all_files_with_type:
        path = file_item.get("name", "")

        try:
            repo, pr_number, job_name, build_id = extract_build_components(path, config)
        except ValueError:
            continue

        if build_id in ['latest-build.txt', 'latest-build']:
            continue

        key = (pr_number, job_name, build_id)

        if key not in build_files:
            build_files[key] = {}

        build_files[key][file_type] = file_item
        all_builds.add(key)

    return build_files, all_builds


def process_single_build(
    pr_number_arg: str,
    job_name: str,
    build_id: str,
    ocp_version: str,
    op_suffix: str,
    build_files: Dict[Tuple[str, str, str], Dict[str, Dict[str, Any]]],
    config: OperatorConfig,
    dual_builds_info: Optional[Dict[Tuple[str, str, str], Dict[str, Dict[str, Any]]]] = None
) -> TestResult:
    """Process a single build and return its test result."""
    key = (pr_number_arg, job_name, build_id)
    build_file_set = build_files[key]

    # Get build status and timestamp from finished.json
    finished_file = build_file_set['finished']
    finished_content = fetch_gcs_file_content(finished_file['name'])
    finished_data = json.loads(finished_content)
    status = finished_data["result"]
    timestamp = finished_data["timestamp"]

    # Check for mismatch between nested operator test and top-level build result
    if dual_builds_info and key in dual_builds_info:
        dual_files = dual_builds_info[key]
        if 'nested' in dual_files and 'top_level' in dual_files:
            nested_content = fetch_gcs_file_content(dual_files['nested']['name'])
            nested_data = json.loads(nested_content)
            nested_status = nested_data["result"]

            top_level_content = fetch_gcs_file_content(dual_files['top_level']['name'])
            top_level_data = json.loads(top_level_content)
            top_level_status = top_level_data["result"]

            if nested_status == STATUS_SUCCESS and top_level_status != STATUS_SUCCESS:
                logger.warning(
                    f"Build {build_id}: {config.operator_display_name} tests SUCCEEDED "
                    f"but overall build has finished with status {top_level_status}."
                )

    # Build prow job URL directly from the finished.json file path
    job_url = build_prow_job_url(finished_file['name'])

    logger.info(f"Built prow job URL for build {build_id} from path {finished_file['name']}: {job_url}")

    # Get exact versions if files exist
    ocp_version_file = build_file_set.get('ocp')
    op_version_file = build_file_set.get('operator')

    if ocp_version_file and op_version_file:
        exact_ocp = fetch_gcs_file_content(ocp_version_file['name']).strip()
        exact_op_version = fetch_gcs_file_content(op_version_file['name']).strip()
        result = TestResult(exact_ocp, exact_op_version, status, job_url, timestamp, config)
    else:
        result = TestResult(ocp_version, op_suffix, status, job_url, timestamp, config)

    return result


def process_tests_for_pr(pr_number: str, results_by_ocp: Dict[str, Dict[str, Any]], config: OperatorConfig) -> None:
    """Retrieve and store test results for all jobs under a single PR."""
    logger.info(f"Fetching test data for PR #{pr_number}")

    # Step 1: Fetch all required files
    all_finished_files, ocp_version_files, op_version_files = fetch_pr_files(pr_number, config)

    # Step 2: Filter to get the preferred finished.json files
    finished_files, dual_builds_info = filter_finished_files(all_finished_files, config)

    # Step 3: Build single unified lookup for all file types
    build_files, all_builds = build_files_lookup(
        finished_files, ocp_version_files, op_version_files, config)

    logger.info(f"Found {len(all_builds)} builds to process")

    # Step 4: Process each job/build combination
    processed_count = 0

    for pr_num, job_name, build_id in sorted(all_builds):
        # Determine repository from job name pattern
        if job_name.startswith("rehearse-"):
            repo = "openshift_release"
        else:
            repo = "rh-ecosystem-edge_nvidia-ci"

        # Extract OCP version for logging
        job_path = f"pr-logs/pull/{repo}/{pr_num}/{job_name}/"
        full_path = f"{job_path}{build_id}"
        match = config.regex.search(full_path)
        if not match:
            logger.warning(f"Could not parse versions from components: {pr_num}, {job_name}, {build_id}")
            continue
        ocp_version = match.group("ocp_version")
        op_suffix = match.group("op_version")

        logger.info(f"Processing build {build_id} for {ocp_version} + {op_suffix}")

        result = process_single_build(
            pr_num, job_name, build_id, ocp_version, op_suffix, build_files, config, dual_builds_info)

        # Initialize the OCP version structure if it doesn't exist
        results_by_ocp.setdefault(ocp_version, {
            "bundle_tests": [],
            "release_tests": [],
            "job_history_links": set()
        })

        # Add job history link for this job name
        job_history_url = f"https://prow.ci.openshift.org/job-history/gs/test-platform-results/pr-logs/directory/{job_name}"
        results_by_ocp[ocp_version]["job_history_links"].add(job_history_url)

        # Determine if this is a bundle test or release test
        if job_name.endswith('-master'):
            results_by_ocp[ocp_version]["bundle_tests"].append(result.to_dict())
        else:
            # Only include in release tests if it has exact semantic versions and is not ABORTED
            if result.has_exact_versions() and result.test_status != STATUS_ABORTED:
                results_by_ocp[ocp_version]["release_tests"].append(result.to_dict())
            else:
                logger.debug(f"Excluded release test for build {build_id}: status={result.test_status}, exact_versions={result.has_exact_versions()}")

        processed_count += 1

    logger.info(f"Processed {processed_count} builds for PR #{pr_number}")


def process_closed_prs(results_by_ocp: Dict[str, Dict[str, List[Dict[str, Any]]]], config: OperatorConfig) -> None:
    """Retrieve and store test results for all closed PRs against the main branch."""
    logger.info("Retrieving PR history...")
    url = "https://api.github.com/repos/rh-ecosystem-edge/nvidia-ci/pulls"
    params = {"state": "closed", "base": "main", "per_page": "100", "page": "1"}
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    response_data = http_get_json(url, params=params, headers=headers)
    for pr in response_data:
        pr_number = str(pr["number"])
        logger.info(f"Processing PR #{pr_number}")
        process_tests_for_pr(pr_number, results_by_ocp, config)


def merge_bundle_tests(
    new_tests: List[Dict[str, Any]],
    existing_tests: List[Dict[str, Any]],
    limit: Optional[int],
    config: OperatorConfig
) -> List[Dict[str, Any]]:
    """Merge bundle tests with existing bundle tests and apply limit."""
    all_tests_by_build = {}

    # Add existing tests first
    for item in existing_tests:
        # Convert operator-specific version field to generic field for TestResult
        item_copy = item.copy()
        if config.version_field_name in item_copy:
            item_copy["operator_version"] = item_copy.pop(config.version_field_name)
        result = TestResult(**item_copy, config=config)
        build_key = result.build_key()
        all_tests_by_build[build_key] = item

    # Add new tests (will overwrite duplicates)
    for item in new_tests:
        # Convert operator-specific version field to generic field for TestResult
        item_copy = item.copy()
        if config.version_field_name in item_copy:
            item_copy["operator_version"] = item_copy.pop(config.version_field_name)
        result = TestResult(**item_copy, config=config)
        build_key = result.build_key()
        all_tests_by_build[build_key] = item

    # Sort by timestamp (newest first) and apply limit
    all_tests = list(all_tests_by_build.values())
    all_tests.sort(key=lambda x: int(x.get('job_timestamp', '0')), reverse=True)

    if limit is not None:
        return all_tests[:limit]

    return all_tests


def get_version_key(result: TestResult) -> Tuple[str, str]:
    """Get the version combination key (OCP, operator) for grouping."""
    return (result.ocp_full_version, result.operator_version.split("(")[0].strip())


def merge_release_tests(
    new_tests: List[Dict[str, Any]],
    existing_tests: List[Dict[str, Any]],
    config: OperatorConfig
) -> List[Dict[str, Any]]:
    """Merge release tests keeping one result per version combination."""
    results_by_version = {}

    # Process existing results
    for item in existing_tests:
        # Convert operator-specific version field to generic field for TestResult
        item_copy = item.copy()
        if config.version_field_name in item_copy:
            item_copy["operator_version"] = item_copy.pop(config.version_field_name)
        result = TestResult(**item_copy, config=config)
        version_key = get_version_key(result)
        results_by_version.setdefault(version_key, []).append(result)

    # Process new results
    for item in new_tests:
        # Convert operator-specific version field to generic field for TestResult
        item_copy = item.copy()
        if config.version_field_name in item_copy:
            item_copy["operator_version"] = item_copy.pop(config.version_field_name)
        result = TestResult(**item_copy, config=config)
        if result.has_exact_versions() and result.test_status != STATUS_ABORTED:
            version_key = get_version_key(result)
            results_by_version.setdefault(version_key, []).append(result)

    # Keep exactly one result per version key
    final_results = []
    for version_results in results_by_version.values():
        success_results = [r for r in version_results if r.test_status == STATUS_SUCCESS]
        other_results = [r for r in version_results if r.test_status != STATUS_SUCCESS]

        selected_result = None
        if success_results:
            success_results.sort(key=lambda x: int(x.job_timestamp), reverse=True)
            selected_result = success_results[0]
        elif other_results:
            other_results.sort(key=lambda x: int(x.job_timestamp), reverse=True)
            selected_result = other_results[0]

        if selected_result:
            final_results.append(selected_result.to_dict())

    final_results.sort(key=lambda x: int(x.get('job_timestamp', '0')), reverse=True)
    return final_results


def merge_ocp_version_results(
    new_version_data: Dict[str, List[Dict[str, Any]]],
    existing_version_data: Dict[str, Any],
    bundle_result_limit: Optional[int],
    config: OperatorConfig
) -> Dict[str, Any]:
    """Merge results for a single OCP version."""
    merged_version_data = {
        "notes": [],
        "bundle_tests": [],
        "release_tests": [],
        "job_history_links": []
    }
    merged_version_data.update(existing_version_data)

    # Merge bundle tests with limit
    new_bundle_tests = new_version_data.get("bundle_tests", [])
    existing_bundle_tests = merged_version_data.get("bundle_tests", [])
    merged_version_data["bundle_tests"] = merge_bundle_tests(
        new_bundle_tests, existing_bundle_tests, bundle_result_limit, config
    )

    # Merge release tests without limit
    new_release_tests = new_version_data.get("release_tests", [])
    existing_release_tests = merged_version_data.get("release_tests", [])
    merged_version_data["release_tests"] = merge_release_tests(
        new_release_tests, existing_release_tests, config
    )

    # Merge job history links
    new_job_history_links = new_version_data.get("job_history_links", set())
    existing_job_history_links = merged_version_data.get("job_history_links", [])

    all_job_history_links = set(existing_job_history_links)
    all_job_history_links.update(new_job_history_links)
    merged_version_data["job_history_links"] = sorted(list(all_job_history_links))

    return merged_version_data


def merge_and_save_results(
    new_results: Dict[str, Dict[str, List[Dict[str, Any]]]],
    output_file: str,
    existing_results: Dict[str, Dict[str, Any]],
    bundle_result_limit: Optional[int],
    config: OperatorConfig
) -> None:
    """Merge and save test results with separated bundle and release test keys."""
    merged_results = existing_results.copy() if existing_results else {}

    for ocp_version, version_data in new_results.items():
        existing_version_data = merged_results.get(ocp_version, {})
        merged_version_data = merge_ocp_version_results(
            version_data, existing_version_data, bundle_result_limit, config
        )
        merged_results[ocp_version] = merged_version_data

    with open(output_file, "w") as f:
        json.dump(merged_results, f, indent=4)

    logger.info(f"Results saved to {output_file}")


def run_dashboard_workflow(config: OperatorConfig, args: argparse.Namespace) -> None:
    """Run the complete dashboard workflow for a specific operator."""
    # Load existing data
    with open(args.baseline_data_filepath, "r") as f:
        existing_results: Dict[str, Dict[str, Any]] = json.load(f)
    logger.info(f"Loaded baseline data with {len(existing_results)} OCP versions")

    # Process PRs
    local_results: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    if args.pr_number.lower() == "all":
        process_closed_prs(local_results, config)
    else:
        process_tests_for_pr(args.pr_number, local_results, config)

    # Merge and save
    merge_and_save_results(
        local_results,
        args.merged_data_filepath,
        existing_results=existing_results,
        bundle_result_limit=args.bundle_result_limit,
        config=config
    )

