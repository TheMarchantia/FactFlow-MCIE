@echo off
title FactFlow Backend

echo ========================================
echo        FactFlow Backend Launcher
echo ========================================
echo.

REM Make sure this BAT file runs from the backend folder
cd /d "%~dp0"

REM Create virtual environment only if it does not already exist
if not exist "venv\Scripts\python.exe" (
    echo [1/3] Creating Python 3.11 virtual environment...
    py -3.11 -m venv venv
    if errorlevel 1 (
        echo.
        echo ERROR: Could not create the Python 3.11 virtual environment.
        echo Make sure Python 3.11 is installed.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment already exists. Skipping creation.
)

echo.
echo [2/3] Activating virtual environment...
call "venv\Scripts\activate.bat"

if errorlevel 1 (
    echo.
    echo ERROR: Could not activate the virtual environment.
    pause
    exit /b 1
)

echo.
echo [3/3] Starting FactFlow backend...
echo.

REM Load environment variables from .env if it exists
if exist ".env" (
    echo Loading environment from .env ...
    for /f "usebackq eol=# tokens=* delims=" %%L in (".env") do (
        set "%%L"
    )
) else (
    echo NOTE: No .env file found. Create backend\.env with GEMINI_API_KEY=your_key
)

if defined GEMINI_API_KEY (
    echo Gemini API:  ENABLED
) else (
    echo Gemini API:  DISABLED ^(set GEMINI_API_KEY in .env to enable real verdicts^)
)

echo.
echo Backend: http://localhost:8000
echo API Docs: http://localhost:8000/docs
echo.
echo Press CTRL+C to stop the server.
echo.

uvicorn app.main:app --reload --host 0.0.0.0

echo.
echo FactFlow backend stopped.
pause
