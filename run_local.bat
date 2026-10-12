@echo off
title MediChain Local Server
color 0A

echo ============================================================
echo           MediChain Local Server + Public Tunnel
echo ============================================================
echo.

REM 1. Check if python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found in PATH!
    pause
    exit /b 1
)

echo [1/2] Starting MediChain Backend on port 8000...
start "MediChain FastAPI Backend" cmd /k "color 0B && python start.py"

echo.
echo [2/2] Backend started!
echo.
echo ============================================================
echo To expose your backend to teammate's Android Phone via Ngrok:
echo.
echo If you have not added your Ngrok authtoken yet, run once:
echo    .\ngrok.exe config add-authtoken YOUR_TOKEN
echo.
echo Then start the tunnel:
echo    .\ngrok.exe http 8000
echo ============================================================
echo.
pause
