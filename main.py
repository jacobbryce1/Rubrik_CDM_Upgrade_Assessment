#!/usr/bin/env python3
"""
Rubrik CDM Pre-Upgrade Compatibility Assessment
Parallel orchestrator using original tool's proven
per-cluster logic with scaling additions:
- Parallel cluster processing via ThreadPoolExecutor
- Streaming output for large environments
- Token refresh for multi-hour runs
- Progress tracking and API statistics

Enhanced HTML reporting matching original tool's
multi-cluster dashboard with per-cluster drill-downs.
"""

import os
import sys
import time
import json
import csv
import shutil
import logging
import threading
import traceback
import html as html_mod
import concurrent.futures
from datetime import datetime

from config import Config, setup_logging
from rsc_client import RSCClient
from cluster_discovery import (
    DiscoveredCluster,
    discover_all_clusters,
    enrich_cluster,
    filter_clusters,
)
from models import (
    ClusterAssessment,
    MultiClusterAssessment,
    StreamingMultiAssessment,
    create_multi_assessment,
)

logger = logging.getLogger("main")


# ==============================================================
#  Progress Tracker
# ==============================================================
class ProgressTracker:
    """Thread-safe progress tracker with ETA."""

    def __init__(self, total, label="items"):
        self.total = total
        self.label = label
        self.completed = 0
        self.failed = 0
        self.lock = threading.Lock()
        self.start_time = time.time()
        self._results = []

    @property
    def summary(self):
        with self.lock:
            return {
                "total": self.total,
                "completed": self.completed,
                "failed": self.failed,
                "elapsed": time.time() - self.start_time,
            }

    def complete(self, name=""):
        with self.lock:
            self.completed += 1
            self._log_progress(name, "completed")

    def fail(self, name=""):
        with self.lock:
            self.failed += 1
            self.completed += 1
            self._log_progress(name, "FAILED")

    def _log_progress(self, name, status):
        elapsed = time.time() - self.start_time
        done = self.completed
        remaining = self.total - done
        if done > 0 and remaining > 0:
            eta_sec = (elapsed / done) * remaining
            eta_str = " | ETA: {:.0f}s".format(eta_sec)
        else:
            eta_str = ""
        logger.info(
            "  Progress: %d/%d %s (%s: %s)%s",
            done, self.total, self.label,
            status, name, eta_str,
        )


# ==============================================================
#  Single Cluster Assessment
#  Uses the original tool's collector pattern with
#  individual error handling per collector.
# ==============================================================
def assess_single_cluster(client, cluster,
                          target_version):
    """
    Assess one cluster for upgrade readiness.
    Each collector is wrapped in try/except so one
    failing collector does not abort the cluster.
    """
    start = time.time()

    ca = ClusterAssessment(
        cluster_name=cluster.name,
        cluster_id=cluster.cluster_id,
        version=cluster.version,
        target_version=target_version,
        cluster_type=cluster.cluster_type,
        node_count=cluster.node_count,
        location=cluster.location,
        connected_state=cluster.connected_state,
        assessment_start=datetime.utcnow().isoformat(),
    )

    # Set the target cluster context
    client.set_target_cluster(
        cluster.cluster_id,
        node_ips=cluster.node_ips,
        name=cluster.name,
        version=cluster.version,
    )

    # Check CDM direct API availability
    ca.cdm_api_available = client.is_cdm_available(
        cluster.cluster_id
    )

    # ── RSC-based collectors (always run) ──

    try:
        from collectors.upgrade_prechecks import (
            collect_upgrade_prechecks,
        )
        result = collect_upgrade_prechecks(
            client, cluster, target_version
        )
        ca.add_collection_result(result)
        ca.checks_performed.append(
            "upgrade_prechecks"
        )
    except Exception as e:
        logger.error(
            "  [%s] upgrade_prechecks failed: %s",
            cluster.name, e,
        )

    try:
        from collectors.workload_inventory import (
            collect_workload_inventory,
        )
        result = collect_workload_inventory(
            client, cluster
        )
        ca.add_collection_result(result)
        ca.checks_performed.append(
            "workload_inventory"
        )
    except Exception as e:
        logger.error(
            "  [%s] workload_inventory failed: %s",
            cluster.name, e,
        )

    try:
        from collectors.sla_compliance import (
            collect_sla_compliance,
        )
        result = collect_sla_compliance(
            client, cluster
        )
        ca.add_collection_result(result)
        ca.checks_performed.append("sla_compliance")
    except Exception as e:
        logger.error(
            "  [%s] sla_compliance failed: %s",
            cluster.name, e,
        )

    try:
        from collectors.host_inventory import (
            collect_host_inventory,
        )
        result = collect_host_inventory(
            client, cluster
        )
        ca.add_collection_result(result)
        ca.checks_performed.append("host_inventory")
    except Exception as e:
        logger.error(
            "  [%s] host_inventory failed: %s",
            cluster.name, e,
        )

    try:
        from collectors.compatibility_validator import (
            collect_compatibility_validation,
        )
        result = collect_compatibility_validation(
            client, cluster, target_version
        )
        ca.add_collection_result(result)
        ca.checks_performed.append(
            "compatibility_validator"
        )
    except Exception as e:
        logger.error(
            "  [%s] compatibility_validator "
            "failed: %s",
            cluster.name, e,
        )

    # ── CDM direct collectors ──
    # (only if authenticated)

    if ca.cdm_api_available:
        try:
            from collectors.cdm_system_status import (
                collect_system_status,
            )
            result = collect_system_status(
                client, cluster
            )
            ca.add_collection_result(result)
            ca.checks_performed.append(
                "cdm_system_status"
            )
        except Exception as e:
            logger.error(
                "  [%s] cdm_system_status "
                "failed: %s",
                cluster.name, e,
            )

        try:
            from collectors.cdm_live_mounts import (
                collect_live_mounts,
            )
            result = collect_live_mounts(
                client, cluster
            )
            ca.add_collection_result(result)
            ca.checks_performed.append(
                "cdm_live_mounts"
            )
        except Exception as e:
            logger.error(
                "  [%s] cdm_live_mounts failed: %s",
                cluster.name, e,
            )

        try:
            from collectors.cdm_archive_replication import (
                collect_archive_replication,
            )
            result = collect_archive_replication(
                client, cluster
            )
            ca.add_collection_result(result)
            ca.checks_performed.append(
                "cdm_archive_replication"
            )
        except Exception as e:
            logger.error(
                "  [%s] cdm_archive_replication "
                "failed: %s",
                cluster.name, e,
            )

        try:
            from collectors.cdm_network_config import (
                collect_network_config,
            )
            result = collect_network_config(
                client, cluster
            )
            ca.add_collection_result(result)
            ca.checks_performed.append(
                "cdm_network_config"
            )
        except Exception as e:
            logger.error(
                "  [%s] cdm_network_config "
                "failed: %s",
                cluster.name, e,
            )

        try:
            from collectors.cdm_workloads import (
                collect_cdm_workloads,
            )
            result = collect_cdm_workloads(
                client, cluster
            )
            ca.add_collection_result(result)
            ca.checks_performed.append(
                "cdm_workloads"
            )
        except Exception as e:
            logger.error(
                "  [%s] cdm_workloads failed: %s",
                cluster.name, e,
            )
    else:
        ca.add_issue(
            severity="INFO",
            category="CONNECTIVITY",
            check="cdm_direct_api",
            message=(
                "CDM direct API not available for "
                + cluster.name
                + ". CDM-direct checks skipped."
            ),
            detail=(
                "Node IPs: "
                + str(cluster.node_ips)
                + ", CDM direct enabled: "
                + str(Config.CDM_DIRECT_ENABLED)
                + ". Ensure network connectivity "
                "to cluster node IPs for full "
                "assessment."
            ),
        )

    # Finalize timing
    ca.assessment_duration_sec = (
        time.time() - start
    )
    ca.assessment_end = (
        datetime.utcnow().isoformat()
    )
    ca.status = "COMPLETED"

    return ca
# ==============================================================
#  Print Final Summary
# ==============================================================
def print_final_summary(ma, files, output_dir,
                        progress=None,
                        api_stats=None):
    """Print final assessment summary to console/log."""
    data = ma.to_dict()

    logger.info("")
    logger.info("=" * 70)
    logger.info("  ASSESSMENT COMPLETE")
    logger.info("=" * 70)
    logger.info(
        "  Target CDM Version: %s",
        data.get("target_version", "?"),
    )
    logger.info(
        "  Clusters Assessed:  %d",
        data.get("total_assessed", 0),
    )
    logger.info(
        "  Clusters Skipped:   %d",
        data.get("total_skipped", 0),
    )
    logger.info(
        "  Clusters Failed:    %d",
        data.get("total_failed", 0),
    )
    logger.info(
        "  Total Blockers:     %d",
        data.get("total_blockers", 0),
    )
    logger.info(
        "  Total Warnings:     %d",
        data.get("total_warnings", 0),
    )
    logger.info(
        "  Total Info:         %d",
        data.get("total_info", 0),
    )
    logger.info("")
    logger.info("  Output directory: %s", output_dir)
    for f in files:
        logger.info(
            "    - %s", os.path.basename(f)
        )
    logger.info("=" * 70)


# ==============================================================
#  Report Generation
# ==============================================================
def generate_reports(ma, output_dir):
    """Generate all configured report formats."""
    generated_files = []

    # ── JSON ──
    if "json" in Config.REPORT_FORMATS:
        json_file = os.path.join(
            output_dir, "assessment_report.json"
        )
        try:
            with open(json_file, "w",
                       encoding="utf-8") as f:
                json.dump(
                    ma.to_dict(), f,
                    indent=2, default=str,
                )
            generated_files.append(json_file)
            logger.info(
                "  [JSON] report: %s", json_file
            )
        except Exception as e:
            logger.error("  [JSON] failed: %s", e)

    # ── CSV: Issues ──
    if "csv" in Config.REPORT_FORMATS:
        issues_csv = os.path.join(
            output_dir, "all_issues.csv"
        )
        try:
            with open(issues_csv, "w", newline="",
                       encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "cluster_name", "severity",
                    "section", "message",
                    "recommendation",
                ])
                data = ma.to_dict()
                for a in data.get("assessments", []):
                    cname = a.get(
                        "cluster_name", ""
                    )
                    for finding in a.get(
                        "findings", []
                    ):
                        writer.writerow([
                            cname,
                            finding.get(
                                "severity", "INFO"
                            ),
                            finding.get(
                                "section", ""
                            ),
                            finding.get(
                                "message", ""
                            ),
                            finding.get(
                                "recommendation", ""
                            ),
                        ])
            generated_files.append(issues_csv)
            logger.info(
                "  [CSV] issues: %s", issues_csv
            )
        except Exception as e:
            logger.error(
                "  [CSV] issues failed: %s", e
            )

        # ── CSV: Summary ──
        summary_csv = os.path.join(
            output_dir, "cluster_summary.csv"
        )
        try:
            with open(summary_csv, "w", newline="",
                       encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "cluster_name", "cluster_id",
                    "version", "target_version",
                    "node_count", "location",
                    "blockers", "warnings", "info",
                    "cdm_api_available",
                    "duration_sec",
                ])
                data = ma.to_dict()
                for a in data.get(
                    "assessments", []
                ):
                    writer.writerow([
                        a.get("cluster_name", ""),
                        a.get("cluster_id", ""),
                        a.get("version", ""),
                        a.get("target_version", ""),
                        a.get("node_count", 0),
                        a.get("location", ""),
                        a.get("blockers", 0),
                        a.get("warnings", 0),
                        a.get("info", 0),
                        a.get(
                            "cdm_api_available",
                            False
                        ),
                        a.get("duration_sec", 0),
                    ])
            generated_files.append(summary_csv)
            logger.info(
                "  [CSV] summary: %s", summary_csv
            )
        except Exception as e:
            logger.error(
                "  [CSV] summary failed: %s", e
            )

    # ── HTML ──
    if "html" in Config.REPORT_FORMATS:
        try:
            html_file = generate_html_report(
                ma, output_dir
            )
            generated_files.append(html_file)
            logger.info(
                "  [HTML] report: %s", html_file
            )
        except Exception as e:
            logger.error("  [HTML] failed: %s", e)
            logger.debug(traceback.format_exc())

    return generated_files


# ==============================================================
#  HTML Report — Full Dashboard
#  Matches original tool's multi-cluster format with
#  per-cluster drill-downs, cross-cluster issues,
#  and collapsible findings sections.
# ==============================================================
def generate_html_report(ma, output_dir):
    """
    Generate comprehensive HTML dashboard.
    Reads issues from both in-memory and streaming
    modes, surfacing all blockers and warnings
    prominently.
    """

    def _esc(val):
        return html_mod.escape(
            str(val)
        ) if val else "—"

    def _severity_class(sev):
        s = str(sev).upper()
        if s in ("BLOCKER", "CRITICAL", "ERROR"):
            return "blocker"
        if s in ("WARNING", "WARN"):
            return "warning"
        return "info"

    def _severity_badge(sev):
        s = str(sev).upper()
        if s in ("BLOCKER", "CRITICAL", "ERROR"):
            return (
                '<span class="badge badge-blocker">'
                'BLOCKER</span>'
            )
        if s in ("WARNING", "WARN"):
            return (
                '<span class="badge badge-warning">'
                'WARNING</span>'
            )
        return (
            '<span class="badge badge-info">'
            'INFO</span>'
        )

    html_file = os.path.join(
        output_dir, "assessment_report.html"
    )
    timestamp = datetime.utcnow().strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    data = ma.to_dict()
    total_assessed = data.get("total_assessed", 0)
    total_failed = data.get("total_failed", 0)
    total_skipped = data.get("total_skipped", 0)
    total_blockers = data.get("total_blockers", 0)
    total_warnings = data.get("total_warnings", 0)
    total_info = data.get("total_info", 0)
    target_ver = data.get("target_version", "?")
    total_discovered = (
        total_assessed + total_skipped + total_failed
    )

    blocker_bg = (
        "#dc3545" if total_blockers > 0
        else "#28a745"
    )
    warning_bg = (
        "#ffc107" if total_warnings > 0
        else "#28a745"
    )
    warning_fg = (
        "#333" if total_warnings > 0
        else "white"
    )

    # ── Resolve issues for each assessment ──
    # In-memory mode: issues are in a.to_dict()["issues"]
    # Streaming mode: issues are only in per-cluster
    #   JSON files — load them if needed
    assessments = data.get("assessments", [])

    # For streaming mode, enrich summaries with
    # issues from per-cluster JSON files
    cluster_dir = os.path.join(
        output_dir, "clusters"
    )
    for a in assessments:
        if "issues" not in a or not a.get("issues"):
            # Try loading from per-cluster JSON
            safe_name = "".join(
                c if c.isalnum() or c in "-_"
                else "_"
                for c in a.get("cluster_name", "")
            )
            detail_path = os.path.join(
                cluster_dir, safe_name + ".json"
            )
            if os.path.exists(detail_path):
                try:
                    with open(
                        detail_path, "r",
                        encoding="utf-8"
                    ) as f:
                        detail = json.load(f)
                    a["issues"] = detail.get(
                        "issues", []
                    )
                except Exception:
                    a["issues"] = []
            else:
                a["issues"] = []

    # Also try reading from in-memory assessments
    # if available (MultiClusterAssessment mode)
    if hasattr(ma, 'assessments'):
        for idx, raw_a in enumerate(ma.assessments):
            if hasattr(raw_a, 'issues') and raw_a.issues:
                if idx < len(assessments):
                    if not assessments[idx].get("issues"):
                        assessments[idx]["issues"] = [
                            i.to_dict()
                            for i in raw_a.issues
                        ]

    # ── Build cluster cards + cross-cluster issues ──
    cluster_cards = ""
    all_issues_rows = ""

    for a in assessments:
        cname = a.get("cluster_name", "Unknown")
        cver = a.get("version", "?")
        ctarget = a.get("target_version", target_ver)
        nodes = a.get("node_count", "?")
        location = a.get("location", "—")
        b = a.get("blockers",
                   a.get("total_blockers", 0))
        w = a.get("warnings",
                   a.get("total_warnings", 0))
        i = a.get("info",
                   a.get("total_info", 0))
        d = round(a.get("duration_sec",
                        a.get(
                            "assessment_duration_sec",
                            0
                        )), 1)
        checks = a.get("checks_performed", [])
        issues = a.get("issues", [])
        platform = a.get("cluster_type", "—")
        cdm_api = a.get("cdm_api_available", False)

        if b > 0:
            card_border = "#dc3545"
            card_status = "BLOCKERS FOUND"
            card_status_class = "status-blocker"
        elif w > 0:
            card_border = "#ffc107"
            card_status = "WARNINGS"
            card_status_class = "status-warning"
        else:
            card_border = "#28a745"
            card_status = "READY"
            card_status_class = "status-ok"

        # Should this cluster's findings be
        # auto-expanded? Yes if blockers or warnings
        open_attr = (
            " open" if (b > 0 or w > 0) else ""
        )

        cluster_cards += (
            '<div class="cluster-card" '
            'style="border-left:5px solid '
            + card_border + ';">\n'
            '  <div class="cluster-card-header">\n'
            '    <div>\n'
            '      <h3 class="cluster-name">'
            + _esc(cname) + '</h3>\n'
            '      <span class="cluster-meta">'
            + _esc(cver) + ' &#8594; '
            + _esc(ctarget)
            + ' &nbsp;|&nbsp; '
            + str(nodes) + ' nodes'
            + ' &nbsp;|&nbsp; '
            + _esc(location)
            + ' &nbsp;|&nbsp; '
            + _esc(platform)
            + '</span>\n'
            '    </div>\n'
            '    <span class="cluster-status '
            + card_status_class + '">'
            + card_status + '</span>\n'
            '  </div>\n'
            '  <div class="cluster-card-metrics">\n'
            '    <div class="metric">'
            '<span class="metric-val blocker-text">'
            + str(b) + '</span>'
            '<span class="metric-label">'
            'Blockers</span></div>\n'
            '    <div class="metric">'
            '<span class="metric-val warning-text">'
            + str(w) + '</span>'
            '<span class="metric-label">'
            'Warnings</span></div>\n'
            '    <div class="metric">'
            '<span class="metric-val info-text">'
            + str(i) + '</span>'
            '<span class="metric-label">'
            'Info</span></div>\n'
            '    <div class="metric">'
            '<span class="metric-val">'
            + str(d) + 's</span>'
            '<span class="metric-label">'
            'Duration</span></div>\n'
            '    <div class="metric">'
            '<span class="metric-val">'
            + str(len(checks)) + '</span>'
            '<span class="metric-label">'
            'Checks</span></div>\n'
            '    <div class="metric">'
            '<span class="metric-val">'
            + ('&#9989;' if cdm_api else '&#10060;')
            + '</span>'
            '<span class="metric-label">'
            'CDM API</span></div>\n'
            '  </div>\n'
        )

        # Per-cluster findings
        # Filter to blockers+warnings first,
        # then info
        blocker_warn_issues = [
            f for f in issues
            if str(f.get("severity", "")).upper()
            in ("BLOCKER", "CRITICAL", "ERROR",
                "WARNING", "WARN")
        ]
        info_issues = [
            f for f in issues
            if str(f.get("severity", "")).upper()
            not in ("BLOCKER", "CRITICAL", "ERROR",
                    "WARNING", "WARN")
        ]

        if issues:
            # Show blockers/warnings expanded,
            # info collapsed
            if blocker_warn_issues:
                cluster_cards += (
                    '  <details class='
                    '"findings-detail"'
                    + open_attr + '>\n'
                    '    <summary '
                    'class="issues-summary">'
                    '&#9888; '
                    + str(len(blocker_warn_issues))
                    + ' Blocker/Warning finding(s)'
                    '</summary>\n'
                    '    <table '
                    'class="findings-table">\n'
                    '      <tr>'
                    '<th>Severity</th>'
                    '<th>Category</th>'
                    '<th>Check</th>'
                    '<th>Message</th>'
                    '<th>Detail</th>'
                    '</tr>\n'
                )
                for f in blocker_warn_issues:
                    sev = f.get("severity", "INFO")
                    cat = f.get("category", "—")
                    chk = f.get("check", "—")
                    msg = f.get("message", "—")
                    det = f.get("detail", "—")
                    row_class = _severity_class(sev)

                    cluster_cards += (
                        '      <tr class="'
                        + row_class + '">'
                        '<td>'
                        + _severity_badge(sev)
                        + '</td>'
                        '<td>' + _esc(cat) + '</td>'
                        '<td>' + _esc(chk) + '</td>'
                        '<td>' + _esc(msg) + '</td>'
                        '<td>' + _esc(det) + '</td>'
                        '</tr>\n'
                    )

                    # Add to cross-cluster table
                    all_issues_rows += (
                        '<tr class="'
                        + row_class + '">'
                        '<td>'
                        + _severity_badge(sev)
                        + '</td>'
                        '<td>' + _esc(cname)
                        + '</td>'
                        '<td>' + _esc(cat)
                        + '</td>'
                        '<td>' + _esc(msg)
                        + '</td>'
                        '<td>' + _esc(det)
                        + '</td>'
                        '</tr>\n'
                    )

                cluster_cards += (
                    '    </table>\n'
                    '  </details>\n'
                )

            if info_issues:
                cluster_cards += (
                    '  <details '
                    'class="findings-detail">\n'
                    '    <summary>'
                    + str(len(info_issues))
                    + ' informational finding(s)'
                    '</summary>\n'
                    '    <table '
                    'class="findings-table">\n'
                    '      <tr>'
                    '<th>Severity</th>'
                    '<th>Category</th>'
                    '<th>Check</th>'
                    '<th>Message</th>'
                    '<th>Detail</th>'
                    '</tr>\n'
                )
                for f in info_issues:
                    sev = f.get("severity", "INFO")
                    cat = f.get("category", "—")
                    chk = f.get("check", "—")
                    msg = f.get("message", "—")
                    det = f.get("detail", "—")

                    cluster_cards += (
                        '      <tr class="info">'
                        '<td>'
                        + _severity_badge(sev)
                        + '</td>'
                        '<td>' + _esc(cat) + '</td>'
                        '<td>' + _esc(chk) + '</td>'
                        '<td>' + _esc(msg) + '</td>'
                        '<td>' + _esc(det) + '</td>'
                        '</tr>\n'
                    )

                cluster_cards += (
                    '    </table>\n'
                    '  </details>\n'
                )
        else:
            cluster_cards += (
                '  <p class="no-findings">'
                '&#9989; No findings — cluster '
                'appears upgrade-ready.</p>\n'
            )

        cluster_cards += '</div>\n'
       # ── Aggregate checks performed ──
    checks_set = set()
    for a in assessments:
        for c in a.get("checks_performed", []):
            checks_set.add(c)
    checks_badges = ""
    for ch in sorted(checks_set):
        checks_badges += (
            '<span class="check-badge">'
            + _esc(ch) + '</span> '
        )

    # ── Failed clusters ──
    failed_rows = ""
    for f in data.get("failures", []):
        failed_rows += (
            '<tr class="blocker">'
            '<td>' + _esc(f.get(
                "cluster_name", "?"
            )) + '</td>'
            '<td>' + _esc(f.get(
                "version", "?"
            )) + '</td>'
            '<td>' + _esc(f.get(
                "error", "Unknown"
            )) + '</td>'
            '</tr>\n'
        )

    # ── Skipped clusters ──
    skipped_rows = ""
    for s in data.get("skipped", []):
        skipped_rows += (
            '<tr><td>' + _esc(s.get(
                "cluster_name", "?"
            )) + '</td>'
            '<td>' + _esc(s.get(
                "reason", "?"
            )) + '</td></tr>\n'
        )

    # ── Skipped/Failed section ──
    skipped_section = ""
    if skipped_rows or failed_rows:
        skipped_section = (
            '<h2>&#9197; Skipped &amp; '
            'Failed Clusters</h2>\n'
        )
        if failed_rows:
            skipped_section += (
                '<h3>Failed</h3>\n'
                '<table class="data-table">\n'
                '<tr><th>Cluster</th>'
                '<th>Version</th>'
                '<th>Error</th></tr>\n'
                + failed_rows
                + '</table>\n'
            )
        if skipped_rows:
            skipped_section += (
                '<h3>Skipped</h3>\n'
                '<table class="data-table">\n'
                '<tr><th>Cluster</th>'
                '<th>Reason</th></tr>\n'
                + skipped_rows
                + '</table>\n'
            )

    # ── Cross-cluster issues ──
    if all_issues_rows:
        issues_section = (
            '<h2>&#9888; All Blockers &amp; '
            'Warnings Across All Clusters ('
            + str(total_blockers + total_warnings)
            + ')</h2>\n'
            '<p style="color:#666;font-size:13px;">'
            'Sorted by severity. These must be '
            'reviewed before proceeding with '
            'upgrade.</p>\n'
            '<table class="data-table">\n'
            '<tr><th>Severity</th>'
            '<th>Cluster</th>'
            '<th>Category</th>'
            '<th>Message</th>'
            '<th>Detail</th></tr>\n'
            + all_issues_rows
            + '</table>\n'
        )
    else:
        issues_section = (
            '<h2>&#9888; Cross-Cluster Issues</h2>'
            '\n'
            '<p class="no-findings">&#9989; '
            'No blockers or warnings found across '
            'any cluster.</p>\n'
        )

    # ════════════════════════════════════════
    #  ASSEMBLE FULL HTML
    # ════════════════════════════════════════
    html = (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" '
        'content="width=device-width, '
        'initial-scale=1.0">\n'
        '<title>Rubrik CDM Pre-Upgrade '
        'Assessment</title>\n'
        '<style>\n'
        '* { box-sizing: border-box; }\n'
        'body { font-family: -apple-system, '
        'BlinkMacSystemFont, "Segoe UI", '
        'Roboto, sans-serif;\n'
        '  margin:0; padding:0; '
        'background:#f0f2f5; color:#333; }\n'
        '.header { background: linear-gradient('
        '135deg, #1a1a2e 0%, #16213e 100%);\n'
        '  color:white; padding:30px 40px; }\n'
        '.header h1 { margin:0 0 5px 0; '
        'font-size:24px; }\n'
        '.header .subtitle { color:#aab; '
        'font-size:14px; margin-bottom:15px; }\n'
        '.header-meta { display:flex; gap:30px; '
        'font-size:13px; color:#ccd; }\n'
        '.header-badges { margin-top:15px; '
        'display:flex; gap:12px; }\n'
        '.header-badge { padding:6px 18px; '
        'border-radius:20px; font-weight:700; '
        'font-size:14px; }\n'
        '.container { max-width:1400px; '
        'margin:0 auto; padding:25px 40px; }\n'
        '.summary { display:flex; gap:15px; '
        'margin:25px 0; flex-wrap:wrap; }\n'
        '.card { background:white; '
        'border-radius:10px; padding:20px;\n'
        '  box-shadow:0 2px 8px '
        'rgba(0,0,0,0.08);\n'
        '  min-width:140px; text-align:center; '
        'flex:1; }\n'
        '.card h3 { margin:0 0 8px 0; '
        'color:#666; font-size:12px;\n'
        '  text-transform:uppercase; '
        'letter-spacing:1px; }\n'
        '.card .value { font-size:36px; '
        'font-weight:700; }\n'
        '.card .value.red { color:#dc3545; }\n'
        '.card .value.orange { color:#ffc107; }\n'
        '.card .value.green { color:#28a745; }\n'
        '.card .value.blue { color:#007bff; }\n'
        '.cluster-card { background:white; '
        'border-radius:10px;\n'
        '  padding:20px 25px; '
        'margin-bottom:15px;\n'
        '  box-shadow:0 2px 8px '
        'rgba(0,0,0,0.06); }\n'
        '.cluster-card-header { display:flex;\n'
        '  justify-content:space-between; '
        'align-items:flex-start;\n'
        '  margin-bottom:12px; flex-wrap:wrap; '
        'gap:10px; }\n'
        '.cluster-name { margin:0; '
        'font-size:18px; color:#1a1a2e; }\n'
        '.cluster-meta { font-size:12px; '
        'color:#888; }\n'
        '.cluster-status { padding:4px 14px; '
        'border-radius:15px;\n'
        '  font-size:12px; font-weight:700; }\n'
        '.status-blocker { background:#fde8e8; '
        'color:#dc3545; }\n'
        '.status-warning { background:#fff3cd; '
        'color:#856404; }\n'
        '.status-ok { background:#d4edda; '
        'color:#155724; }\n'
        '.cluster-card-metrics { display:flex; '
        'gap:20px;\n'
        '  flex-wrap:wrap; '
        'margin-bottom:10px; }\n'
        '.metric { text-align:center; '
        'min-width:70px; }\n'
        '.metric-val { display:block; '
        'font-size:22px; font-weight:700; }\n'
        '.metric-label { font-size:11px; '
        'color:#888; text-transform:uppercase; }\n'
        '.blocker-text { color:#dc3545; }\n'
        '.warning-text { color:#e67e22; }\n'
        '.info-text { color:#3498db; }\n'
        'details.findings-detail { '
        'margin-top:10px; }\n'
        'details.findings-detail summary { '
        'cursor:pointer;\n'
        '  color:#007bff; font-size:13px; '
        'font-weight:600; padding:5px 0; }\n'
        'details.findings-detail summary:hover '
        '{ text-decoration:underline; }\n'
        'summary.issues-summary { '
        'color:#dc3545; font-weight:700; }\n'
        '.findings-table { width:100%; '
        'border-collapse:collapse;\n'
        '  margin-top:8px; font-size:12px; }\n'
        '.findings-table th { background:#f8f9fa; '
        'padding:8px 10px;\n'
        '  text-align:left; font-size:11px; '
        'color:#555;\n'
        '  text-transform:uppercase; '
        'border-bottom:2px solid #dee2e6; }\n'
        '.findings-table td { padding:8px 10px;\n'
        '  border-bottom:1px solid #eee; '
        'vertical-align:top; }\n'
        '.findings-table tr.blocker '
        '{ background:#fff5f5; }\n'
        '.findings-table tr.warning '
        '{ background:#fffbf0; }\n'
        '.findings-table tr.info '
        '{ background:#f0f8ff; }\n'
        '.badge { padding:2px 10px; '
        'border-radius:10px;\n'
        '  font-size:11px; font-weight:700; }\n'
        '.badge-blocker { background:#dc3545; '
        'color:white; }\n'
        '.badge-warning { background:#ffc107; '
        'color:#333; }\n'
        '.badge-info { background:#17a2b8; '
        'color:white; }\n'
        '.check-badge { display:inline-block; '
        'background:#e9ecef;\n'
        '  padding:3px 10px; '
        'border-radius:12px;\n'
        '  font-size:11px; margin:2px; '
        'color:#495057; }\n'
        '.data-table { width:100%; '
        'border-collapse:collapse;\n'
        '  background:white; border-radius:8px; '
        'overflow:hidden;\n'
        '  box-shadow:0 2px 4px '
        'rgba(0,0,0,0.08);\n'
        '  margin-bottom:20px; '
        'font-size:13px; }\n'
        '.data-table th { background:#1a1a2e; '
        'color:white;\n'
        '  padding:10px 12px; text-align:left; '
        'font-size:12px; }\n'
        '.data-table td { padding:9px 12px;\n'
        '  border-bottom:1px solid #eee; '
        'vertical-align:top; }\n'
        '.data-table tr.blocker '
        '{ background:#fde8e8; }\n'
        '.data-table tr.warning '
        '{ background:#fef3e2; }\n'
        '.data-table tr:hover '
        '{ background:#f8f9fa; }\n'
        '.no-findings { color:#28a745; '
        'font-size:13px;\n'
        '  font-style:italic; margin:5px 0; }\n'
        'h2 { color:#1a1a2e; margin-top:35px; '
        'margin-bottom:15px;\n'
        '  padding-bottom:8px; '
        'border-bottom:2px solid #e9ecef; }\n'
        '.footer { margin-top:40px; color:#999; '
        'font-size:11px;\n'
        '  border-top:1px solid #ddd; '
        'padding-top:15px; text-align:center; }\n'
        '.section-note { background:#e8f4fd; '
        'border-left:4px solid #007bff;\n'
        '  padding:12px 16px; border-radius:4px; '
        'margin:15px 0; font-size:13px; }\n'
        '@media print {\n'
        '  .header { background:#1a1a2e '
        '!important;\n'
        '    -webkit-print-color-adjust:exact; }\n'
        '  details { display:block; }\n'
        '  details[open] summary '
        '{ display:none; }\n'
        '}\n'
        '</style>\n'
        '</head>\n<body>\n'
        '\n'
        '<div class="header">\n'
        '  <h1>&#128274; Rubrik CDM Pre-Upgrade '
        'Assessment Report</h1>\n'
        '  <div class="subtitle">'
        'Cross-Cluster Compatibility '
        'Dashboard</div>\n'
        '  <div class="header-meta">\n'
        '    <span>&#128225; Target CDM: <strong>'
        + _esc(target_ver)
        + '</strong></span>\n'
        '    <span>&#128336; Generated: '
        + timestamp + '</span>\n'
        '  </div>\n'
        '  <div class="header-badges">\n'
        '    <span class="header-badge" '
        'style="background:'
        + blocker_bg + ';color:white;">'
        + str(total_blockers)
        + ' Blockers</span>\n'
        '    <span class="header-badge" '
        'style="background:'
        + warning_bg + ';color:'
        + warning_fg + ';">'
        + str(total_warnings)
        + ' Warnings</span>\n'
        '  </div>\n'
        '</div>\n'
        '\n'
        '<div class="container">\n'
        '\n'
        '<div class="summary">\n'
        '  <div class="card"><h3>Discovered</h3>'
        '<div class="value blue">'
        + str(total_discovered)
        + '</div></div>\n'
        '  <div class="card"><h3>Assessed</h3>'
        '<div class="value">'
        + str(total_assessed)
        + '</div></div>\n'
        '  <div class="card"><h3>Skipped</h3>'
        '<div class="value">'
        + str(total_skipped)
        + '</div></div>\n'
        '  <div class="card"><h3>Failed</h3>'
        '<div class="value '
        + ("red" if total_failed > 0 else "green")
        + '">' + str(total_failed)
        + '</div></div>\n'
        '  <div class="card"><h3>Blockers</h3>'
        '<div class="value '
        + ("red" if total_blockers > 0
           else "green")
        + '">' + str(total_blockers)
        + '</div></div>\n'
        '  <div class="card"><h3>Warnings</h3>'
        '<div class="value '
        + ("orange" if total_warnings > 0
           else "green")
        + '">' + str(total_warnings)
        + '</div></div>\n'
        '</div>\n\n'
    )

    if checks_badges:
        html += (
            '<div class="section-note">\n'
            '  <strong>Checks Performed:</strong> '
            + checks_badges + '\n'
            '</div>\n'
        )

    # Cross-cluster issues FIRST (most important)
    html += issues_section + '\n'

    # Then per-cluster details
    html += (
        '<h2>&#128203; Cluster Assessments ('
        + str(total_assessed) + ')</h2>\n'
        + cluster_cards + '\n'
    )

    # Skipped / Failed
    html += skipped_section + '\n'

    # Footer
    html += (
        '<div class="footer">\n'
        '  Rubrik CDM Pre-Upgrade Assessment Tool'
        ' | Target: ' + _esc(target_ver)
        + ' | ' + str(total_assessed)
        + ' clusters assessed'
        + ' | ' + timestamp + '\n'
        '</div>\n'
        '\n'
        '</div>\n'
        '</body>\n</html>\n'
    )

    with open(html_file, "w",
              encoding="utf-8") as fh:
        fh.write(html)

    return html_file     
# ==============================================================
#  Main Orchestrator
# ==============================================================
def main():
    errors = Config.validate()
    if errors:
        print("", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(
            "  CONFIGURATION ERRORS",
            file=sys.stderr,
        )
        print("=" * 60, file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        print("", file=sys.stderr)
        print(
            "  Create a .env file from .env.example.",
            file=sys.stderr,
        )
        print("=" * 60, file=sys.stderr)
        return 1

    global logger
    logger = setup_logging()

    target_cdm = Config.TARGET_CDM_VERSION or "Latest"
    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )
    master_output_dir = os.path.join(
        Config.OUTPUT_DIR,
        "assessment_" + timestamp,
    )
    os.makedirs(master_output_dir, exist_ok=True)

    logger.info("=" * 70)
    logger.info(
        "  RUBRIK CDM PRE-UPGRADE COMPATIBILITY "
        "ASSESSMENT"
    )
    logger.info(
        "  Multi-Cluster Mode -- RSC GraphQL + "
        "CDM Direct API"
    )
    logger.info("=" * 70)
    logger.info(
        "  RSC Instance:       %s",
        Config.RSC_BASE_URL,
    )
    logger.info(
        "  Target CDM Version: %s", target_cdm,
    )
    logger.info(
        "  Max parallel:       %d clusters",
        Config.MAX_PARALLEL_CLUSTERS,
    )
    logger.info(
        "  Output directory:   %s",
        master_output_dir,
    )
    logger.info("=" * 70)

    # ── Initialize RSC Client ──
    client = RSCClient()

    # ── PHASE 1: Discover ──
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 1: Discovering clusters...")
    logger.info("=" * 60)

    all_clusters = discover_all_clusters(client)
    logger.info(
        "  Discovered %d cluster(s)",
        len(all_clusters),
    )

    if not all_clusters:
        logger.error("  No clusters found. Exiting.")
        return 2

    # ── PHASE 2: Enrich (parallel) ──
    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "PHASE 2: Enriching %d cluster(s)...",
        len(all_clusters),
    )
    logger.info("=" * 60)

    enrichment_workers = min(
        getattr(
            Config, "MAX_PARALLEL_ENRICHMENT", 5
        ),
        len(all_clusters),
    )
    progress_enrich = ProgressTracker(
        len(all_clusters), "enrichment"
    )

    def enrich_wrapper(cluster):
        try:
            enrich_cluster(client, cluster)
            progress_enrich.complete(cluster.name)
        except Exception as e:
            logger.warning(
                "  [%s] Enrichment failed: %s",
                cluster.name, e,
            )
            progress_enrich.fail(cluster.name)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=enrichment_workers,
        thread_name_prefix="enrich",
    ) as executor:
        list(executor.map(
            enrich_wrapper, all_clusters
        ))

    # ── PHASE 3: Filter ──
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 3: Filtering clusters...")
    logger.info("=" * 60)

    to_assess, skipped = filter_clusters(all_clusters)
    total = len(to_assess)

    logger.info(
        "  To assess: %d  |  Skipped: %d",
        total, len(skipped),
    )

    for c in to_assess:
        ips = ""
        if hasattr(c, "node_ips") and c.node_ips:
            preview = c.node_ips[:3]
            ips = " (" + ", ".join(preview)
            if len(c.node_ips) > 3:
                ips += ", ..."
            ips += ")"
        logger.info(
            "    [ASSESS] %s v%s (%d nodes)%s",
            c.name, c.version,
            c.node_count, ips,
        )

    for s in skipped:
        logger.info(
            "    [SKIP]   %s — %s",
            s.name, s.skip_reason,
        )

    if total == 0:
        logger.warning(
            "  No clusters to assess after "
            "filtering."
        )
        return 0

    # ── PHASE 4: Assess (parallel) ──
    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "PHASE 4: Assessing %d cluster(s) "
        "(max %d parallel)...",
        total, Config.MAX_PARALLEL_CLUSTERS,
    )
    logger.info("=" * 60)

    ma = create_multi_assessment(
        target_version=target_cdm,
        output_dir=master_output_dir,
    )

    for s in skipped:
        ma.add_skipped(s, s.skip_reason)

    progress = ProgressTracker(total, "clusters")

    def assess_wrapper(idx_cluster):
        idx, cluster = idx_cluster
        threading.current_thread().name = (
            "cluster-" + cluster.name
        )

        try:
            assessment = assess_single_cluster(
                client, cluster, target_cdm,
            )
            ma.add_assessment(assessment)
            progress.complete(cluster.name)

            if assessment.total_blockers > 0:
                level = logging.WARNING
            else:
                level = logging.INFO

            duration = assessment.assessment_duration_sec
            logger.log(
                level,
                "  [%s] %d blockers, %d warnings, "
                "%d info (%.1fs)",
                cluster.name,
                assessment.total_blockers,
                assessment.total_warnings,
                assessment.total_info,
                duration,
            )
            return ("success", cluster, assessment)

        except Exception as e:
            error_msg = (
                type(e).__name__ + ": " + str(e)
            )
            logger.error(
                "  [%s] FAILED: %s",
                cluster.name, error_msg,
            )
            logger.debug(traceback.format_exc())
            ma.add_failure(cluster, error_msg)
            progress.fail(cluster.name)
            return ("error", cluster, error_msg)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=Config.MAX_PARALLEL_CLUSTERS,
        thread_name_prefix="assess",
    ) as executor:
        list(executor.map(
            assess_wrapper,
            enumerate(to_assess, 1),
        ))

    ma.finalize()

    # ── PHASE 5: Generate Reports ──
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 5: Generating reports...")
    logger.info("=" * 60)

    all_files = generate_reports(
        ma, master_output_dir,
    )

    # ── PHASE 6: Summary ──
    client.log_stats()
    print_final_summary(
        ma, all_files, master_output_dir,
        progress=progress.summary,
        api_stats=client.get_stats(),
    )

    data = ma.to_dict()
    if data.get("total_blockers", 0) > 0:
        count = data["total_blockers"]
        logger.warning(
            "\n  %d BLOCKER(S) FOUND -- "
            "Upgrade should NOT proceed "
            "until resolved.\n",
            count,
        )
        return 1

    if data.get("total_failed", 0) > 0:
        count = data["total_failed"]
        logger.warning(
            "\n  %d cluster(s) FAILED assessment "
            "-- Review failures before "
            "proceeding.\n",
            count,
        )
        return 2

    logger.info(
        "\n  No blockers found. Clusters appear "
        "ready for upgrade review.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())