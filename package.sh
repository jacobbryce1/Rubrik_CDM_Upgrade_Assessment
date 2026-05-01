#!/bin/bash
#
# Package the Rubrik CDM Pre-Upgrade Assessment
# Tool into a distributable zip file.
#
# Includes: setup scripts, run scripts, docs,
# all source code, and collectors.
#
# Usage: chmod +x package.sh && ./package.sh
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ZIPNAME="rubrik-cdm-upgrade-assessment-${TIMESTAMP}.zip"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Packaging Assessment Tool               ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""

# =========================================================
# Define file lists
# =========================================================

# Required core files
REQUIRED_FILES=(
    "main.py"
    "config.py"
    "rsc_client.py"
    "models.py"
    "cluster_discovery.py"
    "compatibility_matrix.py"
    "cdm_eos_data.json"
    "requirements.txt"
    ".env.example"
)

# Setup and run scripts (all platforms)
SCRIPT_FILES=(
    "setup.sh"
    "setup.bat"
    "run.sh"
    "run.bat"
)

# Optional extras
OPTIONAL_FILES=(
    "README.md"
    "generate_docs.py"
    "package.sh"
    "package.bat"
    ".gitignore"
)

# =========================================================
# Verify required files
# =========================================================
echo -e "${BLUE}Checking required files...${NC}"

MISSING=0
for f in "${REQUIRED_FILES[@]}"; do
    if [ -f "$f" ]; then
        echo -e "  ${GREEN}✓${NC} $f"
    else
        echo -e "  ${RED}✗ MISSING: $f${NC}"
        MISSING=$((MISSING + 1))
    fi
done

if [ $MISSING -gt 0 ]; then
    echo ""
    echo -e "${RED}ERROR: $MISSING required file(s) missing.${NC}"
    echo "Run this script from the project root."
    exit 1
fi
echo ""

# =========================================================
# Check setup/run scripts
# =========================================================
echo -e "${BLUE}Checking setup & run scripts...${NC}"

SCRIPT_MISSING=0
for f in "${SCRIPT_FILES[@]}"; do
    if [ -f "$f" ]; then
        echo -e "  ${GREEN}✓${NC} $f"
    else
        echo -e "  ${YELLOW}⚠ MISSING: $f${NC}"
        SCRIPT_MISSING=$((SCRIPT_MISSING + 1))
    fi
done

if [ $SCRIPT_MISSING -gt 0 ]; then
    echo -e "  ${YELLOW}$SCRIPT_MISSING setup/run script(s) missing — package will be incomplete${NC}"
fi
echo ""

# =========================================================
# Check optional files
# =========================================================
echo -e "${BLUE}Checking optional files...${NC}"

for f in "${OPTIONAL_FILES[@]}"; do
    if [ -f "$f" ]; then
        echo -e "  ${GREEN}✓${NC} Including: $f"
    else
        echo -e "  ${YELLOW}–${NC} Not found: $f (skipping)"
    fi
done
echo ""

# =========================================================
# Check collectors
# =========================================================
echo -e "${BLUE}Checking collectors...${NC}"

if [ -d "collectors" ]; then
    COLLECTOR_COUNT=$(find collectors -name "*.py" | wc -l | tr -d ' ')
    echo -e "  ${GREEN}✓${NC} collectors/ directory: ${COLLECTOR_COUNT} Python modules"
else
    echo -e "${RED}  ✗ collectors/ directory not found${NC}"
    exit 1
fi
echo ""

# =========================================================
# Generate docs if python-docx is available
# =========================================================
echo -e "${BLUE}Generating documentation...${NC}"

if [ -f "generate_docs.py" ]; then
    if python3 -c "import docx" 2>/dev/null; then
        python3 generate_docs.py 2>/dev/null && \
            echo -e "  ${GREEN}✓${NC} Word document generated" || \
            echo -e "  ${YELLOW}⚠${NC} Doc generation failed (non-critical)"
    else
        echo -e "  ${YELLOW}–${NC} python-docx not installed — skipping"
        echo "    Install with: pip install python-docx"
    fi
else
    echo -e "  ${YELLOW}–${NC} generate_docs.py not found — skipping"
fi
echo ""

# =========================================================
# Build file list for zip
# =========================================================
echo -e "${BLUE}Creating package: ${ZIPNAME}${NC}"

# Start with required files
ZIP_FILES=()
for f in "${REQUIRED_FILES[@]}"; do
    ZIP_FILES+=("$f")
done

# Add setup/run scripts
for f in "${SCRIPT_FILES[@]}"; do
    if [ -f "$f" ]; then
        ZIP_FILES+=("$f")
    fi
done

# Add optional files
for f in "${OPTIONAL_FILES[@]}"; do
    if [ -f "$f" ]; then
        ZIP_FILES+=("$f")
    fi
done

# Add generated docs
if [ -f "Rubrik_CDM_Upgrade_Assessment_Guide.docx" ]; then
    ZIP_FILES+=("Rubrik_CDM_Upgrade_Assessment_Guide.docx")
fi

# Create zip with files + collectors directory
zip -r "${ZIPNAME}" \
    "${ZIP_FILES[@]}" \
    collectors/ \
    --exclude "*.pyc" \
    --exclude "__pycache__/*" \
    --exclude "collectors/__pycache__/*" \
    -x "*.pyc" \
    -x "*__pycache__*"

# =========================================================
# Verify zip contents
# =========================================================
echo ""
echo -e "${BLUE}Package contents:${NC}"
echo "─────────────────────────────────────────"
zipinfo -1 "${ZIPNAME}" | sort
echo "─────────────────────────────────────────"

FILE_COUNT=$(zipinfo -1 "${ZIPNAME}" | wc -l | tr -d ' ')
FILE_SIZE=$(ls -lh "${ZIPNAME}" | awk '{print $5}')

echo ""
echo -e "  ${GREEN}✓${NC} Files included:  ${FILE_COUNT}"
echo -e "  ${GREEN}✓${NC} Package size:    ${FILE_SIZE}"

# =========================================================
# Safety: Ensure .env is NOT included
# =========================================================
if zipinfo -1 "${ZIPNAME}" | grep -q "^\.env$"; then
    echo ""
    echo -e "${RED}⚠ WARNING: .env file detected in zip!${NC}"
    echo "  Removing to protect credentials..."
    zip -d "${ZIPNAME}" ".env"
    echo -e "  ${GREEN}✓${NC} .env removed from package"
fi

# =========================================================
# Verify setup/run scripts are in the zip
# =========================================================
echo ""
echo -e "${BLUE}Verifying setup & run scripts:${NC}"

for f in "${SCRIPT_FILES[@]}"; do
    if zipinfo -1 "${ZIPNAME}" | grep -q "^${f}$"; then
        echo -e "  ${GREEN}✓${NC} $f included"
    else
        echo -e "  ${YELLOW}⚠${NC} $f NOT in package"
    fi
done

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Packaging Complete                      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "  Distribute: ${ZIPNAME}"
echo ""