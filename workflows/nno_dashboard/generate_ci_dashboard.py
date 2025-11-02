#!/usr/bin/env python
"""
NVIDIA Network Operator CI Dashboard Generator

This module extends the GPU Operator CI dashboard generator with Network Operator specific imports.
It reuses all the core logic from the GPU operator dashboard and only overrides the import
for the version field names.
"""
import argparse
import json

from workflows.common.utils import logger

# Import all functions from GPU operator dashboard (reuse everything)
from workflows.gpu_operator_dashboard.generate_ci_dashboard import (
    has_valid_semantic_versions,
    generate_test_matrix,
    build_catalog_table_rows,
    build_notes,
    build_toc,
    build_bundle_info,
)

# Override: Import network operator specific constants
from workflows.nno_dashboard.fetch_ci_data import (
    OCP_FULL_VERSION,
    NETWORK_OPERATOR_VERSION as GPU_OPERATOR_VERSION,  # Alias for compatibility
    STATUS_ABORTED,
)

# Note: We're aliasing NETWORK_OPERATOR_VERSION as GPU_OPERATOR_VERSION so that
# all the imported functions from GPU operator dashboard work without modification.
# The functions just reference the field name, they don't care about the actual operator type.


def main():
    """Main entry point for Network Operator dashboard generator."""
    parser = argparse.ArgumentParser(description="Network Operator Test Matrix Dashboard Generator")
    parser.add_argument("--dashboard_html_filepath", required=True,
                        help="Path to html file for the dashboard")
    parser.add_argument("--dashboard_data_filepath", required=True,
                        help="Path to the file containing the versions for the dashboard")
    args = parser.parse_args()
    
    with open(args.dashboard_data_filepath, "r") as f:
        ocp_data = json.load(f)
    logger.info(
        f"Loaded JSON data with keys: {list(ocp_data.keys())} from {args.dashboard_data_filepath}")

    html_content = generate_test_matrix(ocp_data)

    with open(args.dashboard_html_filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
        logger.info(
            f"Network Operator dashboard generated: {args.dashboard_html_filepath}")


if __name__ == "__main__":
    main()

