#!/usr/bin/env python3
"""
Collector: CDM Network Configuration
Ported from original working tool [1].

All CDM REST API endpoints use FULL path including
api/v1/ or api/internal/ prefix, matching original tool [1].
"""

import logging
from collectors import CollectionResult, CollectorTimer
from config import Config

logger = logging.getLogger(__name__)


def check_network_interfaces(result, client, cluster):
    """Check network interfaces via CDM API [1]."""
    try:
        data = client.cdm_direct_get(
            "api/v1/cluster/me/network_interface",
            cluster_id=cluster.cluster_id,
        )

        if not data:
            result.add_info(
                "Could not retrieve network interface data.",
                {"check": "network_interfaces"},
            )
            return

        interfaces = []
        if isinstance(data, dict):
            interfaces = data.get("data", [])
        elif isinstance(data, list):
            interfaces = data

        if not interfaces:
            result.add_info(
                "No network interface data returned.",
                {"check": "network_interfaces", "count": 0},
            )
            return

        mgmt = []
        data_ifaces = []
        bond = []
        down = []
        mtus = set()

        for iface in interfaces:
            iface_name = iface.get("interfaceName", "")
            iface_type = (
                iface.get("interfaceType", "") or ""
            ).upper()
            status = (
                iface.get("status", "") or ""
            ).upper()
            mtu = iface.get("mtu", 0)

            if mtu:
                mtus.add(mtu)

            if "MANAGEMENT" in iface_type or "MGMT" in iface_type:
                mgmt.append(iface)
            elif "DATA" in iface_type:
                data_ifaces.append(iface)

            if "BOND" in iface_name.upper():
                bond.append(iface)

            if status in ("DOWN", "ERROR", "INACTIVE"):
                down.append(iface)

        result.add_info(
            "Network interfaces on " + cluster.name +
            ": " + str(len(interfaces)) + " total (" +
            str(len(mgmt)) + " management, " +
            str(len(data_ifaces)) + " data, " +
            str(len(bond)) + " bond). " +
            "MTU values: " + str(sorted(mtus) if mtus else "default"),
            {
                "check": "network_interface_summary",
                "total": len(interfaces),
                "management": len(mgmt),
                "data": len(data_ifaces),
                "bonds": len(bond),
            },
        )

        if down:
            for iface in down:
                iface_name = iface.get("interfaceName", "?")
                node = iface.get("node", "?")
                result.add_warning(
                    "Network interface '" + iface_name +
                    "' on node '" + node +
                    "' is DOWN.",
                    {"check": "network_interface_down",
                     "interface": iface_name,
                     "node": node},
                )

        result.summary["network_interfaces"] = {
            "total": len(interfaces),
            "management": len(mgmt),
            "data": len(data_ifaces),
            "bonds": len(bond),
            "down": len(down),
        }

    except Exception as e:
        logger.debug(
            "  [%s] Network interface check failed: %s",
            cluster.name, e
        )
        result.add_info(
            "Could not retrieve network interface data.",
            {"check": "network_interfaces"},
        )


def check_vlan_config(result, client, cluster):
    """Check VLAN configuration [1]."""
    try:
        data = client.cdm_direct_get(
            "api/internal/cluster/me/vlan",
            cluster_id=cluster.cluster_id,
        )

        if not data:
            result.add_info(
                "No VLAN configuration data returned.",
                {"check": "vlan_config"},
            )
            return

        vlans = []
        if isinstance(data, dict):
            vlans = data.get("data", [])
        elif isinstance(data, list):
            vlans = data

        if not vlans:
            result.add_info(
                "No VLANs configured on " +
                cluster.name + ".",
                {"check": "vlan_config", "count": 0},
            )
            return

        result.add_info(
            str(len(vlans)) + " VLAN(s) configured on " +
            cluster.name + ". VLANs will be preserved "
            "through upgrade.",
            {"check": "vlan_config", "count": len(vlans)},
        )

        for vlan in vlans:
            vlan_id = vlan.get("vlan", "?")
            netmask = vlan.get("netmask", "")
            ips = vlan.get("ips", [])

            result.findings.append({
                "severity": "INFO",
                "check": "vlan_detail",
                "message": (
                    "VLAN " + str(vlan_id) +
                    ": netmask=" + netmask +
                    ", " + str(len(ips)) + " IP(s)"
                ),
            })

        result.summary["vlans"] = {
            "count": len(vlans),
        }

    except Exception as e:
        logger.debug(
            "  [%s] VLAN config check failed: %s",
            cluster.name, e
        )


def check_floating_ips(result, client, cluster):
    """Check floating IPs for SMB/NFS [1]."""
    try:
        data = client.cdm_direct_get(
            "api/internal/cluster/me/floating_ip",
            cluster_id=cluster.cluster_id,
        )

        if not data:
            return

        floating_ips = []
        if isinstance(data, dict):
            floating_ips = data.get("data", [])
        elif isinstance(data, list):
            floating_ips = data

        if not floating_ips:
            return

        result.add_warning(
            str(len(floating_ips)) +
            " floating IP(s) configured on " +
            cluster.name +
            ". During upgrade, floating IPs may "
            "temporarily migrate. Clients using "
            "SMB/NFS may experience brief interruptions.",
            {"check": "floating_ips",
             "count": len(floating_ips)},
        )

        for fip in floating_ips:
            ip = fip.get("ip", "?")
            iface = fip.get("interface", "")
            node = fip.get("node", "")

            result.findings.append({
                "severity": "INFO",
                "check": "floating_ip_detail",
                "message": (
                    "Floating IP: " + ip +
                    " on " + iface +
                    " (node: " + node + ")"
                ),
            })

        result.summary["floating_ips"] = {
            "count": len(floating_ips),
        }

    except Exception as e:
        logger.debug(
            "  [%s] Floating IP check failed: %s",
            cluster.name, e
        )


def check_dns_search_domains(result, client, cluster):
    """Check DNS search domains [1]."""
    try:
        data = client.cdm_direct_get(
            "api/v1/cluster/me/dns_search_domain",
            cluster_id=cluster.cluster_id,
        )

        if data:
            domains = data if isinstance(data, list) else []
            if domains:
                result.add_info(
                    "DNS search domains: " +
                    ", ".join(domains),
                    {"check": "dns_search_domains",
                     "domains": domains},
                )

    except Exception as e:
        logger.debug(
            "  [%s] DNS search domain check failed: %s",
            cluster.name, e
        )


def check_proxy_config(result, client, cluster):
    """Check network proxy configuration [1]."""
    try:
        data = client.cdm_direct_get(
            "api/internal/node_management/proxy_config",
            cluster_id=cluster.cluster_id,
        )

        if not data:
            result.add_info(
                "No proxy configuration data returned.",
                {"check": "proxy_config"},
            )
            return

        proxy_config = data if isinstance(data, dict) else {}
        proxy_host = proxy_config.get("host", "")
        proxy_port = proxy_config.get("port", "")
        proxy_protocol = proxy_config.get("protocol", "")
        proxy_username = proxy_config.get("username", "")

        if proxy_host:
            auth_info = (
                " (with authentication)"
                if proxy_username else ""
            )
            result.add_info(
                "Network proxy configured: " +
                proxy_protocol + "://" + proxy_host +
                ":" + str(proxy_port) + auth_info,
                {"check": "proxy_config",
                 "host": proxy_host},
            )

            result.add_warning(
                "Network proxy is configured. Verify "
                "proxy allows HTTPS traffic to RSC "
                "endpoints and CDM upgrade download "
                "servers.",
                {"check": "proxy_upgrade_risk"},
            )
        else:
            result.add_info(
                "No network proxy configured.",
                {"check": "proxy_config"},
            )

    except Exception as e:
        logger.debug(
            "  [%s] Proxy config check failed: %s",
            cluster.name, e
        )


def check_cluster_api_info(result, client, cluster):
    """
    Cross-check cluster info via CDM REST API [1].
    Uses GET /api/v1/cluster/me
    """
    try:
        data = client.cdm_direct_get(
            "api/v1/cluster/me",
            cluster_id=cluster.cluster_id,
        )

        if not data or not isinstance(data, dict):
            return

        name = data.get("name", "")
        node_count = data.get("nodeCount", 0)
        version = data.get("version", "")
        api_version = data.get("apiVersion", "")

        result.add_info(
            "Cluster API reports: name='" + name +
            "', nodes=" + str(node_count) +
            ", version=" + version +
            ", apiVersion=" + api_version,
            {"check": "cluster_api_status",
             "name": name,
             "node_count": node_count,
             "version": version},
        )

        if node_count and cluster.node_count:
            if node_count != cluster.node_count:
                result.add_warning(
                    "Node count mismatch: CDM API "
                    "reports " + str(node_count) +
                    " nodes, RSC reports " +
                    str(cluster.node_count) + " nodes.",
                    {"check": "node_count_mismatch"},
                )

    except Exception as e:
        logger.debug(
            "  [%s] Cluster API info check failed: %s",
            cluster.name, e
        )


def check_static_routes(result, client, cluster):
    """Check custom static routes [1]."""
    try:
        data = client.cdm_direct_get(
            "api/internal/cluster/me/route",
            cluster_id=cluster.cluster_id,
        )

        if not data:
            return

        routes = []
        if isinstance(data, dict):
            routes = data.get("data", [])
        elif isinstance(data, list):
            routes = data

        if routes:
            result.add_info(
                str(len(routes)) +
                " static route(s) configured. "
                "Routes will be preserved through "
                "upgrade.",
                {"check": "static_routes",
                 "count": len(routes)},
            )

            for route in routes:
                network = route.get("network", "?")
                netmask = route.get("netmask", "")
                gateway = route.get("gateway", "")

                result.findings.append({
                    "severity": "INFO",
                    "check": "static_route_detail",
                    "message": (
                        "Route: " + network +
                        "/" + netmask +
                        " via " + gateway
                    ),
                })

    except Exception as e:
        logger.debug(
            "  [%s] Static route check failed: %s",
            cluster.name, e
        )


# ==============================================================
# Main Collector Entry Point
# ==============================================================

def collect_network_config(client, cluster):
    """
    Network configuration assessment via CDM REST API.
    All endpoints use full path matching original tool [1].
    """
    result = CollectionResult(
        collector_name="cdm_network_config"
    )

    with CollectorTimer(result):
        logger.debug(
            "  [%s] Checking network configuration...",
            cluster.name
        )

        check_network_interfaces(result, client, cluster)
        check_vlan_config(result, client, cluster)
        check_floating_ips(result, client, cluster)
        check_dns_search_domains(result, client, cluster)
        check_proxy_config(result, client, cluster)
        check_cluster_api_info(result, client, cluster)
        check_static_routes(result, client, cluster)

        logger.debug(
            "  [%s] Network config complete: "
            "%dB / %dW / %dI",
            cluster.name,
            len(result.blockers),
            len(result.warnings),
            len(result.info_messages)
        )

    return result