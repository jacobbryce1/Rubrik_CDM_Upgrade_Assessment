#!/usr/bin/env python3
"""
Collector: Upgrade Pre-Checks & Compatibility
Ported from original working tool [1].

Uses:
- Static cdm_eos_data.json for EOS dates and upgrade paths [1]
- RSC GraphQL for cluster health / connectivity checks [1]
- Proven query patterns from original tool

Does NOT use CdmUpgradeInfo fields that don't exist:
- installedVersion, upgradeAvailable, upgradeRecommended,
  availableVersions, currentStateInfo, versionSupportInfo
"""

import json
import logging
from pathlib import Path
from collectors import CollectionResult, CollectorTimer
from config import Config

logger = logging.getLogger(__name__)

COMPAT_MATRIX_URL = (
    "https://docs.rubrik.com/en-us/saas/cdm/"
    "compatibility-matrix.html"
)


# ==============================================================
# Version Utilities — from original tool [1]
# ==============================================================

def parse_version_tuple(version_str):
    if not version_str:
        return (0, 0, 0, 0)
    clean = str(version_str).strip().lstrip("v").lstrip("V")
    patch_num = 0
    if "-p" in clean:
        parts = clean.split("-p")
        clean = parts[0]
        try:
            patch_num = int(parts[1])
        except (ValueError, IndexError):
            patch_num = 0
    elif "-" in clean:
        clean = clean.split("-")[0]

    segments = clean.split(".")
    result = []
    for s in segments:
        try:
            result.append(int(s))
        except ValueError:
            result.append(0)
    while len(result) < 3:
        result.append(0)
    result.append(patch_num)
    return tuple(result)


def version_to_major_minor(version_str):
    t = parse_version_tuple(version_str)
    return str(t[0]) + "." + str(t[1])


def version_gte(v1, v2):
    return parse_version_tuple(v1) >= parse_version_tuple(v2)


def version_lt(v1, v2):
    return parse_version_tuple(v1) < parse_version_tuple(v2)


def version_in_range(version, min_ver, max_ver):
    t = parse_version_tuple(version)
    return (
        parse_version_tuple(min_ver) <= t <=
        parse_version_tuple(max_ver)
    )


# ==============================================================
# Static EOS Data Loader — from original tool [1]
# ==============================================================

def load_eos_data():
    eos_file = Path(__file__).parent.parent / "cdm_eos_data.json"
    if eos_file.exists():
        try:
            with open(eos_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.debug(
                "Loaded EOS data: %d versions",
                len(data.get("eos_dates", {}))
            )
            return data
        except Exception as e:
            logger.warning("Failed to load EOS data: %s", e)
    else:
        logger.warning("EOS data file not found: %s", eos_file)
    return {"eos_dates": {}, "upgrade_paths": {}}


# ==============================================================
# RSC Cluster Health Query — from original tool [1]
# Uses passesConnectivityCheck which is proven to work
# ==============================================================

RSC_HEALTH_QUERY = """
query RSCHealth($id: UUID!) {
    cluster(clusterUuid: $id) {
        passesConnectivityCheck
        lastConnectionTime
    }
}
"""

# Cluster basic info — from original tool [1]
CLUSTER_BASIC_QUERY = """
query ClusterBasic($id: UUID!) {
    cluster(clusterUuid: $id) {
        id
        name
        version
        status
        type
        defaultAddress
        lastConnectionTime
        registrationTime
        passesConnectivityCheck
        snapshotCount
        encryptionEnabled
        estimatedRunway
        productType
        timezone
    }
}
"""


# ==============================================================
# RSC Data Fetcher
# ==============================================================

def fetch_rsc_cluster_info(client, cluster):
    """
    Fetch cluster health info from RSC using proven
    queries from the original tool [1].
    """
    info = {}

    # Basic cluster info [1]
    try:
        data = client.graphql(
            CLUSTER_BASIC_QUERY,
            {"id": cluster.cluster_id}
        )
        info["cluster"] = data.get("cluster") or {}
    except Exception as e:
        logger.debug(
            "  [%s] Basic cluster query failed: %s",
            cluster.name, e
        )

    # RSC health check [1]
    try:
        data = client.graphql(
            RSC_HEALTH_QUERY,
            {"id": cluster.cluster_id}
        )
        health = data.get("cluster") or {}
        info["passes_connectivity"] = health.get(
            "passesConnectivityCheck"
        )
        info["last_connection"] = health.get(
            "lastConnectionTime", ""
        )
    except Exception as e:
        logger.debug(
            "  [%s] RSC health query failed: %s",
            cluster.name, e
        )

    # Upgrade info — only downloadedVersion is valid
    try:
        data = client.graphql(
            "query CU($id: UUID!) {"
            " cluster(clusterUuid: $id) {"
            "  cdmUpgradeInfo { downloadedVersion }"
            " } }",
            {"id": cluster.cluster_id}
        )
        upgrade = (
            (data.get("cluster") or {})
            .get("cdmUpgradeInfo") or {}
        )
        info["downloaded_version"] = upgrade.get(
            "downloadedVersion", ""
        )
    except Exception as e:
        logger.debug(
            "  [%s] Upgrade info query failed: %s",
            cluster.name, e
        )

    return info


# ==============================================================
# Individual Checks
# ==============================================================

def check_eos_status(result, cluster, eos_data):
    current = cluster.version
    major_minor = version_to_major_minor(current)

    eos_dates = eos_data.get("eos_dates", {})
    eos_entry = eos_dates.get(major_minor, {})

    if not eos_entry:
        result.add_info(
            "CDM " + current + " (major: " + major_minor +
            ") -- EOS status not found in static data. "
            "Verify manually.",
            {"check": "eos_status"},
        )
        return

    status = eos_entry.get("status", "")
    eos_date_str = eos_entry.get("eos_date", "")

    if status == "NOT_SUPPORTED":
        result.add_blocker(
            "CDM " + current + " is END OF SUPPORT "
            "(EOS date: " + eos_date_str + "). "
            "Upgrade is mandatory.",
            {"check": "eos_status",
             "eos_date": eos_date_str},
        )
    elif status == "APPROACHING_EOS":
        result.add_warning(
            "CDM " + current +
            " is approaching End of Support "
            "(EOS date: " + eos_date_str +
            "). Plan upgrade soon.",
            {"check": "eos_status",
             "eos_date": eos_date_str},
        )
    elif status == "CURRENT":
        result.add_info(
            "CDM " + current + " is currently supported "
            "(EOS date: " + eos_date_str + ").",
            {"check": "eos_status",
             "eos_date": eos_date_str},
        )
    else:
        result.add_info(
            "CDM " + current + " support status: " +
            status + " (EOS date: " + eos_date_str + ").",
            {"check": "eos_status"},
        )


def check_upgrade_path(result, cluster, target_version,
                        eos_data, rsc_info):
    current = cluster.version
    current_mm = version_to_major_minor(current)
    target_mm = version_to_major_minor(target_version)

    if version_gte(current, target_version):
        result.add_info(
            "CDM " + current + " is already at or beyond "
            "target " + target_version +
            ". No upgrade needed.",
            {"check": "upgrade_path"},
        )
        return

    # Check if target is already downloaded
    downloaded = rsc_info.get("downloaded_version", "")
    if downloaded:
        if downloaded == target_version:
            result.add_info(
                "Target " + target_version +
                " is already downloaded on " +
                cluster.name + ".",
                {"check": "upgrade_path",
                 "downloaded": downloaded},
            )
        else:
            result.add_info(
                "Downloaded version on " + cluster.name +
                ": " + downloaded +
                " (target: " + target_version + ").",
                {"check": "upgrade_path",
                 "downloaded": downloaded},
            )

    # Static upgrade path data
    upgrade_paths = eos_data.get("upgrade_paths", {})
    path_entry = upgrade_paths.get(current_mm, {})

    if not path_entry:
        result.add_warning(
            "No upgrade path data found for CDM " +
            current_mm + ". Verify upgrade path "
            "manually at " + COMPAT_MATRIX_URL,
            {"check": "upgrade_path"},
        )
        return

    direct_targets = path_entry.get(
        "direct_upgrade_to", []
    )
    if (target_mm in direct_targets or
            target_version in direct_targets):
        result.add_info(
            "Direct upgrade from " + current + " to " +
            target_version +
            " appears supported (static data).",
            {"check": "upgrade_path"},
        )
    else:
        intermediate = path_entry.get(
            "recommended_intermediate", ""
        )
        if intermediate:
            result.add_blocker(
                "Direct upgrade from " + current +
                " to " + target_version +
                " is NOT supported. "
                "Intermediate upgrade to " +
                intermediate + " required first.",
                {"check": "upgrade_path",
                 "intermediate": intermediate},
            )
        else:
            targets_str = (
                ", ".join(direct_targets)
                if direct_targets else "none found"
            )
            result.add_warning(
                "Direct upgrade from " + current +
                " to " + target_version +
                " may not be supported. "
                "Direct targets for " + current_mm +
                ": " + targets_str +
                ". Verify at " + COMPAT_MATRIX_URL,
                {"check": "upgrade_path"},
            )


def check_version_specific_risks(result, cluster,
                                   target_version):
    target = target_version
    current = cluster.version

    if version_gte(target, "9.5.1"):
        result.add_warning(
            "CDM 9.5.1+ removes legacy API token support. "
            "MANUAL CHECK: Verify no scripts use "
            "CDM local API tokens.",
            {"check": "api_token_deprecation"},
        )
        result.add_warning(
            "CDM 9.5.1+ changes service account behavior. "
            "MANUAL CHECK: Verify CDM local service "
            "accounts are not relied upon for automation.",
            {"check": "service_account_changes"},
        )

    if version_gte(target, "9.5.0"):
        cluster_type = (
            cluster.cluster_type or ""
        ).upper()
        if "CLOUD" in cluster_type or "AZURE" in cluster_type:
            result.add_warning(
                "CDM 9.5+ requires Azure SSD v2 disk type "
                "for cloud clusters.",
                {"check": "cloud_disk_type"},
            )

    if version_in_range(target, "9.4.0", "9.4.99"):
        result.add_warning(
            "CDM 9.4.x has known Nutanix AHV regressions.",
            {"check": "nutanix_ahv_regression"},
        )

    if version_in_range(target, "9.4.1", "9.4.2"):
        result.add_warning(
            "CDM 9.4.1/9.4.2 has known Oracle RAC "
            "ORA-01882 timezone issue.",
            {"check": "oracle_rac_timezone"},
        )

    if target.startswith("9.4.3"):
        result.add_warning(
            "CDM 9.4.3 has a known issue with Active "
            "Directory backups potentially hanging.",
            {"check": "ad_backup_hang"},
        )

    if version_gte(target, "9.4.1"):
        result.add_info(
            "CDM 9.4.1+ changed AWS S3 archival behavior.",
            {"check": "aws_s3_archival"},
        )

    if version_gte(target, "9.4.0"):
        result.add_info(
            "CDM 9.4+ changes NAS relic fileset visibility.",
            {"check": "nas_relic_visibility"},
        )

    # Version jump warnings
    current_major = parse_version_tuple(current)[0]
    target_major = parse_version_tuple(target)[0]
    current_minor = parse_version_tuple(current)[1]
    target_minor = parse_version_tuple(target)[1]

    if target_major > current_major:
        result.add_warning(
            "Major version jump: " + current +
            " -> " + target,
            {"check": "major_version_jump"},
        )
    elif target_minor - current_minor >= 3:
        result.add_warning(
            "Large minor version jump: " + current +
            " -> " + target + " (spanning " +
            str(target_minor - current_minor) +
            " minor versions).",
            {"check": "large_version_jump"},
        )


def check_rsc_connectivity(result, cluster, rsc_info):
    """
    Check RSC connectivity using passesConnectivityCheck
    from the original tool's proven query [1].
    """
    passes = rsc_info.get("passes_connectivity")
    last_conn = rsc_info.get("last_connection", "")

    if passes is True:
        result.add_info(
            "Cluster " + cluster.name +
            " passes RSC connectivity check.",
            {"check": "rsc_connectivity"},
        )
    elif passes is False:
        result.add_warning(
            "Cluster " + cluster.name +
            " FAILS RSC connectivity check. "
            "Verify connectivity before upgrade.",
            {"check": "rsc_connectivity"},
        )
    else:
        # Fall back to connected_state from discovery
        state = (
            cluster.connected_state or ""
        ).upper()
        if state == "CONNECTED":
            result.add_info(
                "Cluster " + cluster.name +
                " is connected to RSC.",
                {"check": "rsc_connectivity"},
            )
        elif state == "DISCONNECTED":
            result.add_blocker(
                "Cluster " + cluster.name +
                " is DISCONNECTED from RSC.",
                {"check": "rsc_connectivity"},
            )
        else:
            result.add_warning(
                "Cluster " + cluster.name +
                " RSC connection state unknown. "
                "Verify connectivity before upgrade.",
                {"check": "rsc_connectivity"},
            )


def check_cluster_health(result, cluster, rsc_info):
    """Check cluster health from RSC data [1]."""
    cluster_data = rsc_info.get("cluster", {})
    status = (
        cluster_data.get("status") or
        cluster.status or ""
    ).upper()

    if status in ("OK", "CONNECTED"):
        result.add_info(
            "Cluster status: " + status,
            {"check": "cluster_health"},
        )
    elif status in ("DEGRADED", "WARNING"):
        result.add_warning(
            "Cluster status is " + status + ". "
            "Investigate before upgrade.",
            {"check": "cluster_health"},
        )
    elif status in ("ERROR", "CRITICAL", "FATAL"):
        result.add_blocker(
            "Cluster status is " + status + ". "
            "Cluster must be healthy before upgrade.",
            {"check": "cluster_health"},
        )
    elif status:
        result.add_info(
            "Cluster status: " + status,
            {"check": "cluster_health"},
        )

    # Estimated runway [1]
    runway = cluster_data.get("estimatedRunway")
    if runway is not None and runway >= 0:
        if runway < 30:
            result.add_warning(
                "Estimated storage runway: " +
                str(runway) + " days. "
                "Consider adding capacity.",
                {"check": "storage_runway",
                 "days": runway},
            )
        else:
            result.add_info(
                "Estimated storage runway: " +
                str(runway) + " days.",
                {"check": "storage_runway",
                 "days": runway},
            )


def check_capacity(result, cluster):
    if cluster.total_capacity <= 0:
        return

    used_pct = 0.0
    if cluster.total_capacity > 0:
        used_pct = (
            cluster.used_capacity /
            cluster.total_capacity
        ) * 100

    if used_pct >= 95:
        result.add_blocker(
            "Cluster capacity critically high: " +
            str(round(used_pct, 1)) + "% used.",
            {"check": "capacity",
             "used_pct": round(used_pct, 1)},
        )
    elif used_pct >= 85:
        result.add_warning(
            "Cluster capacity high: " +
            str(round(used_pct, 1)) + "% used.",
            {"check": "capacity",
             "used_pct": round(used_pct, 1)},
        )
    elif used_pct >= 70:
        result.add_info(
            "Cluster capacity: " +
            str(round(used_pct, 1)) + "% used.",
            {"check": "capacity",
             "used_pct": round(used_pct, 1)},
        )


# ==============================================================
# Main Collector Entry Point
# ==============================================================

def collect_upgrade_prechecks(client, cluster,
                               target_version):
    result = CollectionResult(
        collector_name="upgrade_prechecks"
    )

    with CollectorTimer(result):
        logger.debug(
            "  [%s] Running upgrade pre-checks (%s -> %s)",
            cluster.name, cluster.version, target_version
        )

        # Load static EOS data [1]
        eos_data = load_eos_data()

        # Fetch RSC cluster info using proven queries [1]
        rsc_info = fetch_rsc_cluster_info(client, cluster)

        result.raw_data = {
            "rsc_info": rsc_info,
            "eos_data_version": eos_data.get(
                "_metadata", {}
            ).get("last_updated", "unknown"),
        }

        # Run all checks
        check_eos_status(result, cluster, eos_data)
        check_upgrade_path(
            result, cluster, target_version,
            eos_data, rsc_info
        )
        check_version_specific_risks(
            result, cluster, target_version
        )
        check_rsc_connectivity(result, cluster, rsc_info)
        check_cluster_health(result, cluster, rsc_info)
        check_capacity(result, cluster)

        result.summary = {
            "current_version": cluster.version,
            "target_version": target_version,
            "rsc_info_available": bool(rsc_info),
            "blockers": len(result.blockers),
            "warnings": len(result.warnings),
            "info": len(result.info_messages),
        }

        logger.debug(
            "  [%s] Upgrade prechecks complete: "
            "%dB / %dW / %dI",
            cluster.name,
            len(result.blockers),
            len(result.warnings),
            len(result.info_messages)
        )

    return result