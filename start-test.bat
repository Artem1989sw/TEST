@echo off
chcp 65001 >nul
cd /d "%~dp0"
title English Test Server
start "English Test Server" cmd /k chcp 65001 ^& python server.py
timeout /t 1 /nobreak >nul
start "" http://localhost:8000/
