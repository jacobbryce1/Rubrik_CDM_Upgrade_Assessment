#!/usr/bin/env python3
"""
Collector: CDM Archive & Replication Topology
Ported from original working tool [1].

All CDM REST API endpoints use FULL path:
- api/internal/archive/location [1]
- api/internal/archive/location/job/active [1]
- api/internal/replication/target [1]
- api/internal/replication/source [1]
- api/internal/replication/target/stats [1]
"""

import logging
from collectors import CollectionResult, CollectorTimer
from config import Config

logger = logging.getLogger(__name__)


def check_archive_locations(result, client, cluster):
    """
    Inventory archive locations via CDM internal API.
    Uses GET api/internal/archive/location [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/internal/archive/location",
            cluster_id=cluster.cluster_id,
        )

        if not data:
            result.add_info(
                "Could not retrieve archive locations "
                "via CDM API.",
                {"check": "archive_locations"},
            )
            return []

        locations = []
        if isinstance(data, dict):
            locations = data.get("data", [])
        elif isinstance(data, list):
            locations = data

        if not locations:
            result.add_info(
                "No archive locations configured on " +
                cluster.name + ".",
                {"check": "archive_locations",
                 "count": 0},
            )
            return []

        type_counts = {}
        for loc in locations:
            loc_name = loc.get("name", "Unknown")
            loc_type = loc.get(
                "locationType", "Unknown"
            )
            type_counts[loc_type] = (
                type_counts.get(loc_type, 0) + 1
            )

            result.findings.append({
                "severity": "INFO",
                "check": "archive_location_detail",
                "message": (
                    "Archive: " + loc_name +
                    " (" + loc_type + ")"
                ),
                "location_name": loc_name,
                "location_type": loc_type,
            })

        result.add_info(
            "Archive locations on " + cluster.name +
            ": " + str(len(locations)) +
            " location(s). Types: " + str(type_counts),
            {"check": "archive_location_summary",
             "total": len(locations),
             "type_counts": type_counts},
        )

        # AWS S3 risk warnings [1]
        s3_locations = [
            loc for loc in locations
            if (loc.get("locationType", "").upper() in
                ("S3", "AWS", "AMAZON_S3", "AWS_S3",
                 "AMAZONS3"))
        ]
        if s3_locations:
            result.add_warning(
                str(len(s3_locations)) +
                " AWS S3 archive location(s). "
                "CDM 9.4.1+ changed S3 archival "
                "behavior. Verify S3 bucket policies "
                "and IAM permissions.",
                {"check": "aws_s3_archival_risk",
                 "s3_count": len(s3_locations)},
            )

        return locations

    except Exception as e:
        logger.debug(
            "  [%s] Archive location check failed: %s",
            cluster.name, e
        )
        result.add_info(
            "Could not retrieve archive locations.",
            {"check": "archive_locations"},
        )
        return []


def check_active_archive_jobs(result, client, cluster):
    """
    Check for active archival jobs.
    Uses GET api/internal/archive/location/job/active [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/internal/archive/location/job/active",
            cluster_id=cluster.cluster_id,
        )

        active_jobs = 0
        if data:
            if isinstance(data, dict):
                active_jobs = len(data.get("data", []))
            elif isinstance(data, list):
                active_jobs = len(data)

        if active_jobs > 0:
            result.add_warning(
                str(active_jobs) +
                " active archival job(s) running. "
                "Allow archival jobs to complete "
                "before upgrade.",
                {"check": "active_archive_jobs",
                 "count": active_jobs},
            )
        else:
            result.add_info(
                "No active archival jobs detected.",
                {"check": "active_archive_jobs",
                 "count": 0},
            )

        result.summary[
            "active_archive_jobs"
        ] = active_jobs

    except Exception as e:
        logger.debug(
            "  [%s] Active archive jobs check "
            "failed: %s",
            cluster.name, e
        )


def check_replication_targets(result, client, cluster):
    """
    Inventory replication targets.
    Uses GET api/internal/replication/target [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/internal/replication/target",
            cluster_id=cluster.cluster_id,
        )

        if not data:
            result.add_info(
                "Could not retrieve replication targets "
                "via CDM API.",
                {"check": "replication_targets"},
            )
            return []

        targets = []
        if isinstance(data, dict):
            targets = data.get("data", [])
        elif isinstance(data, list):
            targets = data

        if not targets:
            result.add_info(
                "No replication targets configured on " +
                cluster.name + ".",
                {"check": "replication_targets",
                 "count": 0},
            )
            return []

        for t in targets:
            t_name = t.get(
                "targetClusterName", "Unknown"
            )
            t_ver = t.get(
                "targetClusterVersion", ""
            )

            result.findings.append({
                "severity": "INFO",
                "check": "replication_target_detail",
                "message": (
                    "Replication target: " +
                    t_name + " v" + t_ver
                ),
                "target_name": t_name,
                "target_version": t_ver,
            })

        result.add_info(
            "Replication targets on " + cluster.name +
            ": " + str(len(targets)) + " target(s).",
            {"check": "replication_target_summary",
             "count": len(targets)},
        )

        # Version compatibility check [1]
        from collectors.upgrade_prechecks import (
            parse_version_tuple,
        )
        for t in targets:
            t_name = t.get(
                "targetClusterName", "?"
            )
            t_ver = t.get(
                "targetClusterVersion", ""
            )
            if t_ver and cluster.version:
                source_major = parse_version_tuple(
                    cluster.version
                )[0]
                target_major = parse_version_tuple(
                    t_ver
                )[0]
                if source_major != target_major:
                    result.add_warning(
                        "Major version mismatch: "
                        "source " + cluster.name +
                        " (" + cluster.version +
                        ") -> target '" + t_name +
                        "' (" + t_ver + "). "
                        "Plan coordinated upgrades.",
                        {"check":
                         "replication_version_mismatch",
                         "target_name": t_name,
                         "target_version": t_ver},
                    )

        return targets

    except Exception as e:
        logger.debug(
            "  [%s] Replication target check failed: %s",
            cluster.name, e
        )
        result.add_info(
            "Could not retrieve replication targets.",
            {"check": "replication_targets"},
        )
        return []


def check_replication_sources(result, client, cluster):
    """
    Check replication sources (clusters replicating TO us).
    Uses GET api/internal/replication/source [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/internal/replication/source",
            cluster_id=cluster.cluster_id,
        )

        if not data:
            return []

        sources = []
        if isinstance(data, dict):
            sources = data.get("data", [])
        elif isinstance(data, list):
            sources = data

        if sources:
            for s in sources:
                s_name = s.get(
                    "sourceClusterName", "Unknown"
                )
                s_ver = s.get(
                    "sourceClusterVersion", ""
                )

                result.findings.append({
                    "severity": "INFO",
                    "check": "replication_source_detail",
                    "message": (
                        "Replication source: " +
                        s_name + " v" + s_ver
                    ),
                    "source_name": s_name,
                    "source_version": s_ver,
                })

            result.add_info(
                "Replication sources to " +
                cluster.name + ": " +
                str(len(sources)) + " source(s).",
                {"check": "replication_sources",
                 "count": len(sources)},
            )

        return sources

    except Exception as e:
        logger.debug(
            "  [%s] Replication source check failed: %s",
            cluster.name, e
        )
        return []


def check_active_replication(result, client, cluster):
    """
    Check for active replication streams.
    Uses GET api/internal/replication/target/stats [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/internal/replication/target/stats",
            cluster_id=cluster.cluster_id,
        )

        active_streams = 0
        if data:
            if isinstance(data, dict):
                stats_list = data.get("data", [])
                for ts in stats_list:
                    running = ts.get(
                        "runningJobCount", 0
                    )
                    if running:
                        active_streams += running
            elif isinstance(data, list):
                for ts in data:
                    running = ts.get(
                        "runningJobCount", 0
                    )
                    if running:
                        active_streams += running

        if active_streams > 0:
            result.add_warning(
                str(active_streams) +
                " active replication stream(s). "
                "Allow replication to complete "
                "before upgrade.",
                {"check": "active_replication",
                 "count": active_streams},
            )
        else:
            result.add_info(
                "No active replication streams.",
                {"check": "active_replication",
                 "count": 0},
            )

        result.summary[
            "active_replication_streams"
        ] = active_streams

    except Exception as e:
        logger.debug(
            "  [%s] Active replication check failed: %s",
            cluster.name, e
        )


# ==============================================================
# Main Collector Entry Point
# ==============================================================

def collect_archive_replication(client, cluster):
    """
    Archive and replication topology checks.
    All endpoints use full path [1].
    """
    result = CollectionResult(
        collector_name="cdm_archive_replication"
    )

    with CollectorTimer(result):
        logger.debug(
            "  [%s] Checking archive & replication...",
            cluster.name
        )

        cdm_available = client.is_cdm_available(
            cluster.cluster_id
        )

        if not cdm_available:
            result.add_info(
                "CDM direct API not available for " +
                cluster.name +
                ". Archive/replication checks skipped.",
                {"check": "archive_replication_source"},
            )
            return result

        locations = check_archive_locations(
            result, client, cluster
        )
        check_active_archive_jobs(
            result, client, cluster
        )

        targets = check_replication_targets(
            result, client, cluster
        )
        sources = check_replication_sources(
            result, client, cluster
        )
        check_active_replication(
            result, client, cluster
        )

        result.summary.update({
            "archive_locations": len(locations),
            "replication_targets": len(targets),
            "replication_sources": len(sources),
        })

        logger.debug(
            "  [%s] Archive & replication complete: "
            "%dB / %dW / %dI",
            cluster.name,
            len(result.blockers),
            len(result.warnings),
            len(result.info_messages)
        )

    return result