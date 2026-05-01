@echo off
REM ============================================================
REM Rubrik CDM Upgrade Assessment — Windows Setup Script
REM
REM Usage: Right-click and "Run as Administrator"
REM        or from PowerShell/CMD: setup.bat
REM ============================================================

echo.
echo ==========================================
echo   Rubrik CDM Upgrade Assessment - Setup
echo   %date% %time%
echo ==========================================
echo.

REM ── Step 1: Check Python ──
echo Step 1: Checking Python...

python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   ERROR: Python not found in PATH.
    echo.
    echo   Please install Python 3.8+ from:
    echo     https://www.python.org/downloads/
    echo.
    echo   IMPORTANT: Check "Add Python to PATH"
    echo   during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   Python version: %PYVER%
echo.

REM ── Step 2: Create Virtual Environment ──
echo Step 2: Creating virtual environment...

if exist ".venv\Scripts\activate.bat" (
    echo   Virtual environment already exists.
    set /p RECREATE="  Recreate it? (y/N): "
    if /i "%RECREATE%"=="y" (
        rmdir /s /q .venv
        python -m venv .venv
        echo   Virtual environment recreated.
    ) else (
        echo   Using existing virtual environment.
    )
) else (
    python -m venv .venv
    echo   Virtual environment created.
)
echo.

REM ── Step 3: Install Dependencies ──
echo Step 3: Installing dependencies...

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

echo   Dependencies installed.
echo.

REM ── Step 4: Configure .env ──
echo Step 4: Configuring environment...

if exist ".env" (
    echo   .env file already exists.
    set /p OVERWRITE="  Overwrite with template? (y/N): "
    if /i "%OVERWRITE%"=="y" (
        copy .env.example .env >nul
        echo   .env reset to template.
    ) else (
        echo   Keeping existing .env.
    )
) else (
    copy .env.example .env >nul
    echo   .env created from template.
)
echo.

REM ── Check if credentials need editing ──
findstr /c:"your-client-id-here" .env >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   ==========================================
    echo   ACTION REQUIRED: Edit .env file
    echo   ==========================================
    echo.
    echo   Configure the following in .env:
    echo.
    echo     RSC_BASE_URL=https://your-org.my.rubrik.com
    echo     RSC_ACCESS_TOKEN_URI=https://your-org.my.rubrik.com/api/client_token
    echo     RSC_CLIENT_ID=client^|your-client-id
    echo     RSC_CLIENT_SECRET=your-client-secret
    echo     TARGET_CDM_VERSION=9.1.0
    echo.
    echo   Edit with: notepad .env
    echo.
) else (
    echo   Credentials appear configured.
)

REM ── Step 5: Create output directories ──
echo Step 5: Creating output directories...

if not exist "output" mkdir output
if not exist "logs" mkdir logs
echo   output\ directory ready.
echo   logs\ directory ready.
echo.

REM ── Step 6: Validate Setup ──
echo Step 6: Validating setup...

set ERRORS=0

REM Check Python in venv
.venv\Scripts\python.exe -c "import sys; assert sys.version_info >= (3,8)" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   X Python 3.8+ not available in venv
    set /a ERRORS+=1
) else (
    echo   OK Python version OK
)

REM Check key imports
for %%m in (requests dotenv) do (
    .venv\Scripts\python.exe -c "import %%m" >nul 2>&1
    if !ERRORLEVEL! NEQ 0 (
        echo   X %%m import failed
        set /a ERRORS+=1
    ) else (
        echo   OK %%m importable
    )
)

REM Check required files
for %%f in (
    main.py
    config.py
    rsc_client.py
    models.py
    cluster_discovery.py
    compatibility_matrix.py
    cdm_eos_data.json
) do (
    if exist "%%f" (
        echo   OK %%f found
    ) else (
        echo   X %%f MISSING
        set /a ERRORS+=1
    )
)

REM Check collectors
if exist "collectors\*.py" (
    echo   OK collectors\ directory found
) else (
    echo   X collectors\ directory missing
    set /a ERRORS+=1
)

echo.

REM ── Summary ──
if %ERRORS% EQU 0 (
    echo ==========================================
    echo   Setup Complete - Ready to Run!
    echo ==========================================
    echo.
    echo   Next steps:
    echo     1. Edit .env with your RSC credentials
    echo     2. Run the assessment: run.bat
    echo.
) else (
    echo ==========================================
    echo   Setup Incomplete - %ERRORS% error(s)
    echo ==========================================
    echo.
    echo   Fix the errors above and re-run setup.bat
)

pause