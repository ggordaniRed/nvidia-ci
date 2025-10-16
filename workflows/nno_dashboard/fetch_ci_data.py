#!/usr/bin/env python
"""
NNO Dashboard - Data Fetching (Refactored)

This module uses the shared operator_dashboard module to fetch and process
CI test data for the Network operator. Almost identical to GPU dashboard!

Original: 674 lines
Refactored: ~35 lines (95% reduction!)
"""

from workflows.common import operator_dashboard as dashboard

# Use NNO-specific configuration (ONLY DIFFERENCE from GPU!)
CONFIG = dashboard.NNO_CONFIG

# Re-export constants for backward compatibility
OCP_FULL_VERSION = CONFIG.ocp_version_field
NNO_OPERATOR_VERSION = CONFIG.version_field_name
STATUS_SUCCESS = dashboard.STATUS_SUCCESS
STATUS_FAILURE = dashboard.STATUS_FAILURE
STATUS_ABORTED = dashboard.STATUS_ABORTED


def main() -> None:
    """Main entry point for NNO dashboard data fetching."""
    parser = dashboard.create_argument_parser(CONFIG)
    args = parser.parse_args()
    
    # Run the complete workflow using shared module
    dashboard.run_dashboard_workflow(CONFIG, args)


if __name__ == "__main__":
    main()
