[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ConfigPath,
      [ValidateSet('Install','Check','Stop','Remove')][string]$Action)
$ErrorActionPreference = 'Stop'
$settings = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$taskName = 'Soft-HeartDevSpace-' + $settings.instance_id
$worker = Join-Path $PSScriptRoot 'watch.ps1'
if ($Action -in @('Stop','Remove')) {
    if ($Action -eq 'Remove') {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($task) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
    }
    & $worker -ConfigPath $ConfigPath -ManualStop
    exit $LASTEXITCODE
}
if ($Action -eq 'Check') { & $worker -ConfigPath $ConfigPath; exit $LASTEXITCODE }

$runtime = $PSScriptRoot
$launcher = Join-Path $runtime 'launch.vbs'
$command = '"' + $env:SystemRoot + '\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $worker + '" -ConfigPath "' + $ConfigPath + '"'
$quoted = $command.Replace('"','""')
$vbs = "Option Explicit`r`nDim runner, result`r`nSet runner = CreateObject(""WScript.Shell"")`r`nresult = runner.Run(""$quoted"", 0, True)`r`nWScript.Quit result`r`n"
Set-Content -LiteralPath $launcher -Value $vbs -Encoding Unicode
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$actionDef = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot 'System32\wscript.exe') -Argument ('//B //NoLogo "{0}"' -f $launcher) -WorkingDirectory $runtime
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$logon.Delay = 'PT20S'
$first = (Get-Date).AddSeconds(10)
$tickA = New-ScheduledTaskTrigger -Once -At $first -RepetitionInterval (New-TimeSpan -Minutes 1)
$tickB = New-ScheduledTaskTrigger -Once -At $first.AddSeconds(30) -RepetitionInterval (New-TimeSpan -Minutes 1)
$taskSettings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $actionDef -Trigger @($logon,$tickA,$tickB) -Settings $taskSettings -Principal $principal -Description 'Soft-HeartDevSpace connection heartbeat and recovery.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Output 'Heartbeat installed: every 30 seconds and on user logon.'
