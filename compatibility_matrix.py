#!/usr/bin/env python3
"""
Rubrik CDM Compatibility Matrix — Machine-readable encoding.
Source: Rubrik Compatibility Matrix
Update this file when Rubrik publishes a new matrix.
"""


# ==============================================================
# Version Utilities
# ==============================================================

def parse_major_version(version_str):
    if not version_str:
        return (0, 0)
    clean = str(version_str).strip().lstrip("vV")
    if "-" in clean:
        clean = clean.split("-")[0]
    parts = clean.split(".")
    try:
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        return (major, minor)
    except (ValueError, IndexError):
        return (0, 0)


def version_to_float(version_str):
    t = parse_major_version(version_str)
    return t[0] + (t[1] / 100.0)


def version_gte(v1, v2):
    return version_to_float(v1) >= version_to_float(v2)


def version_in_cdm_range(cdm_version, min_cdm,
                          max_cdm="99.99"):
    v = version_to_float(cdm_version)
    return (
        version_to_float(min_cdm) <= v <=
        version_to_float(max_cdm)
    )


# ==============================================================
# vSphere Compatibility
# ==============================================================

VSPHERE_COMPAT = {
    "vcenter": {
        "8.0": {"min_cdm": "9.0", "max_cdm": "99.99",
                "notes": "vCenter 8.0 from CDM 9.0+"},
        "7.0": {"min_cdm": "7.0", "max_cdm": "99.99",
                "notes": "vCenter 7.0 from CDM 7.0+"},
        "6.7": {"min_cdm": "5.1", "max_cdm": "9.5",
                "notes": "vCenter 6.7 deprecated 9.5+"},
        "6.5": {"min_cdm": "5.0", "max_cdm": "9.3",
                "notes": "vCenter 6.5 removed 9.4+"},
        "6.0": {"min_cdm": "5.0", "max_cdm": "8.1",
                "notes": "vCenter 6.0 removed 9.0+"},
    },
    "esxi": {
        "8.0": {"min_cdm": "9.0", "max_cdm": "99.99",
                "notes": "ESXi 8.0 from CDM 9.0+"},
        "7.0": {"min_cdm": "7.0", "max_cdm": "99.99",
                "notes": "ESXi 7.0 from CDM 7.0+"},
        "6.7": {"min_cdm": "5.1", "max_cdm": "9.5",
                "notes": "ESXi 6.7 deprecated 9.5+"},
        "6.5": {"min_cdm": "5.0", "max_cdm": "9.3",
                "notes": "ESXi 6.5 removed 9.4+"},
        "6.0": {"min_cdm": "5.0", "max_cdm": "8.1",
                "notes": "ESXi 6.0 removed 9.0+"},
    },
}


# ==============================================================
# Host OS Compatibility
# ==============================================================

HOST_OS_COMPAT = {
    "windows": {
        "Windows Server 2025": {
            "min_cdm": "9.5", "max_cdm": "99.99"},
        "Windows Server 2022": {
            "min_cdm": "8.1", "max_cdm": "99.99"},
        "Windows Server 2019": {
            "min_cdm": "5.1", "max_cdm": "99.99"},
        "Windows Server 2016": {
            "min_cdm": "5.0", "max_cdm": "99.99"},
        "Windows Server 2012 R2": {
            "min_cdm": "5.0", "max_cdm": "9.5",
            "notes": "Deprecated in CDM 9.5+"},
        "Windows Server 2012": {
            "min_cdm": "5.0", "max_cdm": "9.4",
            "notes": "Removed in CDM 9.5+"},
        "Windows Server 2008 R2": {
            "min_cdm": "5.0", "max_cdm": "9.1",
            "notes": "Removed in CDM 9.2+"},
    },
    "rhel": {
        "RHEL 9": {"min_cdm": "9.0", "max_cdm": "99.99"},
        "RHEL 8": {"min_cdm": "7.0", "max_cdm": "99.99"},
        "RHEL 7": {"min_cdm": "5.0", "max_cdm": "99.99"},
        "RHEL 6": {
            "min_cdm": "5.0", "max_cdm": "9.4",
            "notes": "Removed in CDM 9.5+"},
    },
    "centos": {
        "CentOS Stream 9": {
            "min_cdm": "9.1", "max_cdm": "99.99"},
        "CentOS 8": {"min_cdm": "7.0", "max_cdm": "99.99"},
        "CentOS 7": {"min_cdm": "5.0", "max_cdm": "99.99"},
        "CentOS 6": {
            "min_cdm": "5.0", "max_cdm": "9.4",
            "notes": "Removed in CDM 9.5+"},
    },
    "ubuntu": {
        "Ubuntu 24.04": {
            "min_cdm": "9.5", "max_cdm": "99.99"},
        "Ubuntu 22.04": {
            "min_cdm": "9.0", "max_cdm": "99.99"},
        "Ubuntu 20.04": {
            "min_cdm": "8.0", "max_cdm": "99.99"},
        "Ubuntu 18.04": {
            "min_cdm": "7.0", "max_cdm": "99.99"},
        "Ubuntu 16.04": {
            "min_cdm": "5.0", "max_cdm": "9.3",
            "notes": "Removed in CDM 9.4+"},
    },
    "sles": {
        "SLES 15": {"min_cdm": "7.0", "max_cdm": "99.99"},
        "SLES 12": {"min_cdm": "5.0", "max_cdm": "99.99"},
        "SLES 11": {
            "min_cdm": "5.0", "max_cdm": "9.3",
            "notes": "Removed in CDM 9.4+"},
    },
    "oracle_linux": {
        "Oracle Linux 9": {
            "min_cdm": "9.1", "max_cdm": "99.99"},
        "Oracle Linux 8": {
            "min_cdm": "8.0", "max_cdm": "99.99"},
        "Oracle Linux 7": {
            "min_cdm": "5.0", "max_cdm": "99.99"},
        "Oracle Linux 6": {
            "min_cdm": "5.0", "max_cdm": "9.4",
            "notes": "Removed in CDM 9.5+"},
    },
    "debian": {
        "Debian 12": {"min_cdm": "9.3", "max_cdm": "99.99"},
        "Debian 11": {"min_cdm": "9.0", "max_cdm": "99.99"},
        "Debian 10": {"min_cdm": "8.0", "max_cdm": "99.99"},
        "Debian 9": {
            "min_cdm": "7.0", "max_cdm": "9.3",
            "notes": "Removed in CDM 9.4+"},
    },
    "amazon_linux": {
        "Amazon Linux 2023": {
            "min_cdm": "9.3", "max_cdm": "99.99"},
        "Amazon Linux 2": {
            "min_cdm": "8.0", "max_cdm": "99.99"},
    },
}


# ==============================================================
# MSSQL Compatibility
# ==============================================================

MSSQL_COMPAT = {
    "SQL Server 2022": {
        "min_cdm": "9.0", "max_cdm": "99.99"},
    "SQL Server 2019": {
        "min_cdm": "7.0", "max_cdm": "99.99"},
    "SQL Server 2017": {
        "min_cdm": "5.1", "max_cdm": "99.99"},
    "SQL Server 2016": {
        "min_cdm": "5.0", "max_cdm": "99.99"},
    "SQL Server 2014": {
        "min_cdm": "5.0", "max_cdm": "9.5",
        "notes": "Deprecated in CDM 9.5+"},
    "SQL Server 2012": {
        "min_cdm": "5.0", "max_cdm": "9.3",
        "notes": "Removed in CDM 9.4+"},
}


# ==============================================================
# Oracle Compatibility
# ==============================================================

ORACLE_COMPAT = {
    "Oracle 23c": {
        "min_cdm": "9.4", "max_cdm": "99.99"},
    "Oracle 21c": {
        "min_cdm": "9.0", "max_cdm": "99.99"},
    "Oracle 19c": {
        "min_cdm": "7.0", "max_cdm": "99.99"},
    "Oracle 18c": {
        "min_cdm": "5.3", "max_cdm": "99.99"},
    "Oracle 12c R2": {
        "min_cdm": "5.0", "max_cdm": "99.99"},
    "Oracle 12c R1": {
        "min_cdm": "5.0", "max_cdm": "99.99"},
    "Oracle 11g R2": {
        "min_cdm": "5.0", "max_cdm": "9.5",
        "notes": "Deprecated in CDM 9.5+"},
    "Oracle 11g R1": {
        "min_cdm": "5.0", "max_cdm": "9.3",
        "notes": "Removed in CDM 9.4+"},
}


# ==============================================================
# Validation Functions
# ==============================================================

def validate_vsphere_vcenter(version_str, target_cdm):
    return _validate_component(
        version_str,
        VSPHERE_COMPAT["vcenter"],
        target_cdm, "vCenter",
    )


def validate_vsphere_esxi(version_str, target_cdm):
    return _validate_component(
        version_str,
        VSPHERE_COMPAT["esxi"],
        target_cdm, "ESXi",
    )


def validate_host_os(os_name, target_cdm):
    if not os_name:
        return {
            "supported": None,
            "severity": "INFO",
            "notes": "OS name not available",
        }

    for category, versions in HOST_OS_COMPAT.items():
        result = _validate_component(
            os_name, versions, target_cdm,
            "Host OS (" + category + ")"
        )
        if result["supported"] is not None:
            return result

    return {
        "supported": None,
        "severity": "INFO",
        "notes": (
            "OS '" + os_name + "' not found in "
            "compatibility matrix. Verify manually."
        ),
    }


def validate_mssql(version_str, target_cdm):
    return _validate_component(
        version_str, MSSQL_COMPAT,
        target_cdm, "MSSQL",
    )


def validate_oracle(version_str, target_cdm):
    return _validate_component(
        version_str, ORACLE_COMPAT,
        target_cdm, "Oracle",
    )


def validate_hyperv(version_str, target_cdm):
    return {
        "supported": None,
        "severity": "INFO",
        "notes": "Hyper-V validation not available",
    }


def validate_nutanix_aos(version_str, target_cdm):
    return {
        "supported": None,
        "severity": "INFO",
        "notes": "Nutanix AOS validation not available",
    }


def validate_postgresql(version_str, target_cdm):
    return {
        "supported": None,
        "severity": "INFO",
        "notes": "PostgreSQL validation not available",
    }


def validate_sap_hana(version_str, target_cdm):
    return {
        "supported": None,
        "severity": "INFO",
        "notes": "SAP HANA validation not available",
    }


# ==============================================================
# Generic Validation Engine
# ==============================================================

def _validate_component(component_version,
                         compat_table, target_cdm,
                         component_name):
    if not component_version:
        return {
            "supported": None,
            "severity": "INFO",
            "notes": (
                component_name +
                " version not available"
            ),
            "component": component_name,
            "version": "",
            "target_cdm": target_cdm,
        }

    component_upper = component_version.upper().strip()
    target_float = version_to_float(target_cdm)

    for known_version, compat in compat_table.items():
        if known_version.upper() in component_upper:
            min_cdm = compat.get("min_cdm", "0.0")
            max_cdm = compat.get("max_cdm", "99.99")
            notes = compat.get("notes", "")

            min_float = version_to_float(min_cdm)
            max_float = version_to_float(max_cdm)

            if min_float <= target_float <= max_float:
                return {
                    "supported": True,
                    "severity": "INFO",
                    "notes": (
                        component_name + " '" +
                        component_version +
                        "' is supported by CDM " +
                        target_cdm + ". " + notes
                    ),
                    "component": component_name,
                    "version": component_version,
                    "target_cdm": target_cdm,
                }
            elif target_float > max_float:
                return {
                    "supported": False,
                    "severity": "WARNING",
                    "notes": (
                        component_name + " '" +
                        component_version +
                        "' NOT supported by CDM " +
                        target_cdm + " (max: " +
                        max_cdm + "). " + notes
                    ),
                    "component": component_name,
                    "version": component_version,
                    "target_cdm": target_cdm,
                }
            elif target_float < min_float:
                return {
                    "supported": False,
                    "severity": "INFO",
                    "notes": (
                        component_name + " '" +
                        component_version +
                        "' requires CDM " +
                        min_cdm + "+ (target: " +
                        target_cdm + "). " + notes
                    ),
                    "component": component_name,
                    "version": component_version,
                    "target_cdm": target_cdm,
                }

    return {
        "supported": None,
        "severity": "INFO",
        "notes": (
            component_name + " '" +
            component_version +
            "' not found in compatibility matrix. "
            "Verify manually."
        ),
        "component": component_name,
        "version": component_version,
        "target_cdm": target_cdm,
    }