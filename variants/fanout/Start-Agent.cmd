@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0omp-agent\start.ps1" %*
exit /b %errorlevel%
