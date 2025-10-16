"""
Shared UI generation module for operator dashboards.

This module provides common HTML generation functions that work with any
operator configuration (GPU, NNO, etc.).
"""

import json
import argparse
import semver
import os

from typing import Dict, List, Any
from datetime import datetime, timezone

from workflows.common.utils import logger
from workflows.common.templates import load_template
from workflows.common.operator_dashboard import OperatorConfig, STATUS_ABORTED


def has_valid_semantic_versions(result: Dict[str, Any], config: OperatorConfig) -> bool:
    """Check if both ocp_full_version and operator_version contain valid semantic versions."""
    try:
        ocp_version = result.get(config.ocp_version_field, "")
        op_version = result.get(config.version_field_name, "")

        if not ocp_version or not op_version:
            return False

        semver.VersionInfo.parse(ocp_version)
        op_version_clean = op_version.split("(")[0].strip()
        semver.VersionInfo.parse(op_version_clean)

    except (ValueError, TypeError):
        logger.warning(f"Invalid semantic version in result: ocp={result.get(config.ocp_version_field)}, operator={result.get(config.version_field_name)}")
        return False
    else:
        return True


def build_catalog_table_rows(regular_results: List[Dict[str, Any]], config: OperatorConfig) -> str:
    """Build the <tr> rows for the table, grouped by the full OCP version."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for result in regular_results:
        ocp_full = result[config.ocp_version_field]
        grouped.setdefault(ocp_full, []).append(result)

    rows_html = ""
    for ocp_full in sorted(
            grouped.keys(),
            key=lambda v: semver.VersionInfo.parse(v),
            reverse=True
    ):
        rows = grouped[ocp_full]

        # Group by operator version
        op_groups: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            op = row[config.version_field_name]
            op_groups.setdefault(op, []).append(row)

        # Determine final status for each operator version
        final_results: Dict[str, Dict[str, Any]] = {}
        for op, op_results in op_groups.items():
            has_success = any(r["test_status"] == "SUCCESS" for r in op_results)
            latest_result = max(op_results, key=lambda r: int(r["job_timestamp"]))

            if has_success:
                successful_results = [r for r in op_results if r["test_status"] == "SUCCESS"]
                chosen = max(successful_results, key=lambda r: int(r["job_timestamp"]))
                final_result = {**chosen, "final_status": "SUCCESS"}
            else:
                final_result = {**latest_result, "final_status": "FAILURE"}

            final_results[op] = final_result

        # Sort operator versions semantically
        sorted_results = sorted(
            final_results.values(),
            key=lambda r: semver.VersionInfo.parse(
                r[config.version_field_name].split("(")[0]),
            reverse=True
        )

        # Build clickable links
        op_links = []
        for r in sorted_results:
            if r["final_status"] == "SUCCESS":
                link = f'<a href="{r["prow_job_url"]}" target="_blank" class="success-link">{r[config.version_field_name]}</a>'
            else:
                link = f'<a href="{r["prow_job_url"]}" target="_blank" class="failed-link">{r[config.version_field_name]} (Failed)</a>'
            op_links.append(link)

        op_links_html = ", ".join(op_links)

        rows_html += f"""
        <tr>
          <td class="version-cell">{ocp_full}</td>
          <td>{op_links_html}</td>
        </tr>
        """

    return rows_html


def build_notes(notes: List[str]) -> str:
    """Build an HTML snippet with manual notes for an OCP version."""
    if not notes:
        return ""

    items = "\n".join(f'<li class="note-item">{n}</li>' for n in notes)
    return f"""
  <div class="section-label">Notes</div>
  <div class="note-items">
    <ul>
      {items}
    </ul>
  </div>
    """


def build_toc(ocp_keys: List[str]) -> str:
    """Build a TOC of OpenShift versions."""
    toc_links = ", ".join(
        f'<a href="#ocp-{ocp_version}">{ocp_version}</a>' for ocp_version in ocp_keys)
    return f"""
<div class="toc">
    <div class="ocp-version-header">OpenShift Versions</div>
    {toc_links}
</div>
    """


def build_bundle_info(bundle_results: List[Dict[str, Any]]) -> str:
    """Build a small HTML snippet that displays info about bundle statuses."""
    if not bundle_results:
        return ""
    sorted_bundles = sorted(
        bundle_results, key=lambda r: int(r["job_timestamp"]), reverse=True)
    leftmost_bundle = sorted_bundles[0]
    last_bundle_date = datetime.fromtimestamp(int(
        leftmost_bundle["job_timestamp"]), timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    bundle_html = f"""
  <div class="section-label">
    <strong>From main branch (OLM bundle)</strong>
  </div>
  <div class="history-bar-inner history-bar-outer">
    <div style="margin-top: 5px;">
      <strong>Last Bundle Job Date:</strong> {last_bundle_date}
    </div>
    """
    for bundle in sorted_bundles:
        status = bundle.get("test_status", "Unknown").upper()
        if status == "SUCCESS":
            status_class = "history-success"
        elif status == "FAILURE":
            status_class = "history-failure"
        else:
            status_class = "history-aborted"
        bundle_timestamp = datetime.fromtimestamp(
            int(bundle["job_timestamp"]), timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        bundle_html += f"""
    <div class='history-square {status_class}'
         onclick='window.open("{bundle["prow_job_url"]}", "_blank")'>
         <span class="history-square-tooltip">
          Status: {status} | Timestamp: {bundle_timestamp}
         </span>
    </div>
        """
    bundle_html += "</div>"
    return bundle_html


def generate_test_matrix(ocp_data: Dict[str, Dict[str, Any]], config: OperatorConfig, templates_dir: str) -> str:
    """Build the final HTML report."""
    header_template = load_template("header.html", templates_dir)
    html_content = header_template
    main_table_template = load_template("main_table.html", templates_dir)
    sorted_ocp_keys = sorted(ocp_data.keys(), reverse=True)
    html_content += build_toc(sorted_ocp_keys)

    for ocp_key in sorted_ocp_keys:
        notes = ocp_data[ocp_key].get("notes", [])
        bundle_results = ocp_data[ocp_key].get("bundle_tests", [])
        release_results = ocp_data[ocp_key].get("release_tests", [])

        # Apply additional filtering for release results
        regular_results = []
        for r in release_results:
            if has_valid_semantic_versions(r, config) and r.get("test_status") != STATUS_ABORTED:
                regular_results.append(r)
        notes_html = build_notes(notes)
        table_rows_html = build_catalog_table_rows(regular_results, config)
        bundle_info_html = build_bundle_info(bundle_results)
        table_block = main_table_template
        table_block = table_block.replace("{ocp_key}", ocp_key)
        table_block = table_block.replace("{table_rows}", table_rows_html)
        table_block = table_block.replace("{bundle_info}", bundle_info_html)
        table_block = table_block.replace("{notes}", notes_html)
        html_content += table_block

    footer_template = load_template("footer.html", templates_dir)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    footer_template = footer_template.replace("{LAST_UPDATED}", now_str)
    html_content += footer_template
    return html_content


def create_ui_argument_parser(config: OperatorConfig) -> argparse.ArgumentParser:
    """Create argument parser for UI generation."""
    parser = argparse.ArgumentParser(
        description=f"{config.operator_display_name} Test Matrix UI Generator"
    )
    parser.add_argument("--dashboard_html_filepath", required=True,
                        help="Path to html file for the dashboard")
    parser.add_argument("--dashboard_data_filepath", required=True,
                        help="Path to the file containing the versions for the dashboard")
    return parser


def run_ui_generation(config: OperatorConfig, templates_dir: str, args: argparse.Namespace) -> None:
    """Run the complete UI generation workflow."""
    with open(args.dashboard_data_filepath, "r") as f:
        ocp_data = json.load(f)
    logger.info(
        f"Loaded JSON data with keys: {list(ocp_data.keys())} from {args.dashboard_data_filepath}")

    html_content = generate_test_matrix(ocp_data, config, templates_dir)

    with open(args.dashboard_html_filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
        logger.info(
            f"Matrix dashboard generated: {args.dashboard_html_filepath}")

