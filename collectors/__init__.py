#!/usr/bin/env python3
"""
Rubrik CDM Pre-Upgrade Assessment — Collectors Package
Ported from original working tool [1].
Each collector module performs a specific category of checks
and returns a CollectionResult.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any

logger = logging.getLogger("collectors")


@dataclass
class CollectionResult:
    """
    Standardized result from a single collector module.
    Matches original tool's result pattern [1].
    """
    collector_name: str = ""
    success: bool = True
    duration_sec: float = 0.0

    # Findings by severity
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info_messages: List[str] = field(default_factory=list)

    # Structured findings for detailed reporting
    findings: List[Dict] = field(default_factory=list)

    # Raw data from API calls
    raw_data: Dict = field(default_factory=dict)

    # Summary metrics
    summary: Dict = field(default_factory=dict)

    # Error message if collector failed
    error: str = ""

    @property
    def total_findings(self):
        return (
            len(self.blockers) +
            len(self.warnings) +
            len(self.info_messages)
        )

    def add_blocker(self, message, detail=None):
        self.blockers.append(message)
        if detail:
            self.findings.append({
                "severity": "BLOCKER",
                "message": message,
                **detail,
            })

    def add_warning(self, message, detail=None):
        self.warnings.append(message)
        if detail:
            self.findings.append({
                "severity": "WARNING",
                "message": message,
                **detail,
            })

    def add_info(self, message, detail=None):
        self.info_messages.append(message)
        if detail:
            self.findings.append({
                "severity": "INFO",
                "message": message,
                **detail,
            })


class CollectorTimer:
    """Context manager to time collector execution."""

    def __init__(self, result):
        self._result = result
        self._start = None

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._result.duration_sec = round(
            time.time() - self._start, 2
        )
        if exc_type is not None:
            self._result.success = False
            self._result.error = (
                str(exc_type.__name__) + ": " +
                str(exc_val)
            )
            logger.error(
                "Collector [%s] failed: %s",
                self._result.collector_name,
                exc_val
            )
        return False