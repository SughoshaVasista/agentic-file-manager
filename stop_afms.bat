@echo off
:: stop_afms.bat — Double-click this to stop all AFMS background services.
:: It launches the PowerShell stop script with the right execution policy.

powershell -ExecutionPolicy Bypass -File "%~dp0stop_afms.ps1"
