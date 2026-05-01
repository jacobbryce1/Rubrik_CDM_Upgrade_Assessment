@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM Rubrik CDM Pre-Upgrade Assessment — Windows Run Script
REM ============================================================

echo.
echo ==========================================
echo   Rubrik CDM Upgrade Assessment
echo   %date% %time%
echo ==========================================
echo.

REM ── Check virtual environment ──
if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found.
    echo.
    echo Run setup first: setup.bat
    echo.
    echo Or manually:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate.bat
    echo   pip install -r requirements.txt
    echo   copy .env.example .env
    echo   notepad .env
    pause
    exit /b 1
)

REM ── Activate venv ──
call .venv\Scripts\activate.bat

REM ── Check .env ──
if not exist ".env" (
    echo ERROR: .env file not found.
    echo Run: copy .env.example .env
    echo Then edit .env with your RSC credentials.
    pause
    exit /b 1
)

REM ── Check credentials ──
findstr /c:"your-client-id-here" .env >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ERROR: .env still has placeholder values.
    echo Edit .env with your RSC credentials.
    echo Run: notepad .env
    pause
    exit /b 1
)

REM ── Run assessment ──
echo Starting assessment...
echo.

python main.py
set EXIT_CODE=%ERRORLEVEL%

REM ── Post-run summary ──
echo.

if %EXIT_CODE% EQU 0 (
    echo ==========================================
    echo   Assessment Complete - No Blockers
    echo ==========================================
) else if %EXIT_CODE% EQU 1 (
    echo ==========================================
    echo   BLOCKERS FOUND - Review the Report
    echo ==========================================
) else if %EXIT_CODE% EQU 2 (
    echo ==========================================
    echo   Some Clusters Failed - Review Errors
    echo ==========================================
)

echo.

REM ── Find latest output ──
for /f "delims=" %%i in (
    'dir /b /od output\assessment_* 2^>nul'
) do set LATEST=output\%%i

if defined LATEST (
    echo Reports: %LATEST%

    if exist "%LATEST%\assessment_report.html" (
        echo HTML:    %LATEST%\assessment_report.html
        echo.
        set /p OPEN_REPORT="Open HTML report in browser? (Y/n): "
        if /i not "!OPEN_REPORT!"=="n" (
            start "" "%LATEST%\assessment_report.html"
        )
    )
)

REM ── Find latest log ──
for /f "delims=" %%i in (
    'dir /b /od logs\assessment_*.log 2^>nul'
) do set LATEST_LOG=logs\%%i

if defined LATEST_LOG (
    echo Log:     %LATEST_LOG%
)

echo.
pause
exit /b %EXIT_CODE%