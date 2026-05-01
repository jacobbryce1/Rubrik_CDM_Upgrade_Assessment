#!/usr/bin/env python3
"""
Collector: CDM Direct Workload Checks
Ported from original working tool [1].

All CDM REST API endpoints use FULL path:
- api/v1/host [1]
- api/v1/fileset_template [1]
- api/v1/exchange/dag [1]
- api/internal/active_directory/domain_controller [1]
- api/internal/kubernetes/cluster [1]
- api/v1/stats/unmanaged_objects [1]
- api/v1/stats/missed_snapshots [1]
- api/v1/vmware/host [1]
"""

import logging
from collectors import CollectionResult, CollectorTimer
from config import Config

logger = logging.getLogger(__name__)


def check_host_inventory(result, client, cluster):
    """
    Fetch host inventory from CDM with connection status.
    Uses GET api/v1/host [1].
    Reports ALL disconnected hosts.
    """
    try:
        data = client.cdm_get_paginated(
            "api/v1/host",
            page_key="data",
            cluster_id=cluster.cluster_id,
        )

        if not data:
            result.add_info(
                "No hosts registered on " +
                cluster.name + " via CDM API.",
                {"check": "cdm_host_inventory",
                 "count": 0},
            )
            return []

        connected = []
        disconnected = []
        unknown = []
        os_counts = {}

        for host in data:
            name = host.get("name", "Unknown")
            status = (
                host.get("status") or ""
            ).upper()
            os_type = host.get(
                "operatingSystemType", "Unknown"
            )

            os_counts[os_type] = (
                os_counts.get(os_type, 0) + 1
            )

            if status in ("CONNECTED", "REPLICATED"):
                connected.append(host)
            elif status in (
                "DISCONNECTED", "DELETED",
                "MISSING", "UNREGISTERED"
            ):
                disconnected.append(host)
            else:
                unknown.append(host)

        result.add_info(
            "CDM host inventory for " + cluster.name +
            ": " + str(len(data)) + " total (" +
            str(len(connected)) + " connected, " +
            str(len(disconnected)) + " disconnected, " +
            str(len(unknown)) + " unknown). " +
            "OS distribution: " + str(os_counts),
            {"check": "cdm_host_summary",
             "total": len(data),
             "connected": len(connected),
             "disconnected": len(disconnected),
             "os_counts": os_counts},
        )

        if disconnected:
            result.add_warning(
                str(len(disconnected)) +
                " host(s) are DISCONNECTED on " +
                cluster.name +
                ". Reconnect before upgrade.",
                {"check": "cdm_disconnected_hosts",
                 "count": len(disconnected)},
            )

            for host in disconnected:
                name = host.get("name", "?")
                os_type = host.get(
                    "operatingSystemType", "?"
                )
                last_seen = host.get(
                    "lastConnectionTime", "unknown"
                )

                result.findings.append({
                    "severity": "WARNING",
                    "check": "cdm_disconnected_host_detail",
                    "message": (
                        "Host '" + name + "' (" +
                        os_type + ") -- disconnected "
                        "(last seen: " + last_seen + ")"
                    ),
                    "host_name": name,
                    "os_type": os_type,
                })

        result.summary["host_inventory"] = {
            "total": len(data),
            "connected": len(connected),
            "disconnected": len(disconnected),
            "unknown": len(unknown),
            "os_counts": os_counts,
        }

        return data

    except Exception as e:
        logger.debug(
            "  [%s] CDM host inventory failed: %s",
            cluster.name, e
        )
        return []


def check_agent_versions(result, client, cluster,
                          hosts, target_version):
    """
    Check RBS agent versions against target CDM [1].
    """
    if not hosts:
        return

    from collectors.upgrade_prechecks import (
        parse_version_tuple,
    )

    agents_checked = 0
    outdated_agents = []
    no_agent = []

    for host in hosts:
        name = host.get("name", "?")
        agent_status = host.get("agentStatus", {}) or {}

        if not agent_status:
            no_agent.append(host)
            continue

        agent_version = agent_status.get("version", "")
        if not agent_version:
            no_agent.append(host)
            continue

        agents_checked += 1

        agent_tuple = parse_version_tuple(agent_version)
        target_tuple = parse_version_tuple(target_version)

        if agent_tuple[0] < target_tuple[0] - 1:
            outdated_agents.append({
                "host_name": name,
                "agent_version": agent_version,
            })

    if outdated_agents:
        result.add_warning(
            str(len(outdated_agents)) +
            " host(s) have significantly outdated "
            "RBS agents that may not be compatible "
            "with CDM " + target_version + ".",
            {"check": "agent_version_check",
             "outdated_count": len(outdated_agents),
             "agents_checked": agents_checked},
        )

        for agent in outdated_agents[:50]:
            result.findings.append({
                "severity": "WARNING",
                "check": "outdated_agent_detail",
                "message": (
                    "Host '" + agent["host_name"] +
                    "' has RBS agent v" +
                    agent["agent_version"]
                ),
            })
    else:
        result.add_info(
            str(agents_checked) +
            " RBS agent(s) checked -- all appear "
            "compatible with target CDM " +
            target_version + ". (" +
            str(len(no_agent)) +
            " hosts without agent info.)",
            {"check": "agent_version_check",
             "agents_checked": agents_checked},
        )

    result.summary["agent_versions"] = {
        "checked": agents_checked,
        "outdated": len(outdated_agents),
        "no_agent": len(no_agent),
    }


def check_fileset_configs(result, client, cluster):
    """
    Check fileset template configurations.
    Uses GET api/v1/fileset_template [1].
    """
    try:
        templates = client.cdm_get_paginated(
            "api/v1/fileset_template",
            page_key="data",
            cluster_id=cluster.cluster_id,
        )

        if not templates:
            result.add_info(
                "No fileset templates configured.",
                {"check": "fileset_templates",
                 "count": 0},
            )
            return

        complex_includes = []
        large_excludes = []

        for tmpl in templates:
            name = tmpl.get("name", "?")
            includes = tmpl.get("includes", []) or []
            excludes = tmpl.get("excludes", []) or []

            for inc in includes:
                if inc in ("/", "C:\\", "*", "**"):
                    complex_includes.append({
                        "template": name,
                        "include": inc,
                    })

            if len(excludes) > 50:
                large_excludes.append({
                    "template": name,
                    "exclude_count": len(excludes),
                })

        result.add_info(
            str(len(templates)) +
            " fileset template(s) configured.",
            {"check": "fileset_templates",
             "count": len(templates)},
        )

        if complex_includes:
            result.add_info(
                str(len(complex_includes)) +
                " fileset template(s) have very broad "
                "include paths (root/wildcard).",
                {"check": "fileset_broad_includes"},
            )

        if large_excludes:
            result.add_info(
                str(len(large_excludes)) +
                " fileset template(s) have >50 "
                "exclude rules.",
                {"check": "fileset_large_excludes"},
            )

        result.summary[
            "fileset_templates"
        ] = len(templates)

    except Exception as e:
        logger.debug(
            "  [%s] Fileset template check failed: %s",
            cluster.name, e
        )


def check_exchange_dags(result, client, cluster):
    """
    Check Exchange DAG protection.
    Uses GET api/v1/exchange/dag [1].
    """
    try:
        dags = client.cdm_get_paginated(
            "api/v1/exchange/dag",
            page_key="data",
            cluster_id=cluster.cluster_id,
        )

        if not dags:
            return

        result.add_info(
            str(len(dags)) +
            " Exchange DAG(s) configured.",
            {"check": "exchange_dags",
             "count": len(dags)},
        )

        for dag in dags:
            dag_name = dag.get("name", "?")
            status = (
                dag.get("status") or ""
            ).upper()
            db_count = len(dag.get("databases", []))

            if status not in (
                "OK", "CONNECTED", "HEALTHY", ""
            ):
                result.add_warning(
                    "Exchange DAG '" + dag_name +
                    "' status: " + status +
                    ". Verify Exchange connectivity.",
                    {"check": "exchange_dag_health",
                     "dag_name": dag_name},
                )
            else:
                result.findings.append({
                    "severity": "INFO",
                    "check": "exchange_dag_detail",
                    "message": (
                        "Exchange DAG '" + dag_name +
                        "': " + str(db_count) +
                        " database(s)"
                    ),
                })

        result.summary["exchange_dags"] = len(dags)

    except Exception as e:
        logger.debug(
            "  [%s] Exchange DAG check failed: %s",
            cluster.name, e
        )


def check_active_directory(result, client, cluster,
                            target_version):
    """
    Check Active Directory protection.
    Uses GET api/internal/active_directory/domain_controller [1].
    CDM 9.4.3 has known AD backup hanging issue.
    """
    try:
        ad_objects = client.cdm_get_paginated(
            "api/internal/active_directory"
            "/domain_controller",
            page_key="data",
            cluster_id=cluster.cluster_id,
        )

        if not ad_objects:
            return

        result.add_info(
            str(len(ad_objects)) +
            " Active Directory domain controller(s) "
            "protected.",
            {"check": "active_directory",
             "count": len(ad_objects)},
        )

        if target_version.startswith("9.4.3"):
            result.add_warning(
                "CDM 9.4.3 has a known issue with "
                "Active Directory backups potentially "
                "hanging. " + str(len(ad_objects)) +
                " AD domain controller(s) are "
                "protected on this cluster.",
                {"check": "ad_943_known_issue",
                 "ad_count": len(ad_objects)},
            )

        for dc in ad_objects:
            dc_name = dc.get("name", "?")
            status = (
                dc.get("status") or ""
            ).upper()

            if status in ("DISCONNECTED", "ERROR"):
                result.add_warning(
                    "AD domain controller '" +
                    dc_name + "' is " + status +
                    ". Reconnect before upgrade.",
                    {"check": "ad_dc_health",
                     "dc_name": dc_name},
                )

        result.summary[
            "active_directory"
        ] = len(ad_objects)

    except Exception as e:
        logger.debug(
            "  [%s] AD check failed: %s",
            cluster.name, e
        )


def check_kubernetes(result, client, cluster):
    """
    Check Kubernetes protection.
    Uses GET api/internal/kubernetes/cluster [1].
    """
    try:
        k8s_clusters = client.cdm_get_paginated(
            "api/internal/kubernetes/cluster",
            page_key="data",
            cluster_id=cluster.cluster_id,
        )

        if not k8s_clusters:
            return

        result.add_info(
            str(len(k8s_clusters)) +
            " Kubernetes cluster(s) protected.",
            {"check": "kubernetes",
             "count": len(k8s_clusters)},
        )

        for k8s in k8s_clusters:
            k8s_name = k8s.get("name", "?")
            status = (
                k8s.get("status") or ""
            ).upper()

            if status in ("DISCONNECTED", "ERROR"):
                result.add_warning(
                    "Kubernetes cluster '" +
                    k8s_name + "' is " + status +
                    ". Reconnect before upgrade.",
                    {"check": "k8s_health",
                     "k8s_name": k8s_name},
                )

        result.summary[
            "kubernetes"
        ] = len(k8s_clusters)

    except Exception as e:
        logger.debug(
            "  [%s] Kubernetes check failed: %s",
            cluster.name, e
        )


def check_unmanaged_objects(result, client, cluster):
    """
    Check for unmanaged (relic) objects.
    Uses GET api/v1/stats/unmanaged_objects [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/v1/stats/unmanaged_objects",
            cluster_id=cluster.cluster_id,
        )

        if not data or not isinstance(data, dict):
            return

        unmanaged_count = data.get("count", 0)
        unmanaged_storage = data.get("storage", 0)

        if unmanaged_count > 0:
            storage_gb = (
                round(unmanaged_storage / (1024 ** 3), 1)
                if unmanaged_storage else 0
            )

            if unmanaged_count > 100 or storage_gb > 500:
                result.add_warning(
                    str(unmanaged_count) +
                    " unmanaged (relic) object(s) "
                    "consuming " + str(storage_gb) +
                    " GB. Consider cleaning up "
                    "before upgrade.",
                    {"check": "unmanaged_objects",
                     "count": unmanaged_count,
                     "storage_gb": storage_gb},
                )
            else:
                result.add_info(
                    str(unmanaged_count) +
                    " unmanaged object(s) (" +
                    str(storage_gb) + " GB).",
                    {"check": "unmanaged_objects",
                     "count": unmanaged_count},
                )

            result.summary["unmanaged_objects"] = {
                "count": unmanaged_count,
                "storage_gb": storage_gb,
            }

    except Exception as e:
        logger.debug(
            "  [%s] Unmanaged objects check failed: %s",
            cluster.name, e
        )


def check_missed_snapshots(result, client, cluster):
    """
    Check for objects with missed snapshots.
    Uses GET api/v1/stats/missed_snapshots [1].
    """
    try:
        data = client.cdm_direct_get(
            "api/v1/stats/missed_snapshots",
            cluster_id=cluster.cluster_id,
        )

        if not data or not isinstance(data, dict):
            return

        missed_count = data.get("count", 0)

        if missed_count > 0:
            if missed_count > 50:
                result.add_warning(
                    str(missed_count) +
                    " object(s) with missed snapshots. "
                    "Investigate before upgrade.",
                    {"check": "missed_snapshots",
                     "count": missed_count},
                )
            else:
                result.add_info(
                    str(missed_count) +
                    " object(s) with missed snapshots.",
                    {"check": "missed_snapshots",
                     "count": missed_count},
                )

            result.summary[
                "missed_snapshots"
            ] = missed_count

    except Exception as e:
        logger.debug(
            "  [%s] Missed snapshot check failed: %s",
            cluster.name, e
        )


# ==============================================================
# Main Collector Entry Point
# ==============================================================

def collect_cdm_workloads(client, cluster):
    """
    CDM-direct workload checks.
    All endpoints use full path [1].
    """
    result = CollectionResult(
        collector_name="cdm_workloads"
    )

    with CollectorTimer(result):
        logger.debug(
            "  [%s] Running CDM workload checks...",
            cluster.name
        )

        target_version = cluster.raw_data.get(
            "_target_version", ""
        )

        # Host inventory and agent check
        hosts = check_host_inventory(
            result, client, cluster
        )
        if hosts:
            check_agent_versions(
                result, client, cluster,
                hosts, target_version,
            )

        # Fileset configurations
        check_fileset_configs(result, client, cluster)

        # Application-specific checks
        check_exchange_dags(result, client, cluster)
        check_active_directory(
            result, client, cluster, target_version
        )
        check_kubernetes(result, client, cluster)

        # Data hygiene
        check_unmanaged_objects(result, client, cluster)
        check_missed_snapshots(result, client, cluster)

        logger.debug(
            "  [%s] CDM workload checks complete: "
            "%dB / %dW / %dI",
            cluster.name,
            len(result.blockers),
            len(result.warnings),
            len(result.info_messages)
        )

    return result