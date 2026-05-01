#!/usr/bin/env python3
"""
Rubrik CDM Pre-Upgrade Assessment — Data Models
Supports both in-memory and streaming output modes
for environments ranging from small to 100K+ servers.
"""

import os
import csv
import json
import logging
import threading
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict

from config import Config

logger = logging.getLogger("models")


# ==============================================================
# Assessment Issue
# ==============================================================

@dataclass
class AssessmentIssue:
    severity: str = ""
    category: str = ""
    check: str = ""
    message: str = ""
    detail: str = ""
    cluster_name: str = ""
    cluster_id: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = (
                datetime.utcnow().isoformat()
            )

    def to_dict(self):
        return {
            "severity": self.severity,
            "category": self.category,
            "check": self.check,
            "message": self.message,
            "detail": self.detail,
            "cluster_name": self.cluster_name,
            "cluster_id": self.cluster_id,
            "timestamp": self.timestamp,
        }

    def to_csv_row(self):
        return [
            self.cluster_name,
            self.cluster_id,
            self.severity,
            self.category,
            self.check,
            self.message,
            self.detail,
        ]

    @staticmethod
    def csv_header():
        return [
            "cluster_name", "cluster_id", "severity",
            "category", "check", "message", "detail",
        ]


# ==============================================================
# Single Cluster Assessment
# ==============================================================

@dataclass
class ClusterAssessment:
    cluster_name: str = ""
    cluster_id: str = ""
    version: str = ""
    target_version: str = ""
    cluster_type: str = ""
    node_count: int = 0
    location: str = ""
    connected_state: str = ""

    assessment_start: str = ""
    assessment_end: str = ""
    assessment_duration_sec: float = 0.0

    issues: List[AssessmentIssue] = field(
        default_factory=list
    )
    collection_results: List = field(
        default_factory=list
    )

    total_blockers: int = 0
    total_warnings: int = 0
    total_info: int = 0

    cdm_api_available: bool = False
    checks_performed: List[str] = field(
        default_factory=list
    )
    raw_data: Dict = field(default_factory=dict)

    def add_issue(self, severity, category, check,
                   message, detail=""):
        issue = AssessmentIssue(
            severity=severity,
            category=category,
            check=check,
            message=message,
            detail=detail,
            cluster_name=self.cluster_name,
            cluster_id=self.cluster_id,
        )
        self.issues.append(issue)

        if severity == "BLOCKER":
            self.total_blockers += 1
        elif severity == "WARNING":
            self.total_warnings += 1
        elif severity == "INFO":
            self.total_info += 1

    def add_collection_result(self, result):
        self.collection_results.append(result)

        for msg in result.blockers:
            self.add_issue(
                severity="BLOCKER",
                category=result.collector_name,
                check=result.collector_name,
                message=msg,
            )
        for msg in result.warnings:
            self.add_issue(
                severity="WARNING",
                category=result.collector_name,
                check=result.collector_name,
                message=msg,
            )
        for msg in result.info_messages:
            self.add_issue(
                severity="INFO",
                category=result.collector_name,
                check=result.collector_name,
                message=msg,
            )

    def to_dict(self):
        return {
            "cluster_name": self.cluster_name,
            "cluster_id": self.cluster_id,
            "version": self.version,
            "target_version": self.target_version,
            "cluster_type": self.cluster_type,
            "node_count": self.node_count,
            "location": self.location,
            "connected_state": self.connected_state,
            "assessment_start": self.assessment_start,
            "assessment_end": self.assessment_end,
            "assessment_duration_sec":
                self.assessment_duration_sec,
            "total_blockers": self.total_blockers,
            "total_warnings": self.total_warnings,
            "total_info": self.total_info,
            "cdm_api_available": self.cdm_api_available,
            "checks_performed": self.checks_performed,
            "issues": [
                i.to_dict() for i in self.issues
            ],
        }

    def clear_raw_data(self):
        self.raw_data = {}
        for cr in self.collection_results:
            cr.raw_data = {}


# ==============================================================
# Multi-Cluster Assessment — In-Memory Mode
# ==============================================================

class MultiClusterAssessment:
    def __init__(self, target_version):
        self.target_version = target_version
        self.assessments = []
        self.failures = []
        self.skipped = []
        self.start_time = datetime.utcnow().isoformat()
        self.end_time = ""
        self._lock = threading.Lock()

    @property
    def global_blockers(self):
        blockers = []
        for a in self.assessments:
            blockers.extend(
                i for i in a.issues
                if i.severity == "BLOCKER"
            )
        return blockers

    @property
    def global_warnings(self):
        warnings = []
        for a in self.assessments:
            warnings.extend(
                i for i in a.issues
                if i.severity == "WARNING"
            )
        return warnings

    @property
    def total_clusters_assessed(self):
        return len(self.assessments)

    @property
    def total_clusters_failed(self):
        return len(self.failures)

    def add_assessment(self, assessment):
        with self._lock:
            self.assessments.append(assessment)

    def add_failure(self, cluster, error):
        with self._lock:
            self.failures.append({
                "cluster_name": cluster.name,
                "cluster_id": cluster.cluster_id,
                "version": cluster.version,
                "error": str(error),
                "timestamp":
                    datetime.utcnow().isoformat(),
            })

    def add_skipped(self, cluster, reason):
        with self._lock:
            self.skipped.append({
                "cluster_name": cluster.name,
                "cluster_id": cluster.cluster_id,
                "version": cluster.version,
                "reason": reason,
            })

    def finalize(self):
        self.end_time = datetime.utcnow().isoformat()

    def to_dict(self):
        return {
            "target_version": self.target_version,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_assessed":
                self.total_clusters_assessed,
            "total_failed":
                self.total_clusters_failed,
            "total_skipped": len(self.skipped),
            "total_blockers":
                len(self.global_blockers),
            "total_warnings":
                len(self.global_warnings),
            "assessments": [
                a.to_dict() for a in self.assessments
            ],
            "failures": self.failures,
            "skipped": self.skipped,
        }


# ==============================================================
# Streaming Multi-Cluster Assessment — Disk-Backed
# ==============================================================

class StreamingMultiAssessment:
    def __init__(self, target_version, output_dir):
        self.target_version = target_version
        self.output_dir = output_dir
        self.start_time = datetime.utcnow().isoformat()
        self.end_time = ""

        self._cluster_dir = os.path.join(
            output_dir, "clusters"
        )
        os.makedirs(self._cluster_dir, exist_ok=True)

        self._summary_file = os.path.join(
            output_dir, "summary.jsonl"
        )
        self._issues_file = os.path.join(
            output_dir, "all_issues.csv"
        )
        self._failures_file = os.path.join(
            output_dir, "failures.jsonl"
        )
        self._skipped_file = os.path.join(
            output_dir, "skipped.jsonl"
        )

        self._lock = threading.Lock()
        self._cluster_count = 0
        self._failure_count = 0
        self._skipped_count = 0
        self._total_blockers = 0
        self._total_warnings = 0
        self._total_info = 0

        self._cluster_summaries = []
        self._failures = []
        self._skipped = []

        with open(self._issues_file, "w",
                  newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(AssessmentIssue.csv_header())

        logger.info(
            "Streaming output initialized: %s",
            output_dir
        )

    @property
    def assessments(self):
        return self._cluster_summaries

    @property
    def failures(self):
        return self._failures

    @property
    def skipped(self):
        return self._skipped

    @property
    def total_clusters_assessed(self):
        return self._cluster_count

    @property
    def total_clusters_failed(self):
        return self._failure_count

    @property
    def global_blockers(self):
        return [
            s for s in self._cluster_summaries
            if s.get("blockers", 0) > 0
        ]

    @property
    def global_warnings(self):
        return [
            s for s in self._cluster_summaries
            if s.get("warnings", 0) > 0
        ]

    def add_assessment(self, assessment):
        with self._lock:
            self._cluster_count += 1
            self._total_blockers += (
                assessment.total_blockers
            )
            self._total_warnings += (
                assessment.total_warnings
            )
            self._total_info += assessment.total_info

            summary = {
                "cluster_name":
                    assessment.cluster_name,
                "cluster_id": assessment.cluster_id,
                "version": assessment.version,
                "target_version":
                    assessment.target_version,
                "cluster_type":
                    assessment.cluster_type,
                "node_count": assessment.node_count,
                "location": assessment.location,
                "blockers": assessment.total_blockers,
                "warnings": assessment.total_warnings,
                "info": assessment.total_info,
                "cdm_api_available":
                    assessment.cdm_api_available,
                "duration_sec":
                    assessment.assessment_duration_sec,
                "checks_performed":
                    assessment.checks_performed,
            }
            self._cluster_summaries.append(summary)

            with open(self._summary_file, "a",
                      encoding="utf-8") as f:
                f.write(
                    json.dumps(summary, default=str) +
                    "\n"
                )

            if assessment.issues:
                with open(self._issues_file, "a",
                          newline="",
                          encoding="utf-8") as f:
                    writer = csv.writer(f)
                    for issue in assessment.issues:
                        writer.writerow(
                            issue.to_csv_row()
                        )

            safe_name = "".join(
                c if c.isalnum() or c in "-_"
                else "_"
                for c in assessment.cluster_name
            )
            detail_file = os.path.join(
                self._cluster_dir,
                safe_name + ".json"
            )
            with open(detail_file, "w",
                      encoding="utf-8") as f:
                json.dump(
                    assessment.to_dict(), f,
                    indent=2, default=str
                )

            assessment.clear_raw_data()

    def add_failure(self, cluster, error):
        with self._lock:
            self._failure_count += 1
            failure = {
                "cluster_name": cluster.name,
                "cluster_id": cluster.cluster_id,
                "version": cluster.version,
                "error": str(error),
                "timestamp":
                    datetime.utcnow().isoformat(),
            }
            self._failures.append(failure)

            with open(self._failures_file, "a",
                      encoding="utf-8") as f:
                f.write(
                    json.dumps(failure, default=str) +
                    "\n"
                )

    def add_skipped(self, cluster, reason):
        with self._lock:
            self._skipped_count += 1
            skipped = {
                "cluster_name": cluster.name,
                "cluster_id": cluster.cluster_id,
                "version": cluster.version,
                "reason": reason,
            }
            self._skipped.append(skipped)

            with open(self._skipped_file, "a",
                      encoding="utf-8") as f:
                f.write(
                    json.dumps(skipped, default=str) +
                    "\n"
                )

    def finalize(self):
        self.end_time = datetime.utcnow().isoformat()

        manifest = {
            "target_version": self.target_version,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_assessed": self._cluster_count,
            "total_failed": self._failure_count,
            "total_skipped": self._skipped_count,
            "total_blockers": self._total_blockers,
            "total_warnings": self._total_warnings,
            "total_info": self._total_info,
        }

        manifest_file = os.path.join(
            self.output_dir, "manifest.json"
        )
        with open(manifest_file, "w",
                  encoding="utf-8") as f:
            json.dump(manifest, f, indent=2,
                      default=str)

        logger.info(
            "Assessment manifest: %s", manifest_file
        )
        return manifest

    def to_dict(self):
        return {
            "target_version": self.target_version,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_assessed": self._cluster_count,
            "total_failed": self._failure_count,
            "total_skipped": self._skipped_count,
            "total_blockers": self._total_blockers,
            "total_warnings": self._total_warnings,
            "total_info": self._total_info,
            "assessments": self._cluster_summaries,
            "failures": self._failures,
            "skipped": self._skipped,
        }


# ==============================================================
# Factory
# ==============================================================

def create_multi_assessment(target_version, output_dir):
    if Config.STREAMING_OUTPUT:
        logger.info(
            "Using STREAMING output mode (disk-backed)"
        )
        return StreamingMultiAssessment(
            target_version=target_version,
            output_dir=output_dir,
        )
    else:
        logger.info(
            "Using STANDARD output mode (in-memory)"
        )
        return MultiClusterAssessment(
            target_version=target_version,
        )