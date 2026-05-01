#!/usr/bin/env python3
"""
Collector: CDM Live Mounts
Ported from original working tool [1].

All CDM REST API endpoints use FULL path:
- api/v1/vmware/vm/snapshot/mount [1]
- api/v1/mssql/db/mount [1]
- api/internal/oracle/db/mount [1]
- api/internal/managed_volume/snapshot/export [1]
- api/v1/volume_group/snapshot/mount
- api/v1/fileset/snapshot/mount

RSC GraphQL for managed volume live mounts [1]:
- managedVolumeLiveMounts(first: 200)
"""

import logging
from collectors import CollectionResult, CollectorTimer
from config import Config

logger = logging.getLogger(__name__)


# ==============================================================
# RSC GraphQL — from original tool [1]
# ==============================================================

MV_LIVE_MOUNTS_QUERY = """
{
    managedVolumeLiveMounts(first: 200) {
        count
        edges {
            node {
                id
                name
                numChannels
                logicalUsedSize
                managedVolume {
                    id
                    name
                }
                cluster {
                    id
                    name
                }
            }
        }
    }
}
"""


# ==============================================================
# CDM REST API Mount Endpoints — from original tool [1]
# Full paths including api/v1/ or api/internal/ prefix
# ==============================================================

CDM_MOUNT_ENDPOINTS = [
    {
        "endpoint": "api/v1/vmware/vm/snapshot/mount",
        "label": "VMware VM",
        "data_key": "data",
    },
    {
        "endpoint": "api/v1/mssql/db/mount",
        "label": "MSSQL Database",
        "data_key": "data",
    },
    {
        "endpoint": "api/internal/oracle/db/mount",
        "label": "Oracle Database",
        "data_key": "data",
    },
    {
        "endpoint": "api/internal/managed_volume/snapshot/export",
        "label": "Managed Volume Export",
        "data_key": "data",
    },
    {
        "endpoint": "api/v1/volume_group/snapshot/mount",
        "label": "Volume Group",
        "data_key": "data",
    },
    {
        "endpoint": "api/v1/fileset/snapshot/mount",
        "label": "Fileset",
        "data_key": "data",
    },
]


# ==============================================================
# Cluster matching for RSC queries
# ==============================================================

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
# CDM REST API Mount Checks [1]
# ==============================================================

def check_cdm_mounts(result, client, cluster):
    """
    Check all CDM mount endpoints using full API paths [1].
    """
    total_mounts = 0
    mount_details = []

    for ep_info in CDM_MOUNT_ENDPOINTS:
        endpoint = ep_info["endpoint"]
        label = ep_info["label"]
        data_key = ep_info["data_key"]

        try:
            data = client.cdm_direct_get(
                endpoint,
                cluster_id=cluster.cluster_id,
            )

            if data is None:
                result.add_info(
                    "No active " + label +
                    " live mounts.",
                    {"check": "cdm_live_mounts",
                     "type": label, "count": 0},
                )
                continue

            mounts = []
            if isinstance(data, dict):
                mounts = data.get(data_key, [])
                if not isinstance(mounts, list):
                    mounts = []
            elif isinstance(data, list):
                mounts = data

            if mounts:
                count = len(mounts)
                total_mounts += count
                mount_details.append(
                    str(count) + " " + label
                )

                result.add_blocker(
                    str(count) + " active " + label +
                    " live mount(s). Must be dismounted "
                    "before upgrade.",
                    {"check": "cdm_live_mounts",
                     "type": label,
                     "count": count,
                     "remediation": (
                         "Dismount all " + label +
                         " live mounts via CDM UI "
                         "or API before upgrade."
                     )},
                )

                for mount in mounts:
                    mount_name = (
                        mount.get("mountName") or
                        mount.get("name") or
                        mount.get("sourceDatabaseName") or
                        mount.get("vmName") or
                        mount.get("sourceVolumeGroupName") or
                        mount.get("sourceFilesetName") or
                        mount.get("managedVolumeName") or
                        "Unknown"
                    )
                    host = (
                        mount.get("hostName") or
                        mount.get("targetHostName") or
                        mount.get("targetInstanceName") or
                        ""
                    )
                    created = mount.get("createDate", "")

                    result.findings.append({
                        "severity": "BLOCKER",
                        "check": "live_mount_detail",
                        "message": (
                            label + " mount: '" +
                            mount_name + "'" +
                            (" on " + host
                             if host else "") +
                            (" (created: " + created +
                             ")" if created else "")
                        ),
                        "mount_type": label,
                        "mount_name": mount_name,
                        "host": host,
                    })
            else:
                result.add_info(
                    "No active " + label +
                    " live mounts.",
                    {"check": "cdm_live_mounts",
                     "type": label, "count": 0},
                )

        except Exception as e:
            logger.debug(
                "  [%s] %s mount check failed: %s",
                cluster.name, label, e
            )
            result.add_info(
                "Could not check " + label +
                " live mounts.",
                {"check": "cdm_live_mounts",
                 "type": label},
            )

    return total_mounts, mount_details


# ==============================================================
# RSC GraphQL MV Mount Check [1]
# ==============================================================

def check_rsc_mv_mounts(result, client, cluster):
    """
    Check managed volume live mounts via RSC GraphQL [1].
    Uses managedVolumeLiveMounts query.
    """
    try:
        data = client.graphql(MV_LIVE_MOUNTS_QUERY)
        conn = (
            data.get("managedVolumeLiveMounts", {}) or {}
        )
        edges = conn.get("edges", []) or []

        cluster_mounts = []
        for edge in edges:
            node = edge.get("node", {}) or {}
            if node_matches_cluster(node, cluster):
                cluster_mounts.append(node)

        if cluster_mounts:
            mv_count = len(cluster_mounts)
            result.summary["rsc_mv_mounts"] = mv_count

            for mount in cluster_mounts:
                mv_info = (
                    mount.get("managedVolume", {}) or {}
                )
                mv_name = mv_info.get("name", "Unknown")
                channels = mount.get("numChannels", 0)
                used = mount.get(
                    "logicalUsedSize", 0
                ) or 0
                used_gb = (
                    round(used / (1024**3), 2)
                    if used else 0
                )

                result.findings.append({
                    "severity": "BLOCKER",
                    "check": "rsc_mv_mount_detail",
                    "message": (
                        "MV live mount: '" + mv_name +
                        "' (" + str(channels) +
                        " channel(s), " +
                        str(used_gb) + " GB used)"
                    ),
                    "mv_name": mv_name,
                    "channels": channels,
                })

            result.add_blocker(
                str(mv_count) +
                " managed volume live mount(s) "
                "detected via RSC. Remove "
                "before upgrade.",
                {"check": "rsc_mv_mounts",
                 "count": mv_count},
            )

            return mv_count
        else:
            return 0

    except Exception as e:
        logger.debug(
            "  [%s] RSC MV mount check failed: %s",
            cluster.name, e
        )
        return 0


# ==============================================================
# Main Collector Entry Point
# ==============================================================

def collect_live_mounts(client, cluster):
    """
    Check all live mount types.
    CDM REST API for most types [1],
    RSC GraphQL for managed volume mounts.
    """
    result = CollectionResult(
        collector_name="cdm_live_mounts"
    )

    with CollectorTimer(result):
        logger.debug(
            "  [%s] Checking for active live mounts...",
            cluster.name
        )

        cdm_available = client.is_cdm_available(
            cluster.cluster_id
        )

        total_mounts = 0
        mount_details = []

        if cdm_available:
            cdm_count, cdm_details = check_cdm_mounts(
                result, client, cluster
            )
            total_mounts += cdm_count
            mount_details.extend(cdm_details)
        else:
            result.add_info(
                "CDM direct API not available for " +
                cluster.name +
                ". Live mount check limited to "
                "RSC GraphQL.",
                {"check": "cdm_live_mounts_source"},
            )

        rsc_mv_count = check_rsc_mv_mounts(
            result, client, cluster
        )
        if rsc_mv_count > 0:
            total_mounts += rsc_mv_count
            mount_details.append(
                str(rsc_mv_count) + " MV (RSC)"
            )

        result.summary["total_mounts"] = total_mounts
        result.summary["cdm_available"] = cdm_available
        result.summary["mount_details"] = mount_details

        if total_mounts > 0:
            detail_str = ", ".join(mount_details)
            logger.warning(
                "  [%s] %d active mount(s): %s",
                cluster.name, total_mounts, detail_str
            )

        logger.debug(
            "  [%s] Live mount check complete: "
            "%dB / %dW / %dI",
            cluster.name,
            len(result.blockers),
            len(result.warnings),
            len(result.info_messages)
        )

    return result