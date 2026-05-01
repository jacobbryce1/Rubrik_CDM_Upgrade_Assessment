#!/usr/bin/env python3
"""
Cluster Discovery — ported from original working tool [1].
Discovers ALL clusters from RSC without type filtering.
The original tool discovered 10 clusters including
OnPrem, Cloud, and Robo types [1].
Removing the type filter ensures we find all of them.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict

from config import Config

logger = logging.getLogger("cluster_discovery")


@dataclass
class DiscoveredCluster:
    cluster_id: str = ""
    name: str = ""
    version: str = ""
    status: str = ""
    connected_state: str = ""
    cluster_type: str = ""
    node_count: int = 0
    node_ips: List[str] = field(default_factory=list)
    location: str = ""
    total_capacity: float = 0.0
    used_capacity: float = 0.0
    available_capacity: float = 0.0
    snapshot_capacity: float = 0.0
    last_connection_time: str = ""
    encryption_enabled: bool = False
    product_type: str = ""

    should_assess: bool = True
    skip_reason: str = ""

    upgrade_info: Dict = field(default_factory=dict)
    raw_data: Dict = field(default_factory=dict)


# ==============================================================
# Cluster Discovery Query — no type filter
# Discovers ALL clusters visible to the service account
# ==============================================================

CLUSTER_DISCOVERY_QUERY = """
query AllClusters($first: Int, $after: String) {
    clusterConnection(
        first: $first
        after: $after
    ) {
        edges {
            node {
                id
                name
                version
                status
                type
                state {
                    connectedState
                }
                geoLocation {
                    address
                }
                lastConnectionTime
                encryptionEnabled
                productType
                clusterNodeConnection {
                    count
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
"""

CLUSTER_NODES_QUERY = """
query ClusterNodes($id: UUID!) {
    cluster(clusterUuid: $id) {
        clusterNodeConnection {
            nodes {
                id
                ipAddress
                status
            }
        }
    }
}
"""

CLUSTER_METRICS_QUERY = """
query ClusterMetrics($id: UUID!) {
    cluster(clusterUuid: $id) {
        metric {
            totalCapacity
            usedCapacity
            availableCapacity
            snapshotCapacity
        }
    }
}
"""

CLUSTER_UPGRADE_QUERY = """
query ClusterUpgrade($id: UUID!) {
    cluster(clusterUuid: $id) {
        cdmUpgradeInfo {
            downloadedVersion
        }
    }
}
"""


def discover_all_clusters(client):
    logger.info("Discovering clusters from RSC...")

    raw_nodes = client.graphql_paginated(
        query=CLUSTER_DISCOVERY_QUERY,
        connection_path=["clusterConnection"],
        page_size=200,
    )

    if not raw_nodes:
        logger.error("No clusters found in RSC")
        return []

    # Filter out non-CDM clusters (Polaris, ExoCompute, etc.)
    # but keep OnPrem, Cloud, Robo, and Unknown types
    # which are all CDM cluster variants
    skip_types = {"Polaris", "ExoCompute"}

    clusters = []
    skipped_types = {}
    for node in raw_nodes:
        cluster_type = node.get("type", "")

        # Skip non-CDM cluster types
        if cluster_type in skip_types:
            skipped_types[cluster_type] = (
                skipped_types.get(cluster_type, 0) + 1
            )
            continue

        # Skip clusters without a version (not real CDM)
        version = node.get("version", "")
        if not version:
            skipped_types["NoVersion"] = (
                skipped_types.get("NoVersion", 0) + 1
            )
            continue

        c = DiscoveredCluster(
            cluster_id=node.get("id", ""),
            name=node.get("name", ""),
            version=version,
            status=node.get("status", ""),
            connected_state=(
                (node.get("state") or {})
                .get("connectedState", "")
            ),
            cluster_type=cluster_type,
            node_count=(
                (node.get("clusterNodeConnection") or {})
                .get("count", 0)
            ),
            location=(
                (node.get("geoLocation") or {})
                .get("address", "")
            ),
            last_connection_time=node.get(
                "lastConnectionTime", ""
            ),
            encryption_enabled=node.get(
                "encryptionEnabled", False
            ),
            product_type=node.get("productType", ""),
            raw_data=node,
        )
        clusters.append(c)

    logger.info(
        "  Discovered %d CDM cluster(s) "
        "(total in RSC: %d)",
        len(clusters), len(raw_nodes)
    )
    if skipped_types:
        for stype, count in skipped_types.items():
            logger.debug(
                "  Skipped %d %s cluster(s)",
                count, stype
            )

    return clusters


def enrich_cluster(client, cluster):
    # Fetch node IPs
    try:
        data = client.graphql(
            CLUSTER_NODES_QUERY,
            {"id": cluster.cluster_id}
        )
        nodes = (
            (data.get("cluster") or {})
            .get("clusterNodeConnection", {})
            .get("nodes", [])
        )
        ips = [
            n["ipAddress"]
            for n in nodes
            if n.get("ipAddress")
        ]
        cluster.node_ips = ips
        cluster.node_count = (
            len(nodes) if nodes else cluster.node_count
        )
    except Exception as e:
        logger.debug(
            "  Node enrichment failed for %s: %s",
            cluster.name, e
        )

    # Fetch capacity metrics
    try:
        data = client.graphql(
            CLUSTER_METRICS_QUERY,
            {"id": cluster.cluster_id}
        )
        metric = (
            (data.get("cluster") or {})
            .get("metric") or {}
        )
        cluster.total_capacity = metric.get(
            "totalCapacity", 0
        )
        cluster.used_capacity = metric.get(
            "usedCapacity", 0
        )
        cluster.available_capacity = metric.get(
            "availableCapacity", 0
        )
        cluster.snapshot_capacity = metric.get(
            "snapshotCapacity", 0
        )
    except Exception as e:
        logger.debug(
            "  Metrics enrichment failed for %s: %s",
            cluster.name, e
        )

    # Fetch upgrade info
    try:
        data = client.graphql(
            CLUSTER_UPGRADE_QUERY,
            {"id": cluster.cluster_id}
        )
        info = (
            (data.get("cluster") or {})
            .get("cdmUpgradeInfo") or {}
        )
        cluster.upgrade_info = info
    except Exception as e:
        logger.debug(
            "  Upgrade enrichment failed for %s: %s",
            cluster.name, e
        )

    # Set up CDM direct API
    if cluster.node_ips and Config.CDM_DIRECT_ENABLED:
        client.set_target_cluster(
            cluster.cluster_id,
            node_ips=cluster.node_ips,
            name=cluster.name,
            version=cluster.version,
        )
        cdm_ok = client.connect_cdm_direct(
            cluster.cluster_id
        )
        if cdm_ok:
            logger.info(
                "  CDM direct authenticated: %s",
                cluster.name
            )
        else:
            logger.debug(
                "  CDM direct not available: %s",
                cluster.name
            )

    return cluster


def filter_clusters(clusters):
    to_assess = []
    skipped = []

    for cluster in clusters:
        if Config.INCLUDE_CLUSTERS:
            if (cluster.name not in
                    Config.INCLUDE_CLUSTERS and
                    cluster.cluster_id not in
                    Config.INCLUDE_CLUSTERS):
                cluster.should_assess = False
                cluster.skip_reason = (
                    "Not in INCLUDE_CLUSTERS"
                )
                skipped.append(cluster)
                continue

        if Config.EXCLUDE_CLUSTERS:
            if (cluster.name in
                    Config.EXCLUDE_CLUSTERS or
                    cluster.cluster_id in
                    Config.EXCLUDE_CLUSTERS):
                cluster.should_assess = False
                cluster.skip_reason = (
                    "In EXCLUDE_CLUSTERS"
                )
                skipped.append(cluster)
                continue

        if Config.SKIP_DISCONNECTED:
            if (cluster.connected_state and
                    cluster.connected_state.upper() ==
                    "DISCONNECTED"):
                cluster.should_assess = False
                cluster.skip_reason = "Disconnected"
                skipped.append(cluster)
                continue

        to_assess.append(cluster)

    logger.info(
        "  Filtered: %d to assess, %d skipped",
        len(to_assess), len(skipped)
    )
    for s in skipped:
        logger.info(
            "    Skipped: %s -- %s",
            s.name, s.skip_reason
        )

    return to_assess, skipped