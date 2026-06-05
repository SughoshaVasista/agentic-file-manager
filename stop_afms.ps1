# stop_afms.ps1 - Gracefully stops all AFMS background services.
#
# Usage:
#   Right-click > Run with PowerShell
#   OR from a terminal:  powershell -ExecutionPolicy Bypass -File stop_afms.ps1

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AFMS - Stopping Background Services"  -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$killed = 0

$targets = @("agent_service.py", "tray_app.py", "background_organizer.py", "organize_this_folder.py")

$allPython = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue

foreach ($proc in $allPython) {
    foreach ($target in $targets) {
        if ($proc.CommandLine -like "*$target*") {
            try {
                Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
                Write-Host "  [STOPPED]  PID $($proc.ProcessId) - $target" -ForegroundColor Green
                $killed++
            }
            catch {
                Write-Host "  [FAILED]   PID $($proc.ProcessId) - $target : $_" -ForegroundColor Red
            }
            break
        }
    }
}

if ($killed -eq 0) {
    Write-Host "  No AFMS processes were running." -ForegroundColor Yellow
}
else {
    Write-Host ""
    Write-Host "  Terminated $killed process(es)." -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Done. You can close this window."      -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
