# File 24: `README.md`

```markdown
# Rubrik CDM Pre-Upgrade Compatibility Assessment Tool

Automated pre-upgrade assessment for Rubrik CDM clusters via
RSC GraphQL API and CDM Direct REST API. Designed for environments
from 1 cluster to 200+ clusters with 100K+ servers.

Built by Jacob Bryce- Advisory SE

NOTE- THIS IS NOT A RUBRIK BUILT OR SUPPORTED TOOL. THIS CARRIES NO WARRANTIES OR SUPPORTABILITY BY RUBRIK OR ITS CREATOR.  THIS WAS BUILT USING PUBLICLY AVAILABLE DOCUMENTATION FOR RUBRIK RSC & CDM.  IT IS INTENDED TO HELP FACILITATE THE UPGRADE PROCESS FOR LARGE AND COMPLEX ENVIRONMENTS.  PLEAE ALWAYS CHECK WITH THE LATEST RUBRIK DOCUMENTATION.


## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    main.py (Orchestrator)                │
│  Phase 1: Discover → Phase 2: Enrich → Phase 4: Assess │
│            (Parallel ThreadPoolExecutor)                 │
├─────────────────────────────────────────────────────────┤
│                    rsc_client.py                         │
│  RSC Token Refresh │ CDM Per-Cluster Auth │ Node Failover│
├──────────────────────┬──────────────────────────────────┤
│   RSC GraphQL API    │      CDM Direct REST API         │
│  (cursor pagination) │   (offset pagination + failover) │
├──────────────────────┴──────────────────────────────────┤
│                    Collectors                            │
│  upgrade_prechecks    │ workload_inventory               │
│  sla_compliance       │ cdm_system_status                │
│  cdm_live_mounts      │ cdm_archive_replication          │
│  cdm_network_config   │ cdm_workloads                    │
│  host_inventory       │ compatibility_validator           │
├─────────────────────────────────────────────────────────┤
│                    Output                                │
│  In-Memory Mode  │  Streaming Mode (disk-backed)        │
│  (small envs)    │  (100+ clusters, 100K+ servers)      │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Prerequisites

- Python 3.8+
- RSC Service Account with permissions:
  - `ViewCluster`
  - `ViewSLA`
  - `ViewInventory`
  - `UPGRADE_CLUSTER` (optional — enables live upgrade path data)

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your RSC credentials and target version
```

Minimum configuration:
```bash
RSC_BASE_URL=https://your-org.my.rubrik.com
RSC_ACCESS_TOKEN_URI=https://your-org.my.rubrik.com/api/client_token
RSC_CLIENT_ID=your-client-id
RSC_CLIENT_SECRET=your-client-secret
TARGET_CDM_VERSION=9.1.0
```

### 4. Run

```bash
python main.py
```

## Project Structure

```
rubrik-cdm-upgrade-assessment/
├── main.py                      # Parallel orchestrator
├── config.py                    # Configuration
├── rsc_client.py                # RSC + CDM API client
├── cluster_discovery.py         # Cluster discovery & enrichment
├── models.py                    # Data models + streaming output
├── compatibility_matrix.py      # CDM compatibility matrix
├── cdm_eos_data.json            # Static EOS dates & upgrade paths
├── requirements.txt             # Python dependencies
├── .env.example                 # Configuration template
├── README.md                    # This file
├── collectors/
│   ├── __init__.py              # Collector base
│   ├── upgrade_prechecks.py     # EOS, upgrade path, version risks
│   ├── workload_inventory.py    # VM, DB, host inventory
│   ├── sla_compliance.py        # SLA, archival, replication
│   ├── cdm_system_status.py     # Node, disk, DNS, NTP, storage
│   ├── cdm_live_mounts.py       # Active live mount detection
│   ├── cdm_archive_replication.py # Archive/replication topology
│   ├── cdm_network_config.py    # VLAN, floating IP, proxy
│   ├── cdm_workloads.py         # Hosts, agents, filesets, AD, K8s
│   ├── host_inventory.py        # RSC host inventory + OS compat
│   └── compatibility_validator.py # Matrix validation
├── output/                      # Assessment output (auto-created)
└── logs/                        # Log files (auto-created)
```

## How It Works

### Phase 1: Connect & Discover
- Authenticates to RSC via service account
- Discovers all CDM clusters using `clusterConnection` GraphQL query
- Applies inclusion/exclusion filters

### Phase 2: Enrich + CDM Auth (Parallel)
- Fetches node IPs, capacity metrics, upgrade info per cluster
- Authenticates to each CDM cluster via `POST /api/v1/service_account/session`
- Uses the same RSC service account credentials for CDM auth
- Runs in parallel across all clusters

### Phase 3: Cluster Inventory
- Displays discovered clusters with version, node count, CDM auth status

### Phase 4: Assess (Parallel)
- Runs all collector modules against each cluster in parallel
- RSC-based collectors always run (GraphQL queries)
- CDM-direct collectors only run on authenticated clusters

### Phase 5: Generate Reports
- JSON, CSV (issues + summary), and HTML reports

### Phase 6: Final Summary
- Displays blocker/warning counts, API statistics, output location

## Authentication

### RSC (Rubrik Security Cloud)
- Bearer token from `/api/client_token` endpoint
- Auto-refreshes before expiry for multi-hour runs

### CDM (Direct REST API)
- Per-cluster session token via `POST /api/v1/service_account/session`
- Uses the SAME RSC Client ID and Secret
- No additional CDM-level configuration needed
- Fresh session created per cluster to avoid token contamination

## Assessment Categories

### Blockers (Must resolve before upgrade)
- Cluster system status not OK
- Unhealthy nodes
- Active live mounts (VMware, MSSQL, Oracle, MV, etc.)
- No supported upgrade path to target version
- End-of-Support CDM version
- Storage capacity >= 95%
- RSC disconnected

### Warnings (Should review before upgrade)
- Disconnected hosts
- Retention-locked SLAs
- Sub-hourly snapshot SLAs
- Active archival/replication jobs
- Replication version mismatches
- Floating IPs (SMB/NFS interruption risk)
- Network proxy configured
- Outdated RBS agent versions
- CDM API token deprecation (9.5.1+)
- High storage utilization (>= 85%)
- AWS S3 archival locations (behavior changes)

### Info (Awareness items)
- Workload inventory summary
- SLA policy summary
- OS distribution
- Agent version distribution
- Network configuration details
- Storage utilization
- Running jobs count

## Output Files

### Standard Mode (STREAMING_OUTPUT=false)
```
output/assessment_YYYYMMDD_HHMMSS/
├── assessment_report.json       # Full JSON report
├── assessment_issues.csv        # All issues (flat CSV)
├── cluster_summary.csv          # One row per cluster
└── assessment_report.html       # Visual HTML report
```

### Streaming Mode (STREAMING_OUTPUT=true)
```
output/assessment_YYYYMMDD_HHMMSS/
├── manifest.json                # Master manifest
├── summary.jsonl                # One JSON line per cluster
├── all_issues.csv               # Incremental issues CSV
├── failures.jsonl               # Failed assessments
├── skipped.jsonl                # Skipped clusters
├── assessment_report.json       # Summary JSON
├── cluster_summary.csv          # One row per cluster
├── assessment_report.html       # Visual HTML report
└── clusters/
    ├── cluster_name_1.json      # Per-cluster detail
    ├── cluster_name_2.json
    └── ...
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0    | No blockers found — clusters appear ready |
| 1    | Blockers found — do NOT proceed with upgrade |
| 2    | Assessment failures — review before proceeding |

## Scaling Features

| Feature | Purpose |
|---------|---------|
| Parallel cluster assessment | 10x+ runtime reduction |
| Cursor-based GraphQL pagination | Handles 100K+ objects |
| CDM REST offset pagination | Complete data collection |
| RSC token auto-refresh | Multi-hour run support |
| Per-cluster CDM auth | Thread-safe parallel access |
| Global request semaphore | Prevents RSC API overload |
| CDM node failover | Handles unreachable nodes |
| Streaming disk-backed output | Low memory for large envs |
| Per-collector error isolation | One failure doesn't stop others |
| Thread-safe data structures | Safe parallel execution |

## Updating Static Data

### EOS Dates & Upgrade Paths
Edit `cdm_eos_data.json` when Rubrik publishes:
- New End-of-Support dates
- End-of-Life dates
- Upgrade path changes
- Version-specific known issues

### Compatibility Matrix
Edit `compatibility_matrix.py` when Rubrik publishes:
- New CDM version support for hypervisors/databases/OS
- Deprecation of older component versions

## Troubleshooting

### "404 Not Found" on token endpoint
- `RSC_ACCESS_TOKEN_URI` is wrong
- Go to RSC > Settings > Service Accounts
- Copy the exact "Access Token URI"

### "401 Unauthorized"
- `RSC_CLIENT_ID` or `RSC_CLIENT_SECRET` is wrong
- Re-copy credentials from RSC Service Account

### "CDM direct API not available"
- CDM cluster nodes not reachable from this machine
- Set `CDM_DIRECT_ENABLED=false` for RSC-only mode
- Or configure network access to CDM node IPs

### "Rate limited (429)"
- Reduce `MAX_PARALLEL_CLUSTERS` or `MAX_CONCURRENT_API_REQUESTS`
- The tool auto-retries with exponential backoff

### Debug Logging
```bash
LOG_LEVEL=DEBUG python main.py
```
Full debug logs always written to `logs/assessment_*.log`.
```

