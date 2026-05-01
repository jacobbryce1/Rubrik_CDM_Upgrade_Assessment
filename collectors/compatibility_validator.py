#!/usr/bin/env python3
"""
Collector: Compatibility Validator

RSC HierarchyObjectTypeEnum fixes:
- MssqlDatabase -> MssqlInstance
- OracleDatabase -> OracleHost

Updated: Per-server detail in warning/blocker
messages so individual incompatible servers and
their versions surface in the HTML report.
"""

import logging
from collectors import CollectionResult, CollectorTimer
from compatibility_matrix import (
    validate_vsphere_vcenter,
    validate_vsphere_esxi,
    validate_host_os,
    validate_mssql,
    validate_oracle,
)
from config import Config

logger = logging.getLogger(__name__)


VCENTER_QUERY = """
query VCenters($first: Int, $after: String) {
    vSphereVCenterConnection(
        first: $first
        after: $after
    ) {
        edges {
            node {
                id
                name
                cluster { id name }
            }
        }
        pageInfo { hasNextPage endCursor }
        count
    }
}
"""

ESXI_HOST_QUERY = """
query ESXiHosts($first: Int, $after: String) {
    vSphereHostConnection(
        first: $first
        after: $after
    ) {
        edges {
            node {
                id
                name
                physicalPath { name objectType }
                cluster { id name }
            }
        }
        pageInfo { hasNextPage endCursor }
        count
    }
}
"""

MSSQL_DISCOVERY_QUERY = """
query MssqlDiscovery($first: Int, $after: String) {
    inventoryRoot {
        descendantConnection(
            first: $first
            after: $after
            typeFilter: [MssqlInstance]
        ) {
            edges {
                node {
                    id
                    name
                    objectType
                    ... on MssqlInstance {
                        cluster { id name }
                    }
                }
            }
            pageInfo { hasNextPage endCursor }
            count
        }
    }
}
"""

ORACLE_DISCOVERY_QUERY = """
query OracleDiscovery($first: Int, $after: String) {
    inventoryRoot {
        descendantConnection(
            first: $first
            after: $after
            typeFilter: [OracleHost]
        ) {
            edges {
                node {
                    id
                    name
                    objectType
                    ... on OracleHost {
                        cluster { id name }
                    }
                }
            }
            pageInfo { hasNextPage endCursor }
            count
        }
    }
}
"""

HOST_OS_QUERY = """
query HostOSCompat($first: Int, $after: String) {
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
                        cluster { id name }
                    }
                }
            }
            pageInfo { hasNextPage endCursor }
            count
        }
    }
}
"""


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


def discover_vcenter_versions(client, cluster):
    try:
        all_vc = client.graphql_paginated(
            query=VCENTER_QUERY,
            connection_path=[
                "vSphereVCenterConnection"
            ],
        )
        results = []
        for vc in all_vc:
            if node_matches_cluster(vc, cluster):
                name = vc.get("name", "Unknown")
                results.append({
                    "name": name,
                    "version": name,
                    "component_type": "vcenter",
                })
        return results
    except Exception as e:
        logger.debug(
            "  [%s] vCenter failed: %s",
            cluster.name, e
        )
        return []


def discover_esxi_versions_cdm(client, cluster):
    try:
        hosts = client.cdm_get_paginated(
            "api/v1/vmware/host",
            page_key="data",
            cluster_id=cluster.cluster_id,
        )
        results = []
        seen = set()
        for host in (hosts or []):
            ver = host.get("esxiVersion", "") or ""
            name = host.get("name", "Unknown")
            if ver and ver not in seen:
                seen.add(ver)
                results.append({
                    "name": name,
                    "version": ver,
                    "component_type": "esxi",
                })
        return results
    except Exception as e:
        logger.debug(
            "  [%s] ESXi CDM failed: %s",
            cluster.name, e
        )
        return []


def discover_esxi_versions_rsc(client, cluster):
    try:
        all_hosts = client.graphql_paginated(
            query=ESXI_HOST_QUERY,
            connection_path=[
                "vSphereHostConnection"
            ],
        )
        results = []
        for host in all_hosts:
            if node_matches_cluster(host, cluster):
                name = host.get("name", "Unknown")
                path = host.get(
                    "physicalPath", []
                ) or []
                vc = ""
                for p in path:
                    ot = p.get("objectType", "")
                    if ("Vcenter" in ot
                            or "vCenter" in ot):
                        vc = p.get("name", "")
                        break
                results.append({
                    "name": name,
                    "version": (
                        vc if vc else "See vCenter"
                    ),
                    "component_type": "esxi",
                })
        return results
    except Exception as e:
        logger.debug(
            "  [%s] ESXi RSC failed: %s",
            cluster.name, e
        )
        return []


def discover_mssql_versions(client, cluster):
    try:
        all_items = client.graphql_paginated(
            query=MSSQL_DISCOVERY_QUERY,
            connection_path=[
                "inventoryRoot",
                "descendantConnection",
            ],
        )
        results = []
        seen = set()
        for item in all_items:
            if node_matches_cluster(item, cluster):
                name = item.get("name", "Unknown")
                sql_ver = _normalize_mssql(name)
                if sql_ver and sql_ver not in seen:
                    seen.add(sql_ver)
                    results.append({
                        "name": name,
                        "version": name,
                        "normalized_version": sql_ver,
                        "component_type": "mssql",
                    })
        return results
    except Exception as e:
        logger.debug(
            "  [%s] MSSQL failed: %s",
            cluster.name, e
        )
        return []


def discover_oracle_versions(client, cluster):
    try:
        all_items = client.graphql_paginated(
            query=ORACLE_DISCOVERY_QUERY,
            connection_path=[
                "inventoryRoot",
                "descendantConnection",
            ],
        )
        results = []
        for item in all_items:
            if node_matches_cluster(item, cluster):
                name = item.get("name", "Unknown")
                results.append({
                    "name": name,
                    "version": name,
                    "component_type": "oracle",
                })
        return results
    except Exception as e:
        logger.debug(
            "  [%s] Oracle failed: %s",
            cluster.name, e
        )
        return []


def discover_host_os_versions(client, cluster):
    try:
        all_hosts = client.graphql_paginated(
            query=HOST_OS_QUERY,
            connection_path=[
                "inventoryRoot",
                "descendantConnection",
            ],
        )
        cluster_hosts = [
            h for h in all_hosts
            if node_matches_cluster(h, cluster)
        ]
        return _extract_os(cluster_hosts)
    except Exception as e:
        logger.debug(
            "  [%s] Host OS failed: %s",
            cluster.name, e
        )
        return []


def _extract_os(hosts):
    results = []
    seen = set()
    for host in hosts:
        os_name = host.get("osName", "") or ""
        os_type = host.get("osType", "") or ""
        name = host.get("name", "Unknown")
        if os_name and os_name not in seen:
            seen.add(os_name)
            results.append({
                "name": name,
                "version": os_name,
                "os_type": os_type,
                "component_type": "host_os",
            })
    return results


def _normalize_mssql(version_str):
    if not version_str:
        return ""
    upper = version_str.upper()
    for year in [
        "2022", "2019", "2017", "2016",
        "2014", "2012"
    ]:
        if year in upper:
            return "SQL Server " + year
    version_map = {
        "16.": "SQL Server 2022",
        "15.": "SQL Server 2019",
        "14.": "SQL Server 2017",
        "13.": "SQL Server 2016",
        "12.": "SQL Server 2014",
        "11.": "SQL Server 2012",
    }
    for prefix, name in version_map.items():
        if version_str.startswith(prefix):
            return name
    return ""
def validate_and_report(result, cluster_name,
                         comp_type, components,
                         validator_func,
                         target_version):
    """
    Validate components against the compatibility
    matrix using two-tier reporting:

    Tier 1 (Cross-Cluster Table):
      Single consolidated WARNING or BLOCKER per
      component type with count + all server names.
      Shows in the main cross-cluster issues table.

    Tier 2 (Per-Cluster Drill-Down):
      Individual per-server INFO entries with
      detected version, minimum supported version,
      and remediation action. Shows when you expand
      the cluster card.
    """
    if not components:
        return

    supported = []
    unsupported = []
    unknown = []

    for comp in components:
        ver = (
            comp.get("normalized_version") or
            comp.get("version", "")
        )
        val = validator_func(ver, target_version)

        if val["supported"] is True:
            supported.append(comp)
        elif val["supported"] is False:
            unsupported.append({
                "component": comp,
                "validation": val,
            })
        else:
            unknown.append({
                "component": comp,
                "validation": val,
            })

    # ══════════════════════════════════════════
    #  UNSUPPORTED — Two-Tier Reporting
    # ══════════════════════════════════════════
    if unsupported:
        # Track whether any are blockers vs warnings
        has_blocker = False
        server_details = []

        # ── Tier 2: Per-server INFO detail ──
        # These show in the per-cluster expandable
        # drill-down section
        for item in unsupported:
            val = item["validation"]
            comp = item["component"]
            comp_name = comp.get(
                "name", "Unknown"
            )
            comp_ver = (
                comp.get("normalized_version")
                or comp.get("version", "Unknown")
            )
            severity = val.get(
                "severity", "WARNING"
            )

            if severity.upper() in (
                "BLOCKER", "CRITICAL", "ERROR"
            ):
                has_blocker = True

            # Collect for Tier 1 summary
            server_details.append(
                comp_name + " (" + comp_ver + ")"
            )

            # Build remediation detail
            detail_parts = []
            notes = val.get("notes", "")
            if notes:
                detail_parts.append(notes)

            min_ver = val.get(
                "minimum_version", ""
            )
            if min_ver:
                detail_parts.append(
                    "Minimum supported: "
                    + str(min_ver)
                )

            max_ver = val.get(
                "maximum_version", ""
            )
            if max_ver:
                detail_parts.append(
                    "Maximum supported: "
                    + str(max_ver)
                )

            supported_range = val.get(
                "supported_versions", ""
            )
            if supported_range:
                detail_parts.append(
                    "Supported versions: "
                    + str(supported_range)
                )

            eol = val.get("end_of_life", "")
            if eol:
                detail_parts.append(
                    "End of Life: " + str(eol)
                )

            detail_parts.append(
                "Action: Upgrade " + comp_name
                + " to a supported version "
                "before upgrading CDM to "
                + target_version
            )
            detail_str = " | ".join(detail_parts)

            # Add per-server INFO finding
            result.add_info(
                comp_type + " detail: "
                + comp_name
                + " (detected: " + comp_ver
                + ") -- not supported on CDM "
                + target_version
                + " | " + detail_str,
                {
                    "check": (
                        "compat_"
                        + comp_type
                        + "_detail"
                    ),
                    "component_name": comp_name,
                    "detected_version": comp_ver,
                },
            )

        # ── Tier 1: Consolidated summary ──
        # Single line for cross-cluster table
        # with all affected server names listed
        summary_msg = (
            str(len(unsupported)) + " "
            + comp_type
            + " version(s) NOT compatible with "
            "CDM " + target_version + ": "
            + ", ".join(server_details)
        )

        if has_blocker:
            result.add_blocker(
                summary_msg,
                {"check": "compat_" + comp_type},
            )
        else:
            result.add_warning(
                summary_msg,
                {"check": "compat_" + comp_type},
            )

    # ══════════════════════════════════════════
    #  SUPPORTED — Consolidated with names
    # ══════════════════════════════════════════
    if supported:
        names = [
            s.get("name", "?") + " ("
            + (s.get("normalized_version")
               or s.get("version", "?"))
            + ")"
            for s in supported
        ]

        # Cap the names list if very long
        if len(names) > 10:
            display = (
                ", ".join(names[:10])
                + " ... and "
                + str(len(names) - 10)
                + " more"
            )
        else:
            display = ", ".join(names)

        result.add_info(
            str(len(supported)) + " "
            + comp_type
            + " version(s) compatible with CDM "
            + target_version + ": "
            + display + ".",
            {"check": "compat_" + comp_type},
        )

    # ══════════════════════════════════════════
    #  UNKNOWN — Consolidated with names
    # ══════════════════════════════════════════
    if unknown:
        names = [
            u["component"].get("name", "?")
            + " ("
            + (u["component"].get(
                "normalized_version"
            ) or u["component"].get(
                "version", "?"
            ))
            + ")"
            for u in unknown
        ]

        if len(names) > 10:
            display = (
                ", ".join(names[:10])
                + " ... and "
                + str(len(names) - 10)
                + " more"
            )
        else:
            display = ", ".join(names)

        result.add_info(
            str(len(unknown)) + " "
            + comp_type
            + " version(s) not in compatibility "
            "matrix -- verify manually: "
            + display + ".",
            {"check": "compat_" + comp_type
             + "_unknown"},
        )

def collect_compatibility_validation(
    client, cluster, target_version
):
    result = CollectionResult(
        collector_name="compatibility_validator"
    )

    with CollectorTimer(result):
        logger.debug(
            "  [%s] Compatibility validation "
            "for CDM %s...",
            cluster.name, target_version
        )

        all_components = {}

        # ── vCenter ──
        vcenters = discover_vcenter_versions(
            client, cluster
        )
        if vcenters:
            all_components["vcenter"] = vcenters
            validate_and_report(
                result, cluster.name, "vCenter",
                vcenters, validate_vsphere_vcenter,
                target_version,
            )

        # ── ESXi ──
        esxi = discover_esxi_versions_cdm(
            client, cluster
        )
        if not esxi:
            esxi = discover_esxi_versions_rsc(
                client, cluster
            )
        if esxi:
            all_components["esxi"] = esxi
            real = [
                e for e in esxi
                if e.get("version", "") not in (
                    "", "See vCenter", "Unknown"
                )
            ]
            if real:
                validate_and_report(
                    result, cluster.name, "ESXi",
                    real, validate_vsphere_esxi,
                    target_version,
                )

        # ── MSSQL ──
        mssql = discover_mssql_versions(
            client, cluster
        )
        if mssql:
            all_components["mssql"] = mssql
            validate_and_report(
                result, cluster.name, "MSSQL",
                mssql, validate_mssql,
                target_version,
            )

        # ── Oracle ──
        oracle = discover_oracle_versions(
            client, cluster
        )
        if oracle:
            all_components["oracle"] = oracle
            validate_and_report(
                result, cluster.name, "Oracle",
                oracle, validate_oracle,
                target_version,
            )

        # ── Host OS ──
        host_os = discover_host_os_versions(
            client, cluster
        )
        if host_os:
            all_components["host_os"] = host_os
            validate_and_report(
                result, cluster.name, "Host OS",
                host_os, validate_host_os,
                target_version,
            )

        # ── Manual checks ──
        manual = []
        if not vcenters:
            manual.append("vCenter versions")
        if not esxi:
            manual.append("ESXi versions")
        manual.append(
            "Nutanix AOS versions "
            "(if applicable)"
        )
        manual.append(
            "Hyper-V/SCVMM versions "
            "(if applicable)"
        )
        manual.append(
            "SAP HANA versions (if applicable)"
        )
        manual.append(
            "PostgreSQL versions (if applicable)"
        )

        if manual:
            result.add_info(
                "Manual verification recommended: "
                + ", ".join(manual) + ".",
                {"check": "compat_manual_checks"},
            )

        # ── Summary ──
        total = sum(
            len(v)
            for v in all_components.values()
        )

        if total == 0:
            result.add_info(
                "No components discovered for "
                "compatibility validation on "
                + cluster.name + ".",
                {"check": "compat_discovery"},
            )
        else:
            parts = [
                str(len(v)) + " " + k
                for k, v in all_components.items()
                if v
            ]
            result.add_info(
                "Compatibility: "
                + str(total)
                + " component(s) -- "
                + ", ".join(parts) + ".",
                {"check": "compat_summary"},
            )

        result.summary = {
            "total_components": total,
            "component_counts": {
                k: len(v)
                for k, v in all_components.items()
            },
        }
        result.raw_data = {
            "discovered_components": all_components,
        }

        logger.debug(
            "  [%s] Compatibility: "
            "%d components, %dB / %dW / %dI",
            cluster.name, total,
            len(result.blockers),
            len(result.warnings),
            len(result.info_messages),
        )

    return result