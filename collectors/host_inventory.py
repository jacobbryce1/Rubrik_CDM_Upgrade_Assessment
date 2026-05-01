#!/usr/bin/env python3
"""
Collector: Host Inventory via RSC GraphQL
Ported from original working tool [1].

Uses inventoryRoot.descendantConnection with
typeFilter: [PhysicalHost].

RSC schema fixes:
- operatingSystemType does NOT exist on PhysicalHost
- agentStatus does NOT exist on PhysicalHost
  (RSC suggested cbtStatus, slaPauseStatus)
- Agent versions only available via CDM direct API
"""

import logging
from collectors import CollectionResult, CollectorTimer
from config import Config

logger = logging.getLogger(__name__)


# ==============================================================
# GraphQL Queries — inventoryRoot [1]
# Removed: operatingSystemType, agentStatus
# ==============================================================

HOST_INVENTORY_QUERY = """
query HostInventory($first: Int, $after: String) {
    inventoryRoot {
        descendantConnection(
            first: $first
            after: $after
            typeFilter: [PhysicalHost]
        ) {
            edges {
                node {
                    id
                    name
                    objectType
                    ... on PhysicalHost {
                        osName
                        osType
                        connectionStatus {
                            connectivity
                        }
                        cluster {
                            id
                            name
                        }
                    }
                }
            }
            pageInfo {
                hasNextPage
                endCursor
            }
            count
        }
    }
}
"""

HOST_INVENTORY_MINIMAL = """
query HostInventoryMinimal($first: Int, $after: String) {
    inventoryRoot {
        descendantConnection(
            first: $first
            after: $after
            typeFilter: [PhysicalHost]
        ) {
            edges {
                node {
                    id
                    name
                    objectType
                    ... on PhysicalHost {
                        osName
                        osType
                        cluster {
                            id
                            name
                        }
                    }
                }
            }
            pageInfo {
                hasNextPage
                endCursor
            }
            count
        }
    }
}
"""


# ==============================================================
# OS Compatibility Matrix
# ==============================================================

OS_COMPATIBILITY = {
    "Windows": {
        "supported": [
            "Windows Server 2022",
            "Windows Server 2019",
            "Windows Server 2016",
            "Windows Server 2012 R2",
            "Windows Server 2012",
            "Windows 11", "Windows 10",
        ],
        "deprecated_in_9_5": [
            "Windows Server 2012",
            "Windows Server 2008 R2",
            "Windows Server 2008",
        ],
        "unsupported": [
            "Windows Server 2003",
            "Windows Server 2000",
            "Windows XP", "Windows 7", "Windows 8",
        ],
    },
    "Linux": {
        "supported": [
            "Red Hat Enterprise Linux 9",
            "Red Hat Enterprise Linux 8",
            "Red Hat Enterprise Linux 7",
            "RHEL 9", "RHEL 8", "RHEL 7",
            "CentOS 9", "CentOS 8", "CentOS 7",
            "Ubuntu 22.04", "Ubuntu 20.04",
            "Ubuntu 18.04",
            "SUSE Linux Enterprise Server 15",
            "SUSE Linux Enterprise Server 12",
            "SLES 15", "SLES 12",
            "Oracle Linux 9", "Oracle Linux 8",
            "Oracle Linux 7",
            "Debian 12", "Debian 11", "Debian 10",
            "Amazon Linux 2023", "Amazon Linux 2",
        ],
        "deprecated_in_9_5": [
            "Red Hat Enterprise Linux 6",
            "RHEL 6", "CentOS 6", "Ubuntu 16.04",
            "SUSE Linux Enterprise Server 11",
            "SLES 11", "Oracle Linux 6", "Debian 9",
        ],
        "unsupported": [
            "Red Hat Enterprise Linux 5",
            "RHEL 5", "CentOS 5",
            "Ubuntu 14.04", "Ubuntu 12.04",
            "Debian 8", "Debian 7",
        ],
    },
}


# ==============================================================
# Cluster Matching
# ==============================================================

def host_matches_cluster(host, cluster):
    hc = host.get("cluster") or {}
    hc_id = hc.get("id", "")
    hc_name = hc.get("name", "")

    if hc_id and hc_id == cluster.cluster_id:
        return True
    if hc_name and cluster.name:
        if hc_name.lower() == cluster.name.lower():
            return True
    if hc_id and cluster.cluster_id:
        if (cluster.cluster_id in hc_id or
                hc_id in cluster.cluster_id):
            return True
    return False


# ==============================================================
# Host Fetch
# ==============================================================

def fetch_hosts(client, cluster):
    """Fetch hosts via inventoryRoot [1]."""
    # Strategy 1: Full fields
    try:
        logger.debug(
            "  [%s] Fetching hosts via inventoryRoot...",
            cluster.name
        )
        all_hosts = client.graphql_paginated(
            query=HOST_INVENTORY_QUERY,
            connection_path=[
                "inventoryRoot",
                "descendantConnection",
            ],
            page_size=200,
        )
        if all_hosts is not None and len(all_hosts) > 0:
            cluster_hosts = [
                h for h in all_hosts
                if host_matches_cluster(h, cluster)
            ]
            logger.debug(
                "  [%s] Hosts: %d of %d match cluster",
                cluster.name,
                len(cluster_hosts),
                len(all_hosts)
            )
            if cluster_hosts:
                return cluster_hosts
            return all_hosts
    except Exception as e:
        logger.debug(
            "  [%s] Host inventory full query "
            "failed: %s",
            cluster.name, e
        )

    # Strategy 2: Minimal fields
    try:
        logger.debug(
            "  [%s] Trying minimal host query...",
            cluster.name
        )
        all_hosts = client.graphql_paginated(
            query=HOST_INVENTORY_MINIMAL,
            connection_path=[
                "inventoryRoot",
                "descendantConnection",
            ],
            page_size=200,
        )
        if all_hosts is not None and len(all_hosts) > 0:
            cluster_hosts = [
                h for h in all_hosts
                if host_matches_cluster(h, cluster)
            ]
            if cluster_hosts:
                return cluster_hosts
            return all_hosts
    except Exception as e:
        logger.debug(
            "  [%s] Minimal host query failed: %s",
            cluster.name, e
        )

    logger.warning(
        "  [%s] All host inventory queries failed.",
        cluster.name
    )
    return []


# ==============================================================
# Analysis Functions
# ==============================================================

def analyze_connectivity(result, cluster_name, hosts):
    """Analyze host connectivity [1]."""
    connected = []
    disconnected = []
    unknown = []

    for host in hosts:
        conn = host.get("connectionStatus") or {}
        status = (
            conn.get("connectivity") or ""
        ).upper()

        if status == "CONNECTED":
            connected.append(host)
        elif status == "DISCONNECTED":
            disconnected.append(host)
        else:
            unknown.append(host)

    stats = {
        "connected": len(connected),
        "disconnected": len(disconnected),
        "unknown": len(unknown),
        "total": len(hosts),
    }

    if disconnected:
        result.add_warning(
            str(len(disconnected)) + " of " +
            str(len(hosts)) +
            " host(s) are DISCONNECTED on " +
            cluster_name +
            ". Reconnect before upgrade.",
            {
                "check": "host_connectivity",
                "count": len(disconnected),
                "connected": len(connected),
                "unknown": len(unknown),
            },
        )

        for host in disconnected:
            name = host.get("name", "?")
            os_name = host.get("osName", "Unknown OS")
            os_type = host.get("osType", "?")

            result.findings.append({
                "severity": "WARNING",
                "check": "disconnected_host_detail",
                "message": (
                    "Host '" + name + "' (" +
                    os_name + ", " + os_type +
                    ") is disconnected"
                ),
                "host_name": name,
                "host_id": host.get("id", ""),
            })
    else:
        result.add_info(
            "All " + str(len(connected)) +
            " host(s) are connected (" +
            str(len(unknown)) +
            " with unknown status).",
            {"check": "host_connectivity"},
        )

    return stats


def analyze_os_distribution(result, cluster_name,
                             hosts):
    """Analyze OS distribution [1]."""
    os_type_counts = {}
    os_name_counts = {}
    unknown_os = []

    for host in hosts:
        os_type = (
            host.get("osType", "Unknown") or "Unknown"
        )
        os_name = host.get("osName", "") or ""

        os_type_counts[os_type] = (
            os_type_counts.get(os_type, 0) + 1
        )
        if os_name:
            os_name_counts[os_name] = (
                os_name_counts.get(os_name, 0) + 1
            )
        else:
            unknown_os.append(host)

    dist_parts = [
        str(count) + " " + os_type
        for os_type, count in sorted(
            os_type_counts.items(),
            key=lambda x: x[1], reverse=True,
        )
    ]

    result.add_info(
        "OS distribution on " + cluster_name + ": " +
        ", ".join(dist_parts) + ". (" +
        str(len(unknown_os)) + " with unknown OS.)",
        {
            "check": "os_distribution",
            "os_type_counts": os_type_counts,
            "os_name_counts": os_name_counts,
        },
    )

    return {
        "os_type_counts": os_type_counts,
        "os_name_counts": os_name_counts,
        "unknown_os": len(unknown_os),
    }


def analyze_os_compatibility(result, cluster_name,
                              hosts, target_version):
    """Check host OS against compatibility matrix [1]."""
    from collectors.upgrade_prechecks import version_gte

    deprecated = []
    unsupported = []
    checked = 0

    for host in hosts:
        os_name = (host.get("osName") or "").strip()
        os_type = (host.get("osType") or "").upper()
        name = host.get("name", "?")

        if not os_name:
            continue
        checked += 1

        os_category = None
        if (os_type in ("WINDOWS",) or
                "WINDOWS" in os_name.upper()):
            os_category = "Windows"
        elif (os_type in ("LINUX",) or any(
            x in os_name.upper()
            for x in ("LINUX", "RHEL", "CENTOS",
                       "UBUNTU", "SUSE", "SLES",
                       "ORACLE", "DEBIAN", "AMAZON")
        )):
            os_category = "Linux"

        if not os_category:
            continue

        compat = OS_COMPATIBILITY.get(
            os_category, {}
        )

        is_unsupported = False
        for unsup in compat.get("unsupported", []):
            if unsup.upper() in os_name.upper():
                is_unsupported = True
                unsupported.append({
                    "host_name": name,
                    "os_name": os_name,
                })
                break

        if is_unsupported:
            continue

        if version_gte(target_version, "9.5.0"):
            for dep in compat.get(
                "deprecated_in_9_5", []
            ):
                if dep.upper() in os_name.upper():
                    deprecated.append({
                        "host_name": name,
                        "os_name": os_name,
                    })
                    break

    if unsupported:
        result.add_warning(
            str(len(unsupported)) +
            " host(s) running UNSUPPORTED OS.",
            {"check": "os_unsupported",
             "count": len(unsupported)},
        )
        for h in unsupported:
            result.findings.append({
                "severity": "WARNING",
                "check": "os_unsupported_detail",
                "message": (
                    "Host '" + h["host_name"] +
                    "' runs unsupported OS: " +
                    h["os_name"]
                ),
            })

    if deprecated:
        result.add_warning(
            str(len(deprecated)) +
            " host(s) running DEPRECATED OS "
            "in CDM " + target_version + ".",
            {"check": "os_deprecated",
             "count": len(deprecated)},
        )
        for h in deprecated[:50]:
            result.findings.append({
                "severity": "WARNING",
                "check": "os_deprecated_detail",
                "message": (
                    "Host '" + h["host_name"] +
                    "' runs deprecated OS: " +
                    h["os_name"]
                ),
            })

    if (checked > 0 and not unsupported and
            not deprecated):
        result.add_info(
            str(checked) +
            " host OS version(s) checked -- all "
            "compatible with CDM " +
            target_version + ".",
            {"check": "os_compatibility",
             "checked": checked},
        )

    return {
        "checked": checked,
        "unsupported": len(unsupported),
        "deprecated": len(deprecated),
    }


def analyze_agent_versions(result, cluster_name, hosts):
    """
    Agent status not available via RSC on this schema.
    agentStatus field does not exist on PhysicalHost.
    Agent versions can be checked via CDM direct API.
    """
    result.add_info(
        "RBS agent version data not available via "
        "RSC for " + cluster_name + ". "
        "Agent versions checked via CDM direct API "
        "if available.",
        {"check": "agent_version_distribution"},
    )
    return {
        "version_counts": {},
        "total": 0,
        "no_agent": len(hosts),
    }


# ==============================================================
# Main Collector Entry Point
# ==============================================================

def collect_host_inventory(client, cluster):
    """Host inventory via inventoryRoot [1]."""
    result = CollectionResult(
        collector_name="host_inventory"
    )

    with CollectorTimer(result):
        logger.debug(
            "  [%s] Collecting RSC host inventory...",
            cluster.name
        )

        target_version = cluster.raw_data.get(
            "_target_version", ""
        )

        hosts = fetch_hosts(client, cluster)

        if not hosts:
            result.add_info(
                "No hosts found for " +
                cluster.name + " via RSC.",
                {"check": "host_inventory",
                 "count": 0},
            )
            return result

        result.add_info(
            "RSC host inventory: " +
            str(len(hosts)) + " host(s) on " +
            cluster.name + ".",
            {"check": "host_inventory",
             "count": len(hosts)},
        )

        result.raw_data = {"hosts": hosts}

        # Connectivity
        connectivity_stats = analyze_connectivity(
            result, cluster.name, hosts
        )

        # OS distribution
        os_stats = analyze_os_distribution(
            result, cluster.name, hosts
        )

        # OS compatibility
        compat_stats = {}
        if target_version:
            compat_stats = analyze_os_compatibility(
                result, cluster.name, hosts,
                target_version
            )

        # Agent versions (not available via RSC)
        agent_stats = analyze_agent_versions(
            result, cluster.name, hosts
        )

        result.summary = {
            "total_hosts": len(hosts),
            "connectivity": connectivity_stats,
            "os_distribution": os_stats,
            "os_compatibility": compat_stats,
            "agent_versions": agent_stats,
        }

        logger.debug(
            "  [%s] Host inventory complete: "
            "%d hosts, %dB / %dW / %dI",
            cluster.name, len(hosts),
            len(result.blockers),
            len(result.warnings),
            len(result.info_messages)
        )

    return result