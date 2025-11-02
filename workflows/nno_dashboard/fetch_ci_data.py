#!/usr/bin/env python
"""
NVIDIA Network Operator CI Data Fetcher

This module extends the GPU Operator CI data fetcher with Network Operator specific patterns.
It overrides only the operator-specific regex patterns and artifact paths while reusing
all the core logic from the GPU operator dashboard.
"""
import argparse
import json
import re
from typing import Any, Dict, List, Optional

# Import everything from the GPU operator fetch_ci_data
from workflows.gpu_operator_dashboard.fetch_ci_data import (
    STATUS_SUCCESS,
    STATUS_FAILURE,
    STATUS_ABORTED,
    GCS_API_BASE_URL,
    GCS_MAX_RESULTS_PER_REQUEST,
    http_get_json,
    fetch_gcs_file_content,
    build_prow_job_url,
    TestResultKey,
    TestResult,
    # Note: NOT importing fetch_filtered_files, extract_build_components, build_files_lookup, or process_single_build
    # We override them below with NNO-specific logic
    process_closed_prs,
    merge_bundle_tests,
    merge_release_tests,
    merge_ocp_version_results,
    merge_and_save_results,
    int_or_none,
)
from workflows.common.utils import logger

# =============================================================================
# Network Operator Specific Constants (Override GPU operator constants)
# =============================================================================

# Constants for version field names (override)
OCP_FULL_VERSION = "ocp_full_version"
NETWORK_OPERATOR_VERSION = "network_operator_version"

# Regular expression to match test result paths for NVIDIA Network Operator (override)
# This pattern is more flexible to handle various job name formats:
# - rehearse-NNN-pull-ci-rh-ecosystem-edge-nvidia-ci-main-doca4-nvidia-network-operator-legacy-sriov-rdma
# - rehearse-NNN-pull-ci-rh-ecosystem-edge-nvidia-ci-main-bare-metal-nvidia-network-operator-bare-metal-e2e-doca4-latest
TEST_RESULT_PATH_REGEX = re.compile(
    r"pr-logs/pull/(?P<repo>[^/]+)/(?P<pr_number>\d+)/"
    r"(?P<job_name>(?:rehearse-\d+-)?pull-ci-rh-ecosystem-edge-nvidia-ci-main-"
    r"(?P<ocp_version>[^/]+?)-nvidia-network-operator-[^/]+)/"
    r"(?P<build_id>[^/]+)"
)

# =============================================================================
# Network Operator Specific Overrides
# =============================================================================

def fetch_filtered_files(pr_number: str, glob_pattern: str) -> List[Dict[str, Any]]:
    """Fetch files matching a specific glob pattern for a PR.
    
    Override: Searches in both rh-ecosystem-edge_nvidia-ci and openshift_release repositories
    since rehearse jobs for network operator are often stored in openshift_release.
    """
    logger.info(f"Fetching files matching pattern: {glob_pattern}")

    all_items = []
    
    # Search in both possible repositories
    repositories = [
        "rh-ecosystem-edge_nvidia-ci",
        "openshift_release"
    ]
    
    for repo in repositories:
        params = {
            "prefix": f"pr-logs/pull/{repo}/{pr_number}/",
            "alt": "json",
            "matchGlob": glob_pattern,
            "maxResults": str(GCS_MAX_RESULTS_PER_REQUEST),
            "projection": "noAcl",
        }
        headers = {"Accept": "application/json"}

        next_page_token = None

        # Handle pagination
        while True:
            if next_page_token:
                params["pageToken"] = next_page_token

            try:
                response_data = http_get_json(
                    GCS_API_BASE_URL, params=params, headers=headers)
                items = response_data.get("items", [])
                all_items.extend(items)

                next_page_token = response_data.get("nextPageToken")
                if not next_page_token:
                    break
            except Exception as e:
                # If error (like 404), the PR doesn't exist in this repo, continue to next repo
                logger.debug(f"PR #{pr_number} not found in {repo} or error occurred: {e}")
                break

    logger.info(f"Found {len(all_items)} files matching {glob_pattern}")
    return all_items


def extract_build_components(path: str) -> tuple[str, str, str, str]:
    """Extract build components using Network Operator regex pattern.
    
    Override: Uses TEST_RESULT_PATH_REGEX defined above for NNO paths.
    
    Args:
        path: File path or URL
    
    Returns:
        Tuple of (repo, pr_number, job_name, build_id)
    
    Raises:
        ValueError: If path doesn't match expected pattern
    """
    # For nested files, get base path by removing everything after build_id
    original_path = path
    if '/artifacts/' in path:
        path = path.split('/artifacts/')[0] + '/'

    # Search for our pattern (works with both paths and full URLs)
    match = TEST_RESULT_PATH_REGEX.search(path)
    if not match:
        msg = "Network operator path regex mismatch" if "nvidia-network-operator" in original_path else "Unexpected path format"
        raise ValueError(msg)

    # Extract values directly from regex groups
    repo = match.group("repo")
    pr_number = match.group("pr_number")
    job_name = match.group("job_name")
    build_id = match.group("build_id")

    return (repo, pr_number, job_name, build_id)


def build_files_lookup(
    finished_files: List[Dict[str, Any]],
    ocp_version_files: List[Dict[str, Any]],
    network_version_files: List[Dict[str, Any]]
) -> tuple[Dict[tuple[str, str, str], Dict[str, Dict[str, Any]]], set[tuple[str, str, str]]]:
    """Build a single lookup dictionary mapping build keys to all their related files.
    
    Override: Uses our extract_build_components with NNO regex.
    
    Returns a dictionary where each key (pr_number, job_name, build_id) maps to a structure containing
    all related files: {finished: file, ocp: file, network: file}
    """
    build_files = {}  # {(pr_number, job_name, build_id): {finished: file, ocp: file, network: file}}
    all_builds = set()

    # Combine all files into a single list with their file type
    all_files_with_type = []
    for file_item in finished_files:
        all_files_with_type.append((file_item, 'finished'))
    for file_item in ocp_version_files:
        all_files_with_type.append((file_item, 'ocp'))
    for file_item in network_version_files:
        all_files_with_type.append((file_item, 'network'))

    # Process all files in a single pass - parse each path only once
    for file_item, file_type in all_files_with_type:
        path = file_item.get("name", "")

        # Skip non-Network operator paths early
        try:
            repo, pr_number, job_name, build_id = extract_build_components(path)
        except ValueError:
            continue

        if build_id in ['latest-build.txt', 'latest-build']:
            continue

        # Build key from extracted components
        key = (pr_number, job_name, build_id)

        # Ensure the build entry exists
        if key not in build_files:
            build_files[key] = {}

        # Store file in the appropriate slot
        build_files[key][file_type] = file_item
        all_builds.add(key)

    return build_files, all_builds


def process_single_build(
    pr_number_arg: str,
    job_name: str,
    build_id: str,
    ocp_version: str,
    network_suffix: str,
    build_files: Dict[tuple[str, str, str], Dict[str, Dict[str, Any]]],
    dual_builds_info: Optional[Dict[tuple[str, str, str], Dict[str, Dict[str, Any]]]] = None
) -> TestResult:
    """Process a single build and return its test result.
    
    Override: Uses 'network' key instead of 'gpu' for version files.
    """
    # Get all files for this build
    key = (pr_number_arg, job_name, build_id)
    build_file_set = build_files[key]

    # Get build status and timestamp from finished.json
    finished_file = build_file_set['finished']
    finished_content = fetch_gcs_file_content(finished_file['name'])
    finished_data = json.loads(finished_content)
    status = finished_data["result"]
    timestamp = finished_data["timestamp"]

    # Check for mismatch between nested Network operator test and top-level build result
    if dual_builds_info and key in dual_builds_info:
        dual_files = dual_builds_info[key]
        if 'nested' in dual_files and 'top_level' in dual_files:
            # Fetch both statuses for comparison
            nested_content = fetch_gcs_file_content(dual_files['nested']['name'])
            nested_data = json.loads(nested_content)
            nested_status = nested_data["result"]

            top_level_content = fetch_gcs_file_content(dual_files['top_level']['name'])
            top_level_data = json.loads(top_level_content)
            top_level_status = top_level_data["result"]

            # Warn if Network operator succeeded but overall build failed
            if nested_status == STATUS_SUCCESS and top_level_status != STATUS_SUCCESS:
                logger.warning(
                    f"Build {build_id}: Network operator tests SUCCEEDED but overall build has finished with status {top_level_status}."
                )

    # Build prow job URL directly from the finished.json file path
    job_url = build_prow_job_url(finished_file['name'])

    logger.info(f"Built prow job URL for build {build_id} from path {finished_file['name']}: {job_url}")

    # Get exact versions if files exist (regardless of build status)
    ocp_version_file = build_file_set.get('ocp')
    network_version_file = build_file_set.get('network')  # Note: 'network' instead of 'gpu'!

    if ocp_version_file and network_version_file:
        exact_ocp = fetch_gcs_file_content(ocp_version_file['name']).strip()
        exact_network_version = fetch_gcs_file_content(
            network_version_file['name']).strip()
        logger.info(f"Found exact versions for build {build_id}: OCP={exact_ocp}, Network={exact_network_version}")
        result = TestResult(exact_ocp, exact_network_version,
                            status, job_url, timestamp)
    else:
        # Use base versions
        logger.info(f"No exact versions found for build {build_id}, using base versions")
        result = TestResult(ocp_version, network_suffix,
                            status, job_url, timestamp)

    return result


def fetch_pr_files(pr_number: str) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fetch all required file types for a PR using targeted filtering.
    
    Override: Uses network-operator-e2e artifact paths instead of gpu-operator-e2e.
    """
    logger.info(f"Fetching files for PR #{pr_number}")

    # Fetch the 3 file types we need using glob patterns (network operator paths)
    # Note: The artifacts are nested: artifacts/nvidia-network-operator-*/network-operator-e2e/artifacts/
    all_finished_files = fetch_filtered_files(pr_number, "**/finished.json")
    ocp_version_files = fetch_filtered_files(
        pr_number, "**/ocp.version")
    network_version_files = fetch_filtered_files(
        pr_number, "**/operator.version")

    return all_finished_files, ocp_version_files, network_version_files


def filter_network_finished_files(all_finished_files: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], Dict[tuple[str, str, str], Dict[str, Dict[str, Any]]]]:
    """Filter Network operator E2E finished.json files, preferring nested when available.
    
    Override: Checks for nvidia-network-operator instead of nvidia-gpu-operator.
    """
    preferred_files = {}  # {build_key: (file_item, is_nested)}
    all_build_files = {}  # {build_key: {'nested': file_item, 'top_level': file_item}}

    logger.info(f"Filtering {len(all_finished_files)} finished files for network operator")
    
    for file_item in all_finished_files:
        path = file_item.get("name", "")

        # Check if it's a Network operator E2E finished.json file
        if not ("nvidia-network-operator" in path and path.endswith('/finished.json')):
            continue

        logger.debug(f"Found network operator file: {path[-80:]}")
        
        # Determine file type and extract build key
        # Nested: artifacts/nvidia-network-operator-*/network-operator-e2e/finished.json
        is_nested = '/artifacts/nvidia-network-operator-' in path and '/network-operator-e2e/finished.json' in path
        is_top_level = not is_nested and '/artifacts/' not in path

        logger.debug(f"  is_nested={is_nested}, is_top_level={is_top_level}")
        
        if not (is_nested or is_top_level):
            logger.debug(f"  Skipping - not nested or top-level")
            continue

        try:
            repo, pr_number, job_name, build_id = extract_build_components(path)
            build_key = (pr_number, job_name, build_id)
        except ValueError:
            continue

        # Track all files for each build
        if build_key not in all_build_files:
            all_build_files[build_key] = {}

        if is_nested:
            all_build_files[build_key]['nested'] = file_item
        else:
            all_build_files[build_key]['top_level'] = file_item

        # Store file, preferring nested over top-level
        if build_key not in preferred_files or is_nested:
            preferred_files[build_key] = (file_item, is_nested)

    # Extract file items and find builds with both nested and top-level files
    result = [file_item for file_item, _ in preferred_files.values()]
    dual_builds = {k: v for k, v in all_build_files.items()
                   if 'nested' in v and 'top_level' in v}

    return result, dual_builds


def process_tests_for_pr(pr_number: str, results_by_ocp: Dict[str, Dict[str, Any]]) -> None:
    """Retrieve and store test results for all jobs under a single PR.
    
    Override: Uses network operator specific filtering and naming.
    """
    logger.info(f"Fetching test data for PR #{pr_number}")

    # Step 1: Fetch all required files (using network operator paths)
    all_finished_files, ocp_version_files, network_version_files = fetch_pr_files(pr_number)

    # Step 2: Filter to get the preferred finished.json files
    finished_files, dual_builds_info = filter_network_finished_files(all_finished_files)
    logger.info(f"After filtering, got {len(finished_files)} finished files")

    # Step 3: Build single unified lookup for all file types
    build_files, all_builds = build_files_lookup(
        finished_files, ocp_version_files, network_version_files)

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
        match = TEST_RESULT_PATH_REGEX.search(full_path)
        if not match:
            logger.warning(f"Could not parse versions from components: {pr_num}, {job_name}, {build_id}")
            continue
        ocp_version = match.group("ocp_version")
        network_suffix = "network-operator"  # Generic suffix for network operator

        logger.info(
            f"Processing build {build_id} for {ocp_version} + {network_suffix}")

        result = process_single_build(
            pr_num, job_name, build_id, ocp_version, network_suffix, build_files, dual_builds_info)

        # Initialize the OCP version structure if it doesn't exist
        results_by_ocp.setdefault(ocp_version, {"bundle_tests": [], "release_tests": [], "job_history_links": set()})

        # Add job history link for this job name
        job_history_url = f"https://prow.ci.openshift.org/job-history/gs/test-platform-results/pr-logs/directory/{job_name}"
        results_by_ocp[ocp_version]["job_history_links"].add(job_history_url)

        # Determine if this is a bundle test (job ends with '-master') or release test
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


def main() -> None:
    """Main entry point for Network Operator CI data fetcher."""
    parser = argparse.ArgumentParser(description="Network Operator Test Matrix Utility")
    parser.add_argument("--pr_number", default="all",
                        help="PR number to process; use 'all' for full history")
    parser.add_argument("--baseline_data_filepath", required=True,
                        help="Path to the baseline data file")
    parser.add_argument("--merged_data_filepath", required=True,
                        help="Path to the updated (merged) data file")
    parser.add_argument("--bundle_result_limit", type=int_or_none, default=None,
                        help="Number of latest bundle results (jobs ending with '-master') to keep per version. Non-bundle results are kept without limit. Omit or use 'unlimited' for no limit. (default: unlimited)")
    args = parser.parse_args()

    # Update JSON data.
    with open(args.baseline_data_filepath, "r") as f:
        existing_results: Dict[str, Dict[str, Any]] = json.load(f)
    logger.info(f"Loaded baseline data with {len(existing_results)} OCP versions")

    local_results: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    if args.pr_number.lower() == "all":
        process_closed_prs(local_results)
    else:
        process_tests_for_pr(args.pr_number, local_results)
    merge_and_save_results(
        local_results, args.merged_data_filepath, existing_results=existing_results, bundle_result_limit=args.bundle_result_limit)


if __name__ == "__main__":
    main()
