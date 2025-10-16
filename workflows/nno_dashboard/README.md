# NNO Dashboard Workflow

This workflow generates an HTML dashboard showing NVIDIA Network Operator (NNO) test results across different operator versions and OpenShift versions. It fetches test data from CI systems and creates visual reports for tracking test status over time.

## Overview

The dashboard workflow:
- Fetches test results from Google Cloud Storage based on pull request data
- Merges new results with existing baseline data
- Generates HTML dashboard reports
- Automatically deploys updates to GitHub Pages

## Usage

### Prerequisites

```console
pip install -r workflows/nno_dashboard/requirements.txt
```

**Important:** Before running fetch_ci_data.py, create the baseline data file and initialize it with an empty JSON object if it doesn't exist:

```console
echo '{}' > nno_data.json
```

### Fetch CI Data

```console
# Process a specific PR
python -m workflows.nno_dashboard.fetch_ci_data --pr_number "123" --baseline_data_filepath nno_data.json --merged_data_filepath nno_data.json

# Process all merged PRs - limited to 100 most recent (default)
python -m workflows.nno_dashboard.fetch_ci_data --pr_number "all" --baseline_data_filepath nno_data.json --merged_data_filepath nno_data.json

# Limit bundle test results to 50 most recent per OCP version
python -m workflows.nno_dashboard.fetch_ci_data --pr_number "all" --baseline_data_filepath nno_data.json --merged_data_filepath nno_data.json --bundle_result_limit 50
```

### Generate Dashboard

```console
python -m workflows.nno_dashboard.generate_ci_dashboard --dashboard_data_filepath nno_data.json --dashboard_html_filepath nno_dashboard.html
```

### Running Tests

First, make sure `pytest` is installed. Then, run:

```console
python -m pytest workflows/nno_dashboard/tests/ -v
```

## GitHub Actions Integration

- **Automatic**: Processes merged pull requests to update the dashboard with new test results and deploys to GitHub Pages
- **Manual**: Can be triggered manually via GitHub Actions workflow dispatch

## Job Name Patterns

The dashboard tracks CI jobs matching this pattern:
```
pull-ci-rh-ecosystem-edge-nvidia-ci-main-{ocp_version}-stable-nvidia-network-operator-e2e-{nno_version}
```

Examples:
- `pull-ci-rh-ecosystem-edge-nvidia-ci-main-4.17-stable-nvidia-network-operator-e2e-24-10-x`
- `pull-ci-rh-ecosystem-edge-nvidia-ci-main-4.16-stable-nvidia-network-operator-e2e-master`

## Test Result Categories

- **Bundle Tests**: Jobs ending with `-master`, representing tests from the main branch
- **Release Tests**: Jobs with specific version numbers (e.g., `24-10-x`), representing released operator versions

## Data Structure

The dashboard data JSON follows this structure:

```json
{
  "4.17": {
    "notes": [],
    "bundle_tests": [
      {
        "ocp_full_version": "4.17.1",
        "nno_operator_version": "25.4.0",
        "test_status": "SUCCESS",
        "prow_job_url": "https://...",
        "job_timestamp": "1234567890"
      }
    ],
    "release_tests": [...],
    "job_history_links": [...]
  }
}
```

