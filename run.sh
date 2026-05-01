#!/bin/bash
# ==============================================================
# Rubrik CDM Pre-Upgrade Assessment — Run Script
# Supports macOS and Linux
# ==============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Banner
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Rubrik CDM Upgrade Assessment           ║${NC}"
echo -e "${BLUE}║  $(date '+%Y-%m-%d %H:%M:%S')                     ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Check Python ──
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo -e "${RED}ERROR: Python 3 not found${NC}"
    echo "Install Python 3.8+ and try again."
    echo "Or run: ./setup.sh"
    exit 1
fi

echo "Python: $($PYTHON --version 2>&1)"

# ── Check virtual environment ──
if [ -d ".venv" ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
else
    echo -e "${RED}ERROR: Virtual environment not found.${NC}"
    echo "Run setup first: ./setup.sh"
    exit 1
fi

# ── Check .env ──
if [ ! -f ".env" ]; then
    echo -e "${RED}ERROR: .env file not found.${NC}"
    echo "Run: cp .env.example .env"
    echo "Then edit .env with your RSC credentials."
    exit 1
fi

# ── Check credentials ──
if grep -q "your-client-id-here" .env 2>/dev/null; then
    echo -e "${RED}ERROR: .env still has placeholder values.${NC}"
    echo "Edit .env with your RSC credentials."
    exit 1
fi

# ── Run assessment ──
echo ""
echo "Starting assessment..."
echo ""

$PYTHON main.py
EXIT_CODE=$?

# ── Post-run summary ──
LATEST=$(ls -td output/assessment_*/ 2>/dev/null | head -1)
LATEST_LOG=$(ls -t logs/assessment_*.log 2>/dev/null | head -1)

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  Assessment Complete — No Blockers       ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
elif [ $EXIT_CODE -eq 1 ]; then
    echo -e "${RED}╔══════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  BLOCKERS FOUND — Review the Report      ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════╝${NC}"
elif [ $EXIT_CODE -eq 2 ]; then
    echo -e "${YELLOW}╔══════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  Some Clusters Failed — Review Errors    ║${NC}"
    echo -e "${YELLOW}╚══════════════════════════════════════════╝${NC}"
fi

echo ""
if [ -n "$LATEST" ]; then
    echo -e "Reports:  ${GREEN}${LATEST}${NC}"

    # Try to open HTML report
    HTML_REPORT="${LATEST}assessment_report.html"
    if [ -f "$HTML_REPORT" ]; then
        echo -e "HTML:     ${GREEN}${HTML_REPORT}${NC}"
        if [ "$(uname -s)" = "Darwin" ]; then
            read -p "Open HTML report in browser? (Y/n): " open_report
            if [ "$open_report" != "n" ] && [ "$open_report" != "N" ]; then
                open "$HTML_REPORT"
            fi
        fi
    fi
fi

if [ -n "$LATEST_LOG" ]; then
    echo -e "Log:      ${GREEN}${LATEST_LOG}${NC}"
fi
echo ""

exit $EXIT_CODE