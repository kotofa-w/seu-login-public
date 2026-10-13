# Read-only checks. This does not register or run scheduled tasks.
$ErrorActionPreference = 'Stop'
$class = Get-CimClass -Namespace Root/Microsoft/Windows/TaskScheduler -ClassName MSFT_TaskEventTrigger
$trigger = New-CimInstance -CimClass $class -ClientOnly -Property @{ Enabled = $true; Subscription = '<QueryList/>'; Delay = 'PT5S' }
if ($trigger.PSTypeNames -notcontains 'Microsoft.Management.Infrastructure.CimInstance#MSFT_TaskTrigger') {
    throw 'Event trigger is missing its scheduled-task base type.'
}
$action = New-ScheduledTaskAction -Execute 'pythonw.exe'
New-ScheduledTask -Action $action -Trigger $trigger | Out-Null
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'install-network-trigger.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors.Message -join "`n") }
$mutations = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.CommandAst] -and $node.GetCommandName() -in @('Register-ScheduledTask', 'Enable-ScheduledTask', 'Unregister-ScheduledTask') }, $true)
if ($mutations.Count -ne 3) { throw 'Unexpected task mutation count.' }
foreach ($command in $mutations) {
    if ($command.Extent.Text -notmatch '-ErrorAction\s+Stop\b') { throw 'Task failure could be reported as success.' }
}
Write-Output 'PASS: native trigger binding, installer syntax and terminating task errors; no task changed.'
