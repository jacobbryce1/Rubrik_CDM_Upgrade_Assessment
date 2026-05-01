#!/usr/bin/env python3
"""
Rubrik CDM Pre-Upgrade Assessment — Configuration
Original auth flow preserved from working tool [1].
Scaling parameters added for large environments.
"""
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    """
    Centralized configuration.
    Authentication fields match original tool exactly [1].
    Scaling fields added for parallel processing.
    """

    # =========================================================
    # RSC Connection — matches original tool [1]
    # =========================================================
    RSC_URL = os.environ.get("RSC_URL", "").rstrip("/")
    RSC_BASE_URL = os.environ.get(
        "RSC_BASE_URL", ""
    ).rstrip("/") or RSC_URL

    RSC_ACCESS_TOKEN_URI = os.environ.get(
        "RSC_ACCESS_TOKEN_URI", ""
    ).strip()

    RSC_CLIENT_ID = os.environ.get("RSC_CLIENT_ID", "")
    RSC_CLIENT_SECRET = os.environ.get("RSC_CLIENT_SECRET", "")

    # Auto-derive token URI if not set
    if not RSC_ACCESS_TOKEN_URI and RSC_BASE_URL:
        RSC_ACCESS_TOKEN_URI = (
            RSC_BASE_URL + "/api/client_token"
        )

    # =========================================================
    # Target CDM Version
    # =========================================================
    TARGET_CDM_VERSION = os.environ.get(
        "TARGET_CDM_VERSION", ""
    )

    # =========================================================
    # Cluster Filtering
    # =========================================================
    INCLUDE_CLUSTERS = [
        c.strip() for c in
        os.environ.get("INCLUDE_CLUSTERS", "").split(",")
        if c.strip()
    ]
    EXCLUDE_CLUSTERS = [
        c.strip() for c in
        os.environ.get("EXCLUDE_CLUSTERS", "").split(",")
        if c.strip()
    ]
    SKIP_DISCONNECTED = os.environ.get(
        "SKIP_DISCONNECTED_CLUSTERS", "true"
    ).lower() in ("true", "1", "yes")

    # =========================================================
    # Scaling — NEW (not in original tool)
    # =========================================================
    MAX_PARALLEL_CLUSTERS = int(
        os.environ.get("MAX_PARALLEL_CLUSTERS", "10")
    )
    MAX_PARALLEL_ENRICHMENT = int(
        os.environ.get("MAX_PARALLEL_ENRICHMENT", "20")
    )
    MAX_CONCURRENT_API_REQUESTS = int(
        os.environ.get("MAX_CONCURRENT_API_REQUESTS", "20")
    )

    # API Resilience
    API_MAX_RETRIES = int(
        os.environ.get("API_MAX_RETRIES", "5")
    )
    API_BACKOFF_BASE = float(
        os.environ.get("API_BACKOFF_BASE", "1.0")
    )
    API_BACKOFF_MAX = float(
        os.environ.get("API_BACKOFF_MAX", "60.0")
    )
    API_BACKOFF_FACTOR = float(
        os.environ.get("API_BACKOFF_FACTOR", "2.0")
    )
    API_TIMEOUT_SECONDS = int(
        os.environ.get("API_TIMEOUT_SECONDS", "60")
    )
    API_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}

    # Token Management
    TOKEN_REFRESH_BUFFER_SEC = int(
        os.environ.get("TOKEN_REFRESH_BUFFER_SEC", "300")
    )

    # CDM Direct API — matches original [1]
    CDM_DIRECT_ENABLED = os.environ.get(
        "CDM_DIRECT_ENABLED", "true"
    ).lower() in ("true", "1", "yes")
    CDM_DIRECT_TIMEOUT = int(
        os.environ.get("CDM_DIRECT_TIMEOUT", "10")
    )
    MAX_CDM_AUTH_ATTEMPTS = int(
        os.environ.get("MAX_CDM_AUTH_ATTEMPTS", "3")
    )

    # Memory Management
    STREAMING_OUTPUT = os.environ.get(
        "STREAMING_OUTPUT", "false"
    ).lower() in ("true", "1", "yes")

    # Output Settings
    OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "./output")
    LOG_DIR = os.environ.get("LOG_DIR", "./logs")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    REPORT_FORMATS = [
        f.strip() for f in
        os.environ.get("REPORT_FORMATS", "csv,json,html")
        .split(",") if f.strip()
    ]

    # =========================================================
    # Per-cluster state — matches original tool [1]
    # Uses class-level variable for backward compatibility
    # Thread-local override added for parallel safety
    # =========================================================
    _current_cluster_id = ""
    _current_cluster_name = ""
    _current_cluster_version = ""

    # Thread-local storage for parallel cluster processing
    import threading
    _thread_local = threading.local()

    @classmethod
    def set_current_cluster(cls, cluster_id, name="",
                             version=""):
        """Set current cluster context (thread-safe)."""
        cls._thread_local.cluster_id = cluster_id
        cls._thread_local.cluster_name = name
        cls._thread_local.cluster_version = version
        # Also set class-level for backward compat
        cls._current_cluster_id = cluster_id
        cls._current_cluster_name = name
        cls._current_cluster_version = version

    @classmethod
    def get_current_cluster_id(cls):
        """Get current cluster ID (thread-safe)."""
        return getattr(
            cls._thread_local, "cluster_id",
            cls._current_cluster_id
        )

    @classmethod
    def get_current_cluster_name(cls):
        return getattr(
            cls._thread_local, "cluster_name",
            cls._current_cluster_name
        )

    @classmethod
    def get_current_cluster_version(cls):
        return getattr(
            cls._thread_local, "cluster_version",
            cls._current_cluster_version
        )

    @classmethod
    def validate(cls):
        """Validate required configuration."""
        errors = []
        if not cls.RSC_BASE_URL:
            errors.append(
                "RSC_BASE_URL (or RSC_URL) is required"
            )
        if not cls.RSC_ACCESS_TOKEN_URI:
            errors.append(
                "RSC_ACCESS_TOKEN_URI is required — "
                "copy from RSC > Settings > Service Accounts"
            )
        if not cls.RSC_CLIENT_ID:
            errors.append("RSC_CLIENT_ID is required")
        if not cls.RSC_CLIENT_SECRET:
            errors.append("RSC_CLIENT_SECRET is required")
        if not cls.TARGET_CDM_VERSION:
            errors.append("TARGET_CDM_VERSION is required")
        if cls.MAX_PARALLEL_CLUSTERS < 1:
            errors.append(
                "MAX_PARALLEL_CLUSTERS must be >= 1"
            )
        if cls.MAX_PARALLEL_CLUSTERS > 50:
            errors.append(
                "MAX_PARALLEL_CLUSTERS > 50 may "
                "overwhelm RSC API"
            )
        return errors

    @classmethod
    def summary(cls):
        return {
            "rsc_base_url": cls.RSC_BASE_URL,
            "rsc_access_token_uri": cls.RSC_ACCESS_TOKEN_URI,
            "target_cdm_version": cls.TARGET_CDM_VERSION,
            "max_parallel_clusters": cls.MAX_PARALLEL_CLUSTERS,
            "cdm_direct_enabled": cls.CDM_DIRECT_ENABLED,
            "streaming_output": cls.STREAMING_OUTPUT,
        }


def setup_logging():
    """Configure file + console logging."""
    log_dir = Path(Config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / ("assessment_" + timestamp + ".log")

    level = getattr(logging, Config.LOG_LEVEL, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()

    # File handler — always DEBUG
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] "
        "[%(threadName)s] %(name)s: %(message)s"
    ))

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(message)s",
        datefmt="%H:%M:%S",
    ))

    root_logger.addHandler(fh)
    root_logger.addHandler(ch)

    logger = logging.getLogger("assessment")
    logger.info("Logging to: %s", log_file)
    return logger