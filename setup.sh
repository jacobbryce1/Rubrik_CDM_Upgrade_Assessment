#!/bin/bash
#
# Rubrik CDM Upgrade Assessment — Setup Script
# Supports macOS and Linux (Ubuntu, Debian, RHEL,
# CentOS, Rocky)
#
# Usage: chmod +x setup.sh && ./setup.sh
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Rubrik CDM Upgrade Assessment — Setup   ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""

# =========================================================
# Detect OS
# =========================================================
OS="$(uname -s)"
echo -e "Operating System: ${GREEN}${OS}${NC}"

if [ "$OS" = "Darwin" ]; then
    OS_TYPE="macos"
    echo -e "Platform: ${GREEN}macOS $(sw_vers -productVersion 2>/dev/null || echo 'Unknown')${NC}"
elif [ "$OS" = "Linux" ]; then
    OS_TYPE="linux"
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo -e "Platform: ${GREEN}${NAME} ${VERSION_ID}${NC}"
    else
        echo -e "Platform: ${GREEN}Linux (unknown distro)${NC}"
    fi
else
    echo -e "${RED}ERROR: Unsupported OS: ${OS}${NC}"
    echo "This script supports macOS and Linux."
    echo "For Windows, use setup.bat"
    exit 1
fi
echo ""

# =========================================================
# Step 1: Check / Install Python
# =========================================================
echo -e "${BLUE}Step 1: Checking Python...${NC}"

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 8 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${YELLOW}Python 3.8+ not found. Installing...${NC}"

    if [ "$OS_TYPE" = "macos" ]; then
        if command -v brew &>/dev/null; then
            brew install python@3.11
        else
            echo -e "${RED}ERROR: Homebrew not found.${NC}"
            echo "Install Homebrew first:"
            echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
            echo "Then run this script again."
            exit 1
        fi
        PYTHON=python3

    elif [ "$OS_TYPE" = "linux" ]; then
        if command -v apt-get &>/dev/null; then
            echo "Installing via apt..."
            sudo apt-get update -qq
            sudo apt-get install -y -qq \
                python3 python3-pip python3-venv
        elif command -v dnf &>/dev/null; then
            echo "Installing via dnf..."
            sudo dnf install -y -q \
                python3 python3-pip
        elif command -v yum &>/dev/null; then
            echo "Installing via yum..."
            sudo yum install -y -q \
                python3 python3-pip
        else
            echo -e "${RED}ERROR: No supported package manager found.${NC}"
            echo "Install Python 3.8+ manually."
            exit 1
        fi
        PYTHON=python3
    fi
fi

PYTHON_VER=$($PYTHON --version 2>&1)
echo -e "  ✓ ${GREEN}${PYTHON_VER}${NC}"
echo ""

# =========================================================
# Step 2: Create Virtual Environment
# =========================================================
echo -e "${BLUE}Step 2: Creating virtual environment...${NC}"

if [ -d ".venv" ]; then
    echo -e "  ${YELLOW}Virtual environment already exists.${NC}"
    read -p "  Recreate it? (y/N): " recreate
    if [ "$recreate" = "y" ] || [ "$recreate" = "Y" ]; then
        rm -rf .venv
        $PYTHON -m venv .venv
        echo -e "  ✓ ${GREEN}Virtual environment recreated${NC}"
    else
        echo -e "  ✓ ${GREEN}Using existing virtual environment${NC}"
    fi
else
    $PYTHON -m venv .venv
    echo -e "  ✓ ${GREEN}Virtual environment created${NC}"
fi
echo ""

# =========================================================
# Step 3: Install Dependencies
# =========================================================
echo -e "${BLUE}Step 3: Installing dependencies...${NC}"

source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

echo -e "  ✓ ${GREEN}Dependencies installed${NC}"

# Verify key packages
echo -e "  Installed packages:"
for pkg in requests urllib3 python-dotenv; do
    ver=$(pip show "$pkg" 2>/dev/null | grep "^Version:" | awk '{print $2}')
    if [ -n "$ver" ]; then
        echo -e "    ✓ ${pkg} ${ver}"
    else
        echo -e "    ${RED}✗ ${pkg} NOT FOUND${NC}"
    fi
done
echo ""

# =========================================================
# Step 4: Configure .env
# =========================================================
echo -e "${BLUE}Step 4: Configuring environment...${NC}"

if [ -f ".env" ]; then
    echo -e "  ${YELLOW}.env file already exists.${NC}"
    read -p "  Overwrite with template? (y/N): " overwrite
    if [ "$overwrite" = "y" ] || [ "$overwrite" = "Y" ]; then
        cp .env.example .env
        echo -e "  ✓ ${GREEN}.env reset to template${NC}"
    else
        echo -e "  ✓ ${GREEN}Keeping existing .env${NC}"
    fi
else
    cp .env.example .env
    echo -e "  ✓ ${GREEN}.env created from template${NC}"
fi

# Check if credentials are configured
if grep -q "your-client-id-here" .env 2>/dev/null || \
   grep -q "your-client-secret-here" .env 2>/dev/null; then
    echo ""
    echo -e "  ${YELLOW}╔══════════════════════════════════════╗${NC}"
    echo -e "  ${YELLOW}║  ACTION REQUIRED: Edit .env file     ║${NC}"
    echo -e "  ${YELLOW}╚══════════════════════════════════════╝${NC}"
    echo ""
    echo "  You need to configure the following in .env:"
    echo ""
    echo "    RSC_BASE_URL=https://your-org.my.rubrik.com"
    echo "    RSC_ACCESS_TOKEN_URI=https://your-org.my.rubrik.com/api/client_token"
    echo "    RSC_CLIENT_ID=client|your-client-id"
    echo "    RSC_CLIENT_SECRET=your-client-secret"
    echo "    TARGET_CDM_VERSION=9.1.0"
    echo ""

    if [ "$OS_TYPE" = "macos" ]; then
        echo "  Edit with:  nano .env  (or: open -e .env)"
    else
        echo "  Edit with:  nano .env  (or: vi .env)"
    fi
else
    echo -e "  ✓ ${GREEN}Credentials appear configured${NC}"
fi
echo ""

# =========================================================
# Step 5: Create output directories
# =========================================================
echo -e "${BLUE}Step 5: Creating output directories...${NC}"

mkdir -p output logs
echo -e "  ✓ ${GREEN}output/ directory ready${NC}"
echo -e "  ✓ ${GREEN}logs/ directory ready${NC}"
echo ""

# =========================================================
# Step 6: Set permissions
# =========================================================
echo -e "${BLUE}Step 6: Setting permissions...${NC}"

chmod +x run.sh 2>/dev/null && \
    echo -e "  ✓ ${GREEN}run.sh is executable${NC}" || true
chmod +x setup.sh 2>/dev/null && \
    echo -e "  ✓ ${GREEN}setup.sh is executable${NC}" || true
echo ""

# =========================================================
# Step 7: Validation
# =========================================================
echo -e "${BLUE}Step 7: Validating setup...${NC}"

ERRORS=0

# Check Python
if ! .venv/bin/python3 -c "import sys; assert sys.version_info >= (3,8)" 2>/dev/null; then
    echo -e "  ${RED}✗ Python 3.8+ not available in venv${NC}"
    ERRORS=$((ERRORS + 1))
else
    echo -e "  ✓ ${GREEN}Python version OK${NC}"
fi

# Check key imports
for mod in requests dotenv; do
    if .venv/bin/python3 -c "import ${mod}" 2>/dev/null; then
        echo -e "  ✓ ${GREEN}${mod} importable${NC}"
    else
        echo -e "  ${RED}✗ ${mod} import failed${NC}"
        ERRORS=$((ERRORS + 1))
    fi
done

# Check required files
for f in main.py config.py rsc_client.py models.py \
         cluster_discovery.py compatibility_matrix.py \
         cdm_eos_data.json; do
    if [ -f "$f" ]; then
        echo -e "  ✓ ${GREEN}${f} found${NC}"
    else
        echo -e "  ${RED}✗ ${f} MISSING${NC}"
        ERRORS=$((ERRORS + 1))
    fi
done

# Check collectors directory
if [ -d "collectors" ] && [ -n "$(ls collectors/*.py 2>/dev/null)" ]; then
    COLLECTOR_COUNT=$(ls collectors/*.py 2>/dev/null | wc -l | tr -d ' ')
    echo -e "  ✓ ${GREEN}collectors/ directory: ${COLLECTOR_COUNT} modules${NC}"
else
    echo -e "  ${RED}✗ collectors/ directory missing or empty${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# =========================================================
# Summary
# =========================================================
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  Setup Complete — Ready to Run!          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo "  Next steps:"
    echo "    1. Edit .env with your RSC credentials (if not done)"
    echo "    2. Run the assessment:  ./run.sh"
    echo ""
else
    echo -e "${RED}╔══════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  Setup Incomplete — ${ERRORS} error(s) found     ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo "  Fix the errors above and re-run setup.sh"
    exit 1
fi