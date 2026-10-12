@echo off
title MediChain - Production Hackathon Launcher
color 0A
cls

echo ======================================================================
echo             MEDICHAIN - AI HEALTHCARE IDENTITY SYSTEM
echo ======================================================================
echo.
echo [1/3] Cleaning up any old background instances...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq MediChain Backend*" >nul 2>&1

echo [2/3] Starting Local Backend Server on Port 8000...
start "MediChain Backend" cmd /k "color 0B && title MediChain Backend && python start.py"

REM Give Uvicorn 2 seconds to initialize port 8000
timeout /t 2 /nobreak >nul

echo [3/3] Starting Ngrok Secure Tunnel...
start "MediChain Ngrok Tunnel" cmd /k "color 0E && title MediChain Tunnel && .\ngrok.exe http 8000"

echo.
echo ======================================================================
echo           ALL SYSTEMS LIVE AND READY FOR JUDGES DEMO!
echo ======================================================================
echo.
echo 1. Local Swagger API Docs:   http://127.0.0.1:8000/docs
echo 2. Ngrok Tunnel Web Monitor: http://127.0.0.1:4040
echo.
echo Check the "MediChain Ngrok Tunnel" window for your public HTTPS URL!
echo Share that URL with your mobile app teammate.
echo ======================================================================
echo.
pause
