# setup_oi_cache_scheduler.ps1
# ─────────────────────────────────────────────────────────────────────────
# PowerShell script to create Windows Task Scheduler job for OI cache updates
# 
# Run as Administrator:
#   Right-click PowerShell → Run as Administrator
#   cd C:\Users\USER\Desktop\trading-system-architecture
#   .\setup_oi_cache_scheduler.ps1
# ─────────────────────────────────────────────────────────────────────────

# Requires admin privileges
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Error "This script must be run as Administrator! Right-click PowerShell and select 'Run as Administrator'"
    exit 1
}

$TaskName = "Trading OI Cache Update"
$WorkingDir = "C:\Users\USER\Desktop\trading-system-architecture"
$PythonPath = "C:\Users\USER\anaconda3\python.exe"
$ScriptName = "run_oi_cache_update.py"

Write-Host "Setting up OI Cache Scheduler..." -ForegroundColor Green
Write-Host "Task Name: $TaskName"
Write-Host "Working Directory: $WorkingDir"
Write-Host "Python: $PythonPath"
Write-Host ""

# Check if Python exists
if (-not (Test-Path $PythonPath)) {
    Write-Error "Python not found at: $PythonPath"
    Write-Host "Please update the Python path in this script" -ForegroundColor Yellow
    exit 1
}

# Check if script exists
$ScriptPath = Join-Path $WorkingDir $ScriptName
if (-not (Test-Path $ScriptPath)) {
    Write-Error "Script not found: $ScriptPath"
    exit 1
}

# Remove existing task if it exists
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Removing existing task: $TaskName" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create the action
$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument $ScriptName `
    -WorkingDirectory $WorkingDir

# Create triggers: 10:30 AM, 1:00 PM, 3:00 PM daily
$Trigger1 = New-ScheduledTaskTrigger -Daily -At "10:30 AM"
$Trigger2 = New-ScheduledTaskTrigger -Daily -At "1:00 PM"
$Trigger3 = New-ScheduledTaskTrigger -Daily -At "3:00 PM"

# Task settings
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -WakeToRun:$false

# Register the task
Write-Host "Creating scheduled task..." -ForegroundColor Green
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger1, $Trigger2, $Trigger3 `
        -Settings $Settings `
        -Description "Updates OI/Volume cache from IBKR during market hours (10:30 AM, 1:00 PM, 3:00 PM EST)" `
        -ErrorAction Stop
    
    Write-Host ""
    Write-Host "SUCCESS! Task created: $TaskName" -ForegroundColor Green
    Write-Host ""
    Write-Host "Schedule:" -ForegroundColor Cyan
    Write-Host "  - Daily at 10:30 AM EST (post-open)"
    Write-Host "  - Daily at 1:00 PM EST (mid-day)"
    Write-Host "  - Daily at 3:00 PM EST (pre-close)"
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "  1. Make sure IBKR TWS or Gateway is running before market open"
    Write-Host "  2. Run the task manually now to test: Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  3. Check logs at: $WorkingDir\logs\trading_framework.log"
    Write-Host "  4. Verify cache at: $WorkingDir\data\oi_cache.json"
    Write-Host ""
    
    # Show task info
    $task = Get-ScheduledTask -TaskName $TaskName
    Write-Host "Task Details:" -ForegroundColor Cyan
    Write-Host "  State: $($task.State)"
    Write-Host "  Next Run Time: $(Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object -ExpandProperty NextRunTime)"
    
} catch {
    Write-Error "Failed to create task: $_"
    exit 1
}

Write-Host ""
Write-Host "To run the task now for testing:" -ForegroundColor Green
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor White
Write-Host ""
Write-Host "To remove the task:" -ForegroundColor Green
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false" -ForegroundColor White
