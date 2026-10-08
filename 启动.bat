@echo off
chcp 65001 >nul
title Mini Assistant
cd /d "%~dp0"

REM Clear proxy vars. Local services do not need a proxy,
REM and a proxy usually refuses to forward 127.0.0.1.
set HTTP_PROXY=
set HTTPS_PROXY=
set http_proxy=
set https_proxy=
set ALL_PROXY=
set PYTHONIOENCODING=utf-8

REM Prefer pythonw (no console window), fall back to python.
set PYW=pythonw.exe
where pythonw.exe >nul 2>&1 || set PYW=python.exe

start "" "%PYW%" "%~dp0run.py"
exit /b 0
