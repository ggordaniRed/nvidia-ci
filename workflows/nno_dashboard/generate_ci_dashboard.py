"""
NNO Dashboard - UI Generation (Refactored)

This module uses the shared operator_dashboard_ui module to generate
HTML dashboards for Network operator test results. Almost identical to GPU!

Original: 276 lines  
Refactored: ~25 lines (91% reduction!)
"""

import os
from workflows.common import operator_dashboard as dashboard
from workflows.common import operator_dashboard_ui as ui

# Use NNO-specific configuration (ONLY DIFFERENCE from GPU!)
CONFIG = dashboard.NNO_CONFIG

# Get templates directory path
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_TEMPLATES_DIR = os.path.join(_CURRENT_DIR, "templates")

# Re-export constants for backward compatibility
OCP_FULL_VERSION = CONFIG.ocp_version_field
NNO_OPERATOR_VERSION = CONFIG.version_field_name


def main():
    """Main entry point for NNO dashboard UI generation."""
    parser = ui.create_ui_argument_parser(CONFIG)
    args = parser.parse_args()
    
    # Run the complete UI generation workflow using shared module
    ui.run_ui_generation(CONFIG, _TEMPLATES_DIR, args)


if __name__ == "__main__":
    main()
