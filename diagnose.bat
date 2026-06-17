@echo off
title Xiaozhi Diagnostic Center

:: Request admin rights (reading network connections and container logs needs it)
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0diagnose_gui.ps1"
