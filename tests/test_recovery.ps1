$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\heartdevspace\runtime\watch.ps1') -LibraryOnly
$cases = @(
    @{args=@(0,$false,1,0,1000);expected='Start'},
    @{args=@(0,$false,1,0,30);expected='Wait'},
    @{args=@(1,$true,0,1000,1000);expected='Healthy'},
    @{args=@(1,$false,5,120,1000);expected='Starting'},
    @{args=@(1,$false,1,1000,1000);expected='Wait'},
    @{args=@(1,$false,3,1000,1000);expected='Restart'},
    @{args=@(1,$false,4,1000,120);expected='Wait'},
    @{args=@(2,$false,9,1000,1000);expected='Duplicate'}
)
foreach ($case in $cases) { $a=$case.args; if ((Get-RecoveryDecision @a) -ne $case.expected) { throw 'Recovery policy mismatch.' } }
if (-not (Get-PublicRecoveryDecision $true $true 5 530 1000)) { throw 'Public failure recovery failed' }
if (Get-PublicRecoveryDecision $true $true 5 403 1000) { throw 'Authorization response restarted tunnel' }
if (Get-PublicRecoveryDecision $false $true 5 530 1000) { throw 'Origin failure restarted healthy tunnel' }
if (Get-PublicRecoveryDecision $true $true 5 530 100) { throw 'Recovery cooldown failed' }
Write-Output 'PASS: 12 recovery cases'
$env:DEVSPACE_OAUTH_OWNER_TOKEN='unrelated-installation-fixture'
$env:DEVSPACE_ALLOWED_ROOTS='unrelated-root'
$env:DEVSPACE_PORT='1234'
Set-DevSpaceEnvironment ([pscustomobject]@{config_dir='fixture-config';state_dir='fixture-state'})
if ($env:DEVSPACE_OAUTH_OWNER_TOKEN -or $env:DEVSPACE_ALLOWED_ROOTS -or $env:DEVSPACE_PORT) { throw 'Inherited settings leaked into app-managed service.' }
if ($env:DEVSPACE_CONFIG_DIR -ne 'fixture-config' -or $env:DEVSPACE_STATE_DIR -ne 'fixture-state') { throw 'App configuration was not selected.' }
Write-Output 'PASS: inherited configuration isolation'
if (-not (Test-FrpCommand 'frpc.exe -c "C:\data\frpc.toml"' 'C:\data\frpc.toml')) { throw 'Quoted FRP config not matched' }
if (-not (Test-FrpCommand 'frpc.exe -c C:\data\frpc.toml' 'C:\data\frpc.toml')) { throw 'Unquoted FRP config not matched' }
if (Test-FrpCommand 'frpc.exe -c C:\data\frpc.toml.other' 'C:\data\frpc.toml') { throw 'Another FRP config matched' }
if (Test-FrpCommand 'frpc.exe -c C:\elsewhere\frpc.toml' 'C:\data\frpc.toml') { throw 'Unrelated FRP matched' }
Write-Output 'PASS: FRP process identity'
if ((Get-RecoveryDecision 1 $false 20 900 900 $true) -ne 'Deferred') { throw 'Pending gateway restarted an existing FRP process' }
if ((Get-RecoveryDecision 0 $false 0 0 900 $true) -ne 'Start') { throw 'Pending gateway failed to recover an absent FRP process' }
Write-Output 'PASS: pending gateway process recovery'
