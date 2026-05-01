#!/usr/bin/env python3
"""
Collector: Workload Inventory
Ported from original working tool [1].

Uses inventoryRoot.descendantConnection with typeFilter.

RSC HierarchyObjectTypeEnum values (from RSC error):
- VSphereVirtualMachine (not VsphereVm)
- PhysicalHost (correct)
- MssqlInstance (not MssqlDatabase)
- OracleHost (not OracleDatabase)
- NasShare (not NasFileset)
- MANAGED_VOLUME_EXPORT (not ManagedVolume)
- HypervServer (not HyperVVirtualMachine)
- VolumeGroup (correct)
- NutanixCluster (not NutanixVm)
"""

import logging
from collectors import CollectionResult, CollectorTimer
from config import Config

logger = logging.getLogger(__name__)


def node_matches_cluster(node, cluster):
    nc = node.get("cluster") or {}
    nc_id = nc.get("id", "")
    nc_name = nc.get("name", "")

    if nc_id and nc_id == cluster.cluster_id:
        return True
    if nc_name and cluster.name:
        if nc_name.lower() == cluster.name.lower():
            return True
    if nc_id and cluster.cluster_id:
        if (cluster.cluster_id in nc_id or
                nc_id in cluster.cluster_id):
            return True
    return False


# ==============================================================
# GraphQL Query — corrected enum values
# ==============================================================

WORKLOAD_INVENTORY_QUERY = """
query WorkloadInventory($first: Int, $after: String, $typeFilter: [HierarchyObjectTypeEnum!]) {
    inventoryRoot {
        descendantConnection(
            first: $first
            after: $after
            typeFilter: $typeFilter
        ) {
            edges {
                node {
                    id
                    name
                    objectType
                    ... on PhysicalHost {
                        osName
                        osType
                        connectionStatus { connectivity }
                        cluster { id name }
                    }
                    ... on VsphereVm {
                        effectiveSlaDomain { id name }
                        cluster { id name }
                    }
                    ... on MssqlInstance {
                        effectiveSlaDomain { id name }
                        cluster { id name }
                    }
                    ... on MssqlDatabase {
                        effectiveSlaDomain { id name }
                        cluster { id name }
                    }
                    ... on OracleHost {
                        effectiveSlaDomain { id name }
                        cluster { id name }
                    }
                    ... on OracleDatabase {
                        effectiveSlaDomain { id name }
                        cluster { id name }
                    }
                    ... on NasShare {
                        effectiveSlaDomain { id name }
                        cluster { id name }
                    }
                    ... on ManagedVolume {
                        effectiveSlaDomain { id name }
                        cluster { id name }
                        managedVolumeType
                        state
                    }
                    ... on HypervServer {
                        cluster { id name }
                    }
                    ... on VolumeGroup {
                        effectiveSlaDomain { id name }
                        cluster { id name }
                    }
                    ... on NutanixCluster {
                        cluster { id name }
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

# Correct HierarchyObjectTypeEnum values from RSC
# Use AllSubHierarchyType to get everything
# then filter by objectType client-side.
# VSphereVirtualMachine is not a valid enum value
# but VsphereVm works as an inline fragment type.
WORKLOAD_TYPE_FILTERS = [
    "AllSubHierarchyType",
]

WORKLOAD_LABELS = {
    "VSphereVirtualMachine": "VMware VMs",
    "MssqlInstance": "MSSQL Instances",
    "MssqlDatabase": "MSSQL Databases",
    "OracleHost": "Oracle Hosts",
    "OracleDatabase": "Oracle Databases",
    "PhysicalHost": "Physical Hosts",
    "NasShare": "NAS Shares",
    "MANAGED_VOLUME_EXPORT": "Managed Volumes",
    "ManagedVolume": "Managed Volumes",
    "HypervServer": "Hyper-V Servers",
    "VolumeGroup": "Volume Groups",
    "NutanixCluster": "Nutanix Clusters",
}


# ==============================================================
# Analysis Functions
# ==============================================================

def analyze_host_connectivity(result, hosts,
                               cluster_name):
    disconnected = []
    connected = 0
    unknown = 0

    for host in hosts:
        conn_status = (
            (host.get("connectionStatus") or {})
            .get("connectivity", "")
        )
        if not conn_status:
            unknown += 1
        elif conn_status.upper() == "CONNECTED":
            connected += 1
        elif conn_status.upper() == "DISCONNECTED":
            disconnected.append(host)
        else:
            unknown += 1

    if disconnected:
        result.add_warning(
            str(len(disconnected)) +
            " physical host(s) are DISCONNECTED on " +
            cluster_name +
            ". Reconnect before upgrade.",
            {
                "check": "disconnected_hosts",
                "count": len(disconnected),
                "connected": connected,
                "unknown": unknown,
            },
        )

        for host in disconnected:
            os_type = (
                host.get("osType") or "Unknown"
            )
            result.findings.append({
                "severity": "WARNING",
                "check": "disconnected_host_detail",
                "message": (
                    "Host '" +
                    host.get("name", "?") +
                    "' (" + os_type +
                    ") is disconnected"
                ),
                "host_name": host.get("name", ""),
            })

    return {
        "connected": connected,
        "disconnected": len(disconnected),
        "unknown": unknown,
        "total": len(hosts),
    }


def analyze_managed_volumes(result, managed_volumes):
    writable = [
        mv for mv in managed_volumes
        if (mv.get("state") or "").upper() == "WRITABLE"
    ]
    if writable:
        result.add_warning(
            str(len(writable)) +
            " managed volume(s) are in WRITABLE "
            "state. Consider quiescing.",
            {
                "check": "writable_managed_volumes",
                "count": len(writable),
            },
        )


def analyze_sla_coverage(result, workload_name,
                          workloads):
    unprotected = []
    for w in workloads:
        sla = w.get("effectiveSlaDomain") or {}
        sla_name = sla.get("name", "")
        if (not sla_name or
                sla_name.upper() in (
                    "UNPROTECTED", "DO_NOT_PROTECT",
                    "DONOTPROTECT",
                )):
            unprotected.append(w)

    if unprotected and len(unprotected) > 10:
        result.add_info(
            str(len(unprotected)) + " " +
            workload_name +
            " have no SLA assigned.",
            {
                "check": "sla_coverage",
                "workload_type": workload_name,
                "unprotected_count": len(unprotected),
            },
        )


# ==============================================================
# Main Collector Entry Point
# ==============================================================

def collect_workload_inventory(client, cluster):
    result = CollectionResult(
        collector_name="workload_inventory"
    )

    with CollectorTimer(result):
        logger.debug(
            "  [%s] Collecting workload inventory...",
            cluster.name
        )

        all_workloads = []
        try:
            all_workloads = client.graphql_paginated(
                query=WORKLOAD_INVENTORY_QUERY,
                variables={
                    "typeFilter": WORKLOAD_TYPE_FILTERS,
                },
                connection_path=[
                    "inventoryRoot",
                    "descendantConnection",
                ],
                page_size=200,
            )
            logger.debug(
                "  [%s] Total workloads fetched: %d",
                cluster.name, len(all_workloads)
            )
        except Exception as e:
            logger.warning(
                "  [%s] Workload inventory query "
                "failed: %s",
                cluster.name, e
            )
            result.add_warning(
                "Could not retrieve workload "
                "inventory: " + str(e),
                {"check": "workload_fetch_error"},
            )
            return result

        # Filter to this cluster
        cluster_workloads = [
            w for w in all_workloads
            if node_matches_cluster(w, cluster)
        ]

        logger.debug(
            "  [%s] Cluster workloads: %d of %d",
            cluster.name, len(cluster_workloads),
            len(all_workloads)
        )

        # Group by objectType
        inventory = {}
        for w in cluster_workloads:
            otype = w.get("objectType", "Unknown")
            if otype not in inventory:
                inventory[otype] = []
            inventory[otype].append(w)

        # Summary
        total_workloads = len(cluster_workloads)
        summary = {"total_workloads": total_workloads}
        for otype, items in inventory.items():
            summary[otype] = len(items)

        result.summary = summary
        result.raw_data = {"inventory": inventory}

        # Report
        inventory_parts = []
        for otype, items in sorted(
            inventory.items(),
            key=lambda x: len(x[1]),
            reverse=True
        ):
            count = len(items)
            if count > 0:
                label = WORKLOAD_LABELS.get(
                    otype, otype
                )
                inventory_parts.append(
                    str(count) + " " + label
                )

        if inventory_parts:
            result.add_info(
                "Workload inventory for " +
                cluster.name + ": " +
                str(total_workloads) +
                " total -- " +
                ", ".join(inventory_parts),
                {"check":
                 "workload_inventory_summary"},
            )
        else:
            result.add_info(
                "No active workloads found for " +
                cluster.name + ".",
                {"check":
                 "workload_inventory_summary"},
            )

        # Host connectivity
        hosts = inventory.get("PhysicalHost", [])
        if hosts:
            host_stats = analyze_host_connectivity(
                result, hosts, cluster.name
            )
            result.summary[
                "host_connectivity"
            ] = host_stats

        # Managed volumes
        mvs = (
            inventory.get(
                "MANAGED_VOLUME_EXPORT", []
            ) +
            inventory.get("ManagedVolume", [])
        )
        if mvs:
            analyze_managed_volumes(result, mvs)

        # SLA coverage per type
        for otype, items in inventory.items():
            if items:
                label = WORKLOAD_LABELS.get(
                    otype, otype
                )
                analyze_sla_coverage(
                    result, label, items
                )

        logger.debug(
            "  [%s] Workload inventory complete: "
            "%d total, %dB / %dW / %dI",
            cluster.name, total_workloads,
            len(result.blockers),
            len(result.warnings),
            len(result.info_messages)
        )

    return result