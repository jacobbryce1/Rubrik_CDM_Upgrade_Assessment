#!/usr/bin/env python3
"""
Collector: CDM System Status
Ported from original working tool [1].

All CDM REST API endpoints use FULL path matching original:
- api/v1/cluster/me [1]
- api/v1/cluster/me/node [1]
- api/v1/cluster/me/dns_nameserver [1]
- api/v1/cluster/me/ntp_server [1]
- api/v1/stats/system_storage [1]
- api/internal/event_series [1]

Running jobs uses CDM REST API (NOT RSC GraphQL)
to avoid activitySeriesConnection 400 errors [2].
"""

import logging
from collectors import CollectionResult, CollectorTimer
from config import Config

logger = logging.getLogger(__name__)


def check_system_status(result, client, cluster):
    """
    Check overall cluster system status.
    Tries api/internal/cluster/me/system_status first,
    falls back to api/v1/cluster/me [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/internal/cluster/me/system_status",
            cluster_id=cluster.cluster_id,
        )

        if data is None:
            data = client.cdm_direct_get(
                "api/v1/cluster/me",
                cluster_id=cluster.cluster_id,
            )

        if data and isinstance(data, dict):
            status = (
                data.get("status") or
                data.get("systemStatus") or
                ""
            ).upper()

            if not status:
                result.add_info(
                    "System status not available "
                    "via CDM API.",
                    {"check": "system_status"},
                )
            elif status in ("OK", "HEALTHY"):
                result.add_info(
                    "Cluster system status: " + status,
                    {"check": "system_status",
                     "status": status},
                )
            elif status in ("DEGRADED", "WARNING"):
                result.add_warning(
                    "Cluster system status: '" +
                    status + "'. Investigate "
                    "before upgrading.",
                    {"check": "system_status",
                     "status": status},
                )
            else:
                result.add_blocker(
                    "Cluster system status: '" +
                    status + "'. Resolve "
                    "before upgrading.",
                    {"check": "system_status",
                     "status": status},
                )
        else:
            result.add_info(
                "System status endpoint returned "
                "empty response.",
                {"check": "system_status"},
            )
    except Exception as e:
        logger.debug(
            "  [%s] System status check failed: %s",
            cluster.name, e
        )


def check_cluster_info(result, client, cluster):
    """
    Get cluster basic info via CDM REST API.
    Uses GET api/v1/cluster/me [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/v1/cluster/me",
            cluster_id=cluster.cluster_id,
        )
        if data and isinstance(data, dict):
            name = data.get("name", "")
            version = data.get("version", "")
            node_count = data.get("nodeCount", 0)
            api_version = data.get("apiVersion", "")

            result.add_info(
                "CDM API reports: name='" + name +
                "', version=" + version +
                ", nodes=" + str(node_count) +
                ", apiVersion=" + api_version,
                {"check": "cluster_api_info",
                 "name": name,
                 "version": version,
                 "node_count": node_count},
            )

            if node_count and cluster.node_count:
                if node_count != cluster.node_count:
                    result.add_warning(
                        "Node count mismatch: CDM API "
                        "reports " + str(node_count) +
                        " nodes, RSC reports " +
                        str(cluster.node_count) +
                        " nodes.",
                        {"check": "node_count_mismatch"},
                    )
        else:
            result.add_info(
                "Cluster info endpoint returned "
                "empty response.",
                {"check": "cluster_api_info"},
            )
    except Exception as e:
        logger.debug(
            "  [%s] Cluster info check failed: %s",
            cluster.name, e
        )


def check_node_status(result, client, cluster):
    """
    Check individual node health.
    Uses GET api/v1/cluster/me/node [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/v1/cluster/me/node",
            cluster_id=cluster.cluster_id,
        )
        if not data:
            return

        nodes = []
        if isinstance(data, dict):
            nodes = data.get("data", [])
            if not nodes:
                nodes = data.get("nodes", [])
        elif isinstance(data, list):
            nodes = data

        if not nodes:
            return

        healthy = 0
        unhealthy = []

        for node in nodes:
            node_id = node.get("id", "?")
            status = (node.get("status") or "").upper()
            ip = node.get("ipAddress", "")

            if status in ("OK", "HEALTHY", ""):
                healthy += 1
            else:
                unhealthy.append({
                    "node_id": node_id,
                    "status": status,
                    "ip": ip,
                })

        if unhealthy:
            for n in unhealthy:
                result.add_blocker(
                    "Node " + n["node_id"] +
                    " (" + n["ip"] + ") status: '" +
                    n["status"] +
                    "'. All nodes must be healthy.",
                    {"check": "node_status",
                     "node_id": n["node_id"],
                     "status": n["status"]},
                )
        else:
            result.add_info(
                "All " + str(healthy) +
                " node(s) are healthy.",
                {"check": "node_status",
                 "healthy": healthy,
                 "total": len(nodes)},
            )

        result.summary["node_health"] = {
            "healthy": healthy,
            "unhealthy": len(unhealthy),
            "total": len(nodes),
        }

    except Exception as e:
        logger.debug(
            "  [%s] Node status check failed: %s",
            cluster.name, e
        )


def check_dns_config(result, client, cluster):
    """
    Check DNS server configuration.
    Uses GET api/v1/cluster/me/dns_nameserver [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/v1/cluster/me/dns_nameserver",
            cluster_id=cluster.cluster_id,
        )
        if data is not None:
            dns_list = data if isinstance(data, list) else []
            if len(dns_list) == 0:
                result.add_warning(
                    "No DNS servers configured on " +
                    cluster.name + ".",
                    {"check": "dns_config",
                     "dns_count": 0},
                )
            elif len(dns_list) == 1:
                result.add_warning(
                    "Only 1 DNS server configured on " +
                    cluster.name +
                    ". Recommend at least 2.",
                    {"check": "dns_config",
                     "dns_count": 1},
                )
            else:
                result.add_info(
                    str(len(dns_list)) +
                    " DNS server(s) configured.",
                    {"check": "dns_config",
                     "dns_count": len(dns_list)},
                )

            result.summary["dns_servers"] = len(dns_list)

    except Exception as e:
        logger.debug(
            "  [%s] DNS check failed: %s",
            cluster.name, e
        )


def check_ntp_config(result, client, cluster):
    """
    Check NTP server configuration.
    Uses GET api/v1/cluster/me/ntp_server [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/v1/cluster/me/ntp_server",
            cluster_id=cluster.cluster_id,
        )
        if data is not None:
            ntp_list = data if isinstance(data, list) else []
            if len(ntp_list) == 0:
                result.add_warning(
                    "No NTP servers configured on " +
                    cluster.name + ".",
                    {"check": "ntp_config",
                     "ntp_count": 0},
                )
            else:
                result.add_info(
                    str(len(ntp_list)) +
                    " NTP server(s) configured.",
                    {"check": "ntp_config",
                     "ntp_count": len(ntp_list)},
                )

            result.summary["ntp_servers"] = len(ntp_list)

    except Exception as e:
        logger.debug(
            "  [%s] NTP check failed: %s",
            cluster.name, e
        )


def check_support_tunnel(result, client, cluster):
    """
    Check support tunnel status.
    Uses GET api/v1/cluster/me/support/tunnel [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/v1/cluster/me/support/tunnel",
            cluster_id=cluster.cluster_id,
        )
        if data and isinstance(data, dict):
            enabled = data.get("isTunnelEnabled", False)
            port = data.get("port", "")

            if enabled:
                result.add_info(
                    "Support tunnel is ENABLED "
                    "(port: " + str(port) + ").",
                    {"check": "support_tunnel",
                     "enabled": True},
                )
            else:
                result.add_info(
                    "Support tunnel is disabled.",
                    {"check": "support_tunnel",
                     "enabled": False},
                )
    except Exception as e:
        logger.debug(
            "  [%s] Support tunnel check failed: %s",
            cluster.name, e
        )


def check_storage(result, client, cluster):
    """
    Check cluster storage utilization.
    Uses GET api/v1/stats/system_storage [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/v1/stats/system_storage",
            cluster_id=cluster.cluster_id,
        )
        if data and isinstance(data, dict):
            total = data.get("total", 0)
            used = data.get("used", 0)
            available = data.get("available", 0)
            snapshot = data.get("snapshot", 0)
            live_mount = data.get("liveMount", 0)

            if total > 0:
                used_pct = (used / total) * 100

                result.summary["storage"] = {
                    "total_bytes": total,
                    "used_bytes": used,
                    "available_bytes": available,
                    "used_pct": round(used_pct, 1),
                    "snapshot_bytes": snapshot,
                    "live_mount_bytes": live_mount,
                }

                if used_pct >= 95:
                    result.add_blocker(
                        "Storage critically full: " +
                        str(round(used_pct, 1)) +
                        "% used. Free space "
                        "before upgrade.",
                        {"check": "storage",
                         "used_pct": round(used_pct, 1)},
                    )
                elif used_pct >= 85:
                    result.add_warning(
                        "Storage utilization high: " +
                        str(round(used_pct, 1)) +
                        "% used.",
                        {"check": "storage",
                         "used_pct": round(used_pct, 1)},
                    )
                else:
                    result.add_info(
                        "Storage utilization: " +
                        str(round(used_pct, 1)) +
                        "% used.",
                        {"check": "storage",
                         "used_pct": round(used_pct, 1)},
                    )

    except Exception as e:
        logger.debug(
            "  [%s] Storage check failed: %s",
            cluster.name, e
        )


def check_running_jobs(result, client, cluster):
    """
    Check for running/queued jobs via CDM REST API.
    Uses CDM api/internal/event_series instead of
    RSC GraphQL activitySeriesConnection [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/internal/event_series"
            "?status=Active&limit=100",
            cluster_id=cluster.cluster_id,
        )

        if data is None:
            data = client.cdm_direct_get(
                "api/v1/event_series"
                "?status=Active&limit=100",
                cluster_id=cluster.cluster_id,
            )

        if data is None:
            result.add_info(
                "Could not check running jobs "
                "via CDM API.",
                {"check": "running_jobs"},
            )
            return

        jobs = []
        if isinstance(data, dict):
            jobs = data.get("data", [])
        elif isinstance(data, list):
            jobs = data

        if not jobs:
            result.add_info(
                "No running or queued jobs on " +
                cluster.name + ".",
                {"check": "running_jobs", "count": 0},
            )
            return

        result.summary["running_jobs"] = {
            "count": len(jobs),
        }

        if len(jobs) > 50:
            result.add_warning(
                str(len(jobs)) +
                " active job(s) on " +
                cluster.name +
                ". Allow jobs to complete "
                "before upgrading.",
                {"check": "running_jobs",
                 "count": len(jobs)},
            )
        else:
            result.add_info(
                str(len(jobs)) +
                " active job(s) on " +
                cluster.name + ".",
                {"check": "running_jobs",
                 "count": len(jobs)},
            )

    except Exception as e:
        logger.debug(
            "  [%s] Running jobs check failed: %s",
            cluster.name, e
        )


def add_manual_check_reminders(result, cluster):
    """Manual check reminders [1]."""
    result.add_warning(
        "MANUAL CHECK: Verify no CDM local API tokens "
        "are in use. CDM 9.5.1+ removes legacy API "
        "token support. "
        "Check CDM UI > Settings > API Token Management.",
        {"check": "manual_api_tokens"},
    )

    result.add_warning(
        "MANUAL CHECK: Review CDM local service accounts. "
        "CDM 9.5.1+ changes service account behavior. "
        "Check CDM UI > Settings > Service Accounts.",
        {"check": "manual_service_accounts"},
    )


# ==============================================================
# Main Collector Entry Point
# ==============================================================

def collect_system_status(client, cluster):
    """
    Comprehensive system status checks via CDM REST API.
    All endpoints use full path matching original tool [1].
    """
    result = CollectionResult(
        collector_name="cdm_system_status"
    )

    with CollectorTimer(result):
        logger.debug(
            "  [%s] Running CDM system status checks...",
            cluster.name
        )

        check_system_status(result, client, cluster)
        check_cluster_info(result, client, cluster)
        check_node_status(result, client, cluster)
        check_dns_config(result, client, cluster)
        check_ntp_config(result, client, cluster)
        check_support_tunnel(result, client, cluster)
        check_storage(result, client, cluster)
        check_running_jobs(result, client, cluster)
        add_manual_check_reminders(result, cluster)

        logger.debug(
            "  [%s] CDM system status complete: "
            "%dB / %dW / %dI",
            cluster.name,
            len(result.blockers),
            len(result.warnings),
            len(result.info_messages)
        )

    return result