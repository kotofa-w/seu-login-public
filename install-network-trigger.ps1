param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'seu_login.ini'),
    [string]$PythonPath = '',
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$taskName = 'SEU_NetworkConnect'
$scriptPath = Join-Path $PSScriptRoot 'seu_login.py'
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    $owned = @($existingTask.Actions).Count -eq 1 -and ([string]$existingTask.Actions[0].Arguments).StartsWith(('"' + $scriptPath + '" --on-network-connect '), [System.StringComparison]::OrdinalIgnoreCase)
    if (-not $owned) { throw 'A task with this name belongs to another program. It was not changed.' }
}
if ($Remove) {
    if ($existingTask) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop }
    Write-Output 'Removed SEU_NetworkConnect.'
    return
}
$channel = Get-WinEvent -ListLog 'Microsoft-Windows-WLAN-AutoConfig/Operational'
if (-not $channel.IsEnabled) {
    throw 'WLAN-AutoConfig Operational log is disabled. Enable it before installing the trigger.'
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw 'Configuration not found. Run setup.bat or pass -ConfigPath.'
}
if (-not $PythonPath) {
    $PythonPath = (Get-Command pythonw.exe -ErrorAction Stop).Source
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
$arguments = '"{0}" --on-network-connect --config "{1}"' -f $scriptPath, $ConfigPath
if ($existingTask) {
    if ([string]$existingTask.Actions[0].Arguments -cne $arguments) {
        throw 'The existing task uses a different configuration. Remove it explicitly before installing again.'
    }
    Enable-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
    Write-Output 'SEU_NetworkConnect is installed and enabled for this program.'
    return
}
$action = New-ScheduledTaskAction -Execute $PythonPath -Argument $arguments -WorkingDirectory $PSScriptRoot
$subscription = '<QueryList><Query Id="0" Path="Microsoft-Windows-WLAN-AutoConfig/Operational"><Select Path="Microsoft-Windows-WLAN-AutoConfig/Operational">*[System[(EventID=8001)]]</Select></Query></QueryList>'
$eventTriggerClass = Get-CimClass -Namespace Root/Microsoft/Windows/TaskScheduler -ClassName MSFT_TaskEventTrigger
$eventTrigger = New-CimInstance -CimClass $eventTriggerClass -ClientOnly -Property @{
    Enabled = $true
    Subscription = $subscription
    Delay = 'PT5S'
}
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$logonTrigger.Delay = 'PT30S'
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($eventTrigger, $logonTrigger) -Principal $principal -Settings $settings -Description 'Authenticate SEU WLAN/ISP after a Wi-Fi connection event; no periodic polling.' -ErrorAction Stop | Out-Null
Write-Output 'Installed SEU_NetworkConnect. No authentication was started by the installer.'
