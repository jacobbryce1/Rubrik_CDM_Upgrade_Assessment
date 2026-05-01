#!/usr/bin/env python3
"""
Collector: SLA Compliance & Configuration
Ported from original working tool [1].

Uses slaDomains query with inline fragments for
ClusterSlaDomain and GlobalSlaReply — the proven
pattern that works against this RSC instance.

Assessment results [2] confirm this pattern successfully
collects SLA data including retention lock status,
archival targets, and replication configuration.
"""

import logging
from collectors import CollectionResult, CollectorTimer
from config import Config

logger = logging.getLogger(__name__)


# ==============================================================
# GraphQL Queries — from original working tool [1]
# ==============================================================

# slaDomains query with inline fragments [1]
# This exact pattern works — DO NOT change to slaDomainConnection
SLA_DOMAINS_QUERY = """
{
    slaDomains(first: 200) {
        edges {
            node {
                id
                name
                ... on ClusterSlaDomain {
                    protectedObjectCount
                    isRetentionLockedSla
                    baseFrequency {
                        duration
                        unit
                    }
                    archivalSpec {
                        archivalLocationName
                        threshold
                        thresholdUnit
                    }
                    replicationSpecsV2 {
                        cluster {
                            name
                        }
                        retentionDuration {
                            duration
                            unit
                        }
                    }
                    cluster {
                        id
                        name
                    }
                }
                ... on GlobalSlaReply {
                    description
                    objectTypes
                    protectedObjectCount
                    isRetentionLockedSla
                    isDefault
                    baseFrequency {
                        duration
                        unit
                    }
                    archivalSpecs {
                        storageSetting {
                            name
                        }
                        threshold
                        thresholdUnit
                    }
                    replicationSpecsV2 {
                        cluster {
                            name
                        }
                        retentionDuration {
                            duration
                            unit
                        }
                    }
                }
            }
        }
    }
}
"""


# ==============================================================
# Cluster matching — from original tool [1]
# ==============================================================

def node_matches_cluster(sla_node, cluster):
    """Check if a cluster SLA belongs to the target cluster."""
    sla_cluster = sla_node.get("cluster") or {}
    sla_cluster_id = sla_cluster.get("id", "")
    sla_cluster_name = sla_cluster.get("name", "")

    if sla_cluster_id and sla_cluster_id == cluster.cluster_id:
        return True

    if sla_cluster_name and cluster.name:
        if sla_cluster_name.lower() == cluster.name.lower():
            return True

    if sla_cluster_id and cluster.cluster_id:
        if (cluster.cluster_id in sla_cluster_id or
                sla_cluster_id in cluster.cluster_id):
            return True

    return False


def is_global_sla(node):
    """Global SLAs have a description field [1]."""
    return "description" in node


# ==============================================================
# Analysis Functions — from original tool [1]
# ==============================================================

def analyze_sla_policies(result, cluster, sla_domains):
    """Analyze SLA policies for upgrade concerns [1]."""
    if not sla_domains:
        result.add_info(
            "No SLA domains found for cluster " +
            cluster.name + ".",
            {"check": "sla_policy_count"},
        )
        return

    total_slas = len(sla_domains)
    global_slas = [
        s for s in sla_domains if is_global_sla(s)
    ]
    local_slas = [
        s for s in sla_domains if not is_global_sla(s)
    ]
    locked_slas = [
        s for s in sla_domains
        if s.get("isRetentionLockedSla", False)
    ]

    total_protected = sum(
        s.get("protectedObjectCount", 0) or 0
        for s in sla_domains
    )

    result.add_info(
        "SLA summary for " + cluster.name + ": " +
        str(total_slas) + " SLA domains (" +
        str(len(global_slas)) + " global, " +
        str(len(local_slas)) + " local), " +
        str(total_protected) + " protected objects, " +
        str(len(locked_slas)) + " retention-locked.",
        {
            "check": "sla_summary",
            "total_slas": total_slas,
            "global_slas": len(global_slas),
            "local_slas": len(local_slas),
            "locked_slas": len(locked_slas),
            "total_protected": total_protected,
        },
    )

    # Archival configured SLAs
    slas_with_archival = []
    for s in sla_domains:
        if s.get("archivalSpec") or s.get("archivalSpecs"):
            slas_with_archival.append(s)

    if slas_with_archival:
        result.add_info(
            str(len(slas_with_archival)) +
            " SLA(s) have archival configured. "
            "Verify archival targets are accessible "
            "post-upgrade.",
            {"check": "sla_archival_count",
             "count": len(slas_with_archival)},
        )

    # Replication configured SLAs
    slas_with_replication = []
    for s in sla_domains:
        repl = s.get("replicationSpecsV2") or []
        if repl:
            slas_with_replication.append(s)

    if slas_with_replication:
        result.add_info(
            str(len(slas_with_replication)) +
            " SLA(s) have replication configured. "
            "Verify replication targets are accessible "
            "and version-compatible post-upgrade.",
            {"check": "sla_replication_count",
             "count": len(slas_with_replication)},
        )

    # Retention lock — warning for compliance [1]
    if locked_slas:
        sla_names = [
            s.get("name", "?") for s in locked_slas[:10]
        ]
        more = ""
        if len(locked_slas) > 10:
            more = "..."
        result.add_warning(
            str(len(locked_slas)) +
            " SLA(s) have retention lock enabled. "
            "Verify retention lock compliance is "
            "maintained through upgrade. SLA names: " +
            ", ".join(sla_names) + more,
            {
                "check": "retention_lock",
                "count": len(locked_slas),
                "sla_names": [
                    s.get("name", "?")
                    for s in locked_slas
                ],
            },
        )

    # High frequency SLAs [1]
    high_freq_slas = []
    for sla in sla_domains:
        freq = sla.get("baseFrequency") or {}
        duration = freq.get("duration", 0) or 0
        unit = (freq.get("unit") or "").upper()
        if unit == "MINUTES" and 0 < duration < 60:
            high_freq_slas.append(sla)
        elif unit == "HOURS" and 0 < duration < 1:
            high_freq_slas.append(sla)

    if high_freq_slas:
        result.add_warning(
            str(len(high_freq_slas)) +
            " SLA(s) have sub-hourly snapshot "
            "frequency. During upgrade, snapshots "
            "may be delayed or missed.",
            {"check": "high_frequency_slas",
             "count": len(high_freq_slas)},
        )


def analyze_replication_from_slas(result, cluster,
                                    sla_domains):
    """Extract replication targets from SLAs [1]."""
    repl_targets = set()
    for sla in sla_domains:
        repl_specs = sla.get("replicationSpecsV2") or []
        for spec in repl_specs:
            target_cluster = spec.get("cluster") or {}
            target_name = target_cluster.get("name", "")
            if target_name:
                repl_targets.add(target_name)

    if repl_targets:
        result.add_info(
            "Replication targets in SLA policies for " +
            cluster.name + ": " +
            ", ".join(sorted(repl_targets)) + ".",
            {"check": "sla_replication_targets",
             "targets": sorted(repl_targets)},
        )
    else:
        result.add_info(
            "No replication targets configured in "
            "SLA policies for " + cluster.name + ".",
            {"check": "sla_replication_targets"},
        )

    return repl_targets


def analyze_archival_from_slas(result, cluster,
                                 sla_domains):
    """Extract archival targets from SLAs [1]."""
    archival_targets = set()
    for sla in sla_domains:
        # ClusterSlaDomain uses archivalSpec (singular) [1]
        arch_spec = sla.get("archivalSpec")
        if arch_spec:
            loc_name = arch_spec.get(
                "archivalLocationName", ""
            )
            if loc_name:
                archival_targets.add(loc_name)

        # GlobalSlaReply uses archivalSpecs (plural) [1]
        arch_specs = sla.get("archivalSpecs") or []
        for spec in arch_specs:
            storage = spec.get("storageSetting") or {}
            loc_name = storage.get("name", "")
            if loc_name:
                archival_targets.add(loc_name)

    if archival_targets:
        result.add_info(
            "Archival targets in SLA policies for " +
            cluster.name + ": " +
            ", ".join(sorted(archival_targets)) + ".",
            {"check": "sla_archival_targets",
             "targets": sorted(archival_targets)},
        )
    else:
        result.add_info(
            "No archival targets configured in "
            "SLA policies for " + cluster.name + ".",
            {"check": "sla_archival_targets"},
        )

    return archival_targets


def analyze_global_sla_dependencies(result, cluster,
                                       global_slas):
    """Check if global SLAs reference this cluster [1]."""
    if not global_slas:
        return

    global_with_repl = []
    for sla in global_slas:
        repl = sla.get("replicationSpecsV2") or []
        for spec in repl:
            target = spec.get("cluster") or {}
            target_name = target.get("name", "")
            if (target_name and
                    target_name.lower() ==
                    cluster.name.lower()):
                global_with_repl.append(sla)
                break

    if global_with_repl:
        result.add_warning(
            str(len(global_with_repl)) +
            " global SLA(s) reference " +
            cluster.name +
            " as a replication target. "
            "If upgrading this cluster, ensure "
            "source clusters remain compatible.",
            {
                "check": "global_sla_dependency",
                "count": len(global_with_repl),
                "sla_names": [
                    s.get("name", "?")
                    for s in global_with_repl[:10]
                ],
            },
        )


# ==============================================================
# Main Collector Entry Point
# ==============================================================

def collect_sla_compliance(client, cluster):
    """
    Collect and analyze SLA policies using the proven
    slaDomains query from the original tool [1].
    """
    result = CollectionResult(
        collector_name="sla_compliance"
    )

    with CollectorTimer(result):
        logger.debug(
            "  [%s] Collecting SLA compliance data...",
            cluster.name
        )

        # Fetch all SLA domains using proven query [1]
        all_sla_domains = []
        try:
            data = client.graphql(SLA_DOMAINS_QUERY)
            conn = data.get("slaDomains", {}) or {}
            edges = conn.get("edges", []) or []

            for edge in edges:
                node = edge.get("node", {}) or {}
                if node:
                    all_sla_domains.append(node)

            logger.debug(
                "  [%s] Fetched %d total SLA domains",
                cluster.name, len(all_sla_domains)
            )
        except Exception as e:
            logger.warning(
                "  [%s] Failed to fetch SLA domains: %s",
                cluster.name, e
            )
            result.add_warning(
                "Could not retrieve SLA domains: " +
                str(e),
                {"check": "sla_fetch_error"},
            )

        # Separate cluster SLAs vs global SLAs [1]
        cluster_slas = []
        global_slas = []
        for sla in all_sla_domains:
            if is_global_sla(sla):
                global_slas.append(sla)
            elif node_matches_cluster(sla, cluster):
                cluster_slas.append(sla)

        # Combine for analysis [1]
        relevant_slas = cluster_slas + global_slas

        logger.debug(
            "  [%s] SLA breakdown: %d cluster, "
            "%d global, %d total relevant",
            cluster.name, len(cluster_slas),
            len(global_slas), len(relevant_slas)
        )

        # Store raw data
        result.raw_data = {
            "all_sla_domains": all_sla_domains,
            "cluster_slas": cluster_slas,
            "global_slas": global_slas,
        }

        # Run analyses [1]
        analyze_sla_policies(
            result, cluster, relevant_slas
        )
        repl_targets = analyze_replication_from_slas(
            result, cluster, relevant_slas
        )
        archival_targets = analyze_archival_from_slas(
            result, cluster, relevant_slas
        )
        analyze_global_sla_dependencies(
            result, cluster, global_slas
        )

        # Build summary
        result.summary = {
            "total_sla_domains": len(relevant_slas),
            "cluster_slas": len(cluster_slas),
            "global_slas": len(global_slas),
            "slas_with_archival": len([
                s for s in relevant_slas
                if s.get("archivalSpec") or
                s.get("archivalSpecs")
            ]),
            "slas_with_replication": len([
                s for s in relevant_slas
                if s.get("replicationSpecsV2")
            ]),
            "retention_locked": len([
                s for s in relevant_slas
                if s.get("isRetentionLockedSla")
            ]),
            "replication_targets": sorted(repl_targets),
            "archival_targets": sorted(archival_targets),
        }

        logger.debug(
            "  [%s] SLA compliance complete: "
            "%dB / %dW / %dI",
            cluster.name,
            len(result.blockers),
            len(result.warnings),
            len(result.info_messages)
        )

    return result