# Soft-HeartDevSpace Windows heartbeat worker.
# Two staggered minute triggers provide a heartbeat every 30 seconds.
[CmdletBinding()]
param([string]$ConfigPath, [switch]$LibraryOnly, [switch]$ManualStop)
$ErrorActionPreference = 'Stop'

function Get-RecoveryDecision {
    param([int]$ProcessCount, [bool]$Healthy, [int]$Failures,
          [double]$AgeSeconds, [double]$SinceRecoverySeconds)
    if ($ProcessCount -gt 1) { return 'Duplicate' }
    if ($ProcessCount -eq 0) {
        if ($SinceRecoverySeconds -lt 60) { return 'Wait' }
        return 'Start'
    }
    if ($Healthy) { return 'Healthy' }
    if ($AgeSeconds -lt 180) { return 'Starting' }
    if ($Failures -ge 3 -and $SinceRecoverySeconds -ge 300) { return 'Restart' }
    return 'Wait'
}

function Get-PublicRecoveryDecision {
    param([bool]$LocalHealthy, [bool]$TunnelHealthy, [int]$Failures,
          [int]$HttpStatus, [double]$SinceRecoverySeconds)
    return ($LocalHealthy -and $TunnelHealthy -and $Failures -ge 5 -and
        $SinceRecoverySeconds -ge 900 -and $HttpStatus -in @(0,502,503,504,530))
}

function Set-DevSpaceEnvironment($Settings) {
    # App-owned configuration must take precedence over a legacy installation's
    # inherited DEVSPACE_* values, including owner credentials and allowed roots.
    foreach ($item in @(Get-ChildItem Env: | Where-Object { $_.Name -like 'DEVSPACE_*' })) {
        Remove-Item -LiteralPath ('Env:' + $item.Name)
    }
    $env:DEVSPACE_CONFIG_DIR = [string]$Settings.config_dir
    $env:DEVSPACE_STATE_DIR = [string]$Settings.state_dir
    $env:DEVSPACE_WIDGETS = 'off'
    $env:DEVSPACE_SKILLS = '0'
    $env:DEVSPACE_TOOL_MODE = 'full'
}

if ($LibraryOnly) { return }
if (-not $ConfigPath) { throw 'ConfigPath is required.' }
$dsSettings = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$dsLogDir = [string]$dsSettings.log_dir
$dsNode = [string]$dsSettings.node_path
$dsGitBashDir = $(if ($dsSettings.bash_path) { Split-Path -Parent ([string]$dsSettings.bash_path) } else { '' })
$dsCli = [string]$dsSettings.devspace_cli
$dsCloudflared = [string]$dsSettings.cloudflared_path
$dsConfigPath = Join-Path $dsSettings.config_dir 'config.json'
$dsTunnelConfig = [string]$dsSettings.tunnel_config
$dsStatePath = Join-Path $dsLogDir 'state.json'
$dsStatusPath = Join-Path $dsLogDir 'status.json'
$dsWatchLog = Join-Path $dsLogDir 'heartbeat.log'
$dsTunnelName = [string]$dsSettings.tunnel_id
$dsProcessTitle = 'soft-heartdevspace-' + $dsSettings.instance_id
$dsMutex = New-Object System.Threading.Mutex($false, ('Local\SoftHeartDevSpace-' + $dsSettings.instance_id))
$dsLocked = $false
$dsState = $null

function Rotate-Log([string]$Path, [long]$LimitBytes = 0) {
    if ((Test-Path -LiteralPath $Path) -and (Get-Item -LiteralPath $Path).Length -gt $LimitBytes) {
        Move-Item -LiteralPath $Path -Destination ($Path + '.previous') -Force
    }
}
function Write-WatchLog([string]$Message) {
    Rotate-Log $dsWatchLog 2097152
    Add-Content -LiteralPath $dsWatchLog -Encoding UTF8 -Value ('{0:o} {1}' -f [DateTime]::UtcNow, $Message)
}
function Write-JsonAtomic($Value, [string]$Path) {
    $stage = $Path + '.pending'
    $Value | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $stage -Encoding UTF8
    Move-Item -LiteralPath $stage -Destination $Path -Force
}
function Get-ManagedProcess([string]$Component) {
    if ($Component -eq 'node') {
        Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object {
            $_.ExecutablePath -eq $dsNode -and $_.CommandLine -and
            $_.CommandLine.Contains($dsCli) -and $_.CommandLine.Contains('--title=' + $dsProcessTitle) -and $_.CommandLine -match '\bserve\b'
        }
    } else {
        Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" | Where-Object {
            $_.ExecutablePath -eq $dsCloudflared -and $_.CommandLine -and
            $_.CommandLine.Contains($dsTunnelConfig) -and
            $_.CommandLine -match ('\brun\s+' + [regex]::Escape($dsTunnelName) + '(\s|$)')
        }
    }
}
function Test-Health([string]$Url, [bool]$IsTunnel = $false, [bool]$UseProxy = $false) {
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $UseProxy
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(8)
    $client.DefaultRequestHeaders.UserAgent.ParseAdd('DevSpaceHeartbeat/1.1')
    $cachePolicy = New-Object System.Net.Http.Headers.CacheControlHeaderValue
    $cachePolicy.NoCache = $true
    $client.DefaultRequestHeaders.CacheControl = $cachePolicy
    $response = $null
    try {
        $response = $client.GetAsync($Url).GetAwaiter().GetResult()
        $code = [int]$response.StatusCode
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $valid = $false
        if ($code -eq 200) {
            try {
                $json = $body | ConvertFrom-Json
                if ($IsTunnel) { $valid = ([int]$json.readyConnections -gt 0) }
                else { $valid = ($json.ok -eq $true -and $json.name -eq 'devspace') }
            } catch { $valid = $false }
        }
        return @{healthy=$valid; httpStatus=$code}
    } catch { return @{healthy=$false; httpStatus=0} }
    finally {
        if ($null -ne $response) { $response.Dispose() }
        $client.Dispose()
        $handler.Dispose()
    }
}
function Get-SinceRecovery([string]$Stamp) {
    if ([string]::IsNullOrWhiteSpace($Stamp)) { return [double]::PositiveInfinity }
    return ([DateTime]::UtcNow - [DateTime]::Parse($Stamp).ToUniversalTime()).TotalSeconds
}
function Invoke-Recovery([string]$Component, [string]$Action, [string]$Reason) {
    $current = @(Get-ManagedProcess $Component)
    if ($current.Count -gt 1) { throw "Multiple matching $Component processes; recovery deferred." }
    if ($Action -eq 'Start' -and $current.Count -gt 0) { return }
    $dsState[$Component + 'LastRecoveryUtc'] = [DateTime]::UtcNow.ToString('o')
    if ($Action -eq 'Restart' -and $current.Count -eq 1) {
        $observed = $current[0]
        $confirmed = @(Get-ManagedProcess $Component | Where-Object {
            $_.ProcessId -eq $observed.ProcessId -and $_.CreationDate -eq $observed.CreationDate
        })
        if ($confirmed.Count -ne 1) { throw "$Component process identity changed; recovery deferred." }
        Write-WatchLog ("Stopping $Component PID={0}; reason=$Reason" -f $observed.ProcessId)
        Stop-Process -Id $observed.ProcessId -Force -ErrorAction Stop
        Wait-Process -Id $observed.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
    }
    if ($Component -eq 'node') {
        foreach ($path in @($dsNode, $dsCli, $dsConfigPath, (Join-Path $dsGitBashDir 'bash.exe'))) {
            if (-not (Test-Path -LiteralPath $path)) { throw "Required runtime missing: $path" }
        }
        $config = Get-Content -LiteralPath $dsConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $workdir = [string]$config.allowedRoots[0]
        if (-not (Test-Path -LiteralPath $workdir -PathType Container)) { throw "Workspace unavailable: $workdir" }
        # Avoid starting a second server when another process owns the expected port.
        $listener = @(Get-NetTCPConnection -State Listen -LocalPort $dsSettings.port -ErrorAction SilentlyContinue)
        if ($listener.Count -gt 0) { throw 'Service port occupied by another process; choose a free port.' }
        Set-DevSpaceEnvironment $dsSettings
        $env:Path = $dsGitBashDir + ';' + (Split-Path -Parent $dsNode) + ';' + $env:Path
        Rotate-Log (Join-Path $dsLogDir 'devspace.log')
        Rotate-Log (Join-Path $dsLogDir 'devspace.err')
        $started = Start-Process -FilePath $dsNode -ArgumentList ('--title={0} "{1}" serve' -f $dsProcessTitle, $dsCli) -WorkingDirectory $workdir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dsLogDir 'devspace.log') -RedirectStandardError (Join-Path $dsLogDir 'devspace.err') -PassThru
    } else {
        foreach ($path in @($dsCloudflared, $dsTunnelConfig)) {
            if (-not (Test-Path -LiteralPath $path)) { throw "Required tunnel path missing: $path" }
        }
        Rotate-Log (Join-Path $dsLogDir 'cf-local.log')
        Rotate-Log (Join-Path $dsLogDir 'cf-local.err')
        $started = Start-Process -FilePath $dsCloudflared -ArgumentList ('--config "{0}" tunnel --metrics 127.0.0.1:{2} run {1}' -f $dsTunnelConfig, $dsTunnelName, $dsSettings.metrics_port) -WorkingDirectory $dsLogDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dsLogDir 'cf-local.log') -RedirectStandardError (Join-Path $dsLogDir 'cf-local.err') -PassThru
    }
    $dsState[$Component + 'Failures'] = 0
    if ($Component -eq 'tunnel') { $dsState.publicFailures = 0 }
    Write-WatchLog ("$Action $Component PID={0}; reason=$Reason" -f $started.Id)
}

try {
    try { $dsLocked = $dsMutex.WaitOne($(if ($ManualStop) { 15000 } else { 0 })) }
    catch [System.Threading.AbandonedMutexException] { $dsLocked = $true }
    if (-not $dsLocked) { if ($ManualStop) { throw 'Heartbeat busy. Try Stop again.' }; exit 0 }
    New-Item -ItemType Directory -Path $dsLogDir -Force | Out-Null
    if ($ManualStop) {
        foreach ($component in @('node','tunnel')) {
            foreach ($observed in @(Get-ManagedProcess $component)) {
                $confirmed = @(Get-ManagedProcess $component | Where-Object { $_.ProcessId -eq $observed.ProcessId -and $_.CreationDate -eq $observed.CreationDate })
                if ($confirmed.Count -eq 1) { Stop-Process -Id $observed.ProcessId -Force -ErrorAction Stop }
            }
        }
        Write-JsonAtomic @{checkedAtUtc=[DateTime]::UtcNow.ToString('o');paused=$true;checkIntervalSeconds=30} $dsStatusPath
        Write-WatchLog 'Connection stopped by user.'
        exit 0
    }
    if (-not $dsSettings.enabled) { exit 0 }
    Add-Type -AssemblyName System.Net.Http
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $dsState = @{nodeFailures=0; tunnelFailures=0; publicFailures=0;
        nodeLastRecoveryUtc=''; tunnelLastRecoveryUtc=''; lastSummary='';
        heartbeatCount=0; lastHealthyUtc=''}
    if (Test-Path -LiteralPath $dsStatePath) {
        try {
            $saved = Get-Content -LiteralPath $dsStatePath -Raw | ConvertFrom-Json
            foreach ($key in @($dsState.Keys)) {
                if ($null -ne $saved.$key) { $dsState[$key] = $saved.$key }
            }
        } catch { Write-WatchLog 'Recovery counters reset after unreadable state file.' }
    }
    $nodeProcesses = @(Get-ManagedProcess 'node')
    $tunnelProcesses = @(Get-ManagedProcess 'tunnel')
    $localHealth = Test-Health ('http://127.0.0.1:{0}/healthz' -f $dsSettings.port)
    $tunnelHealth = Test-Health ('http://127.0.0.1:{0}/ready' -f $dsSettings.metrics_port) $true
    $config = Get-Content -LiteralPath $dsConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $publicUrl = ([string]$config.publicBaseUrl).TrimEnd('/') + '/healthz'
    $publicHealth = Test-Health $publicUrl $false $true
    $dsState.heartbeatCount = [long]$dsState.heartbeatCount + 1
    if ($localHealth.healthy -and $tunnelHealth.healthy -and $publicHealth.healthy) {
        $dsState.lastHealthyUtc = [DateTime]::UtcNow.ToString('o')
    }
    $dsState.nodeFailures = $(if ($localHealth.healthy) { 0 } else { [int]$dsState.nodeFailures + 1 })
    $dsState.tunnelFailures = $(if ($tunnelHealth.healthy) { 0 } else { [int]$dsState.tunnelFailures + 1 })
    $dsState.publicFailures = $(if ($publicHealth.healthy -or -not $localHealth.healthy -or -not $tunnelHealth.healthy) { 0 } else { [int]$dsState.publicFailures + 1 })
    $decisions = @{}
    foreach ($component in @('node','tunnel')) {
        if ($component -eq 'node') { $processes = @($nodeProcesses) }
        else { $processes = @($tunnelProcesses) }
        $health = $(if ($component -eq 'node') { $localHealth } else { $tunnelHealth })
        $age = 0
        if ($processes.Count -eq 1) { $age = ([DateTime]::Now - $processes[0].CreationDate).TotalSeconds }
        $since = Get-SinceRecovery $dsState[$component + 'LastRecoveryUtc']
        $decision = Get-RecoveryDecision $processes.Count $health.healthy $dsState[$component + 'Failures'] $age $since
        $reason = 'process absent or repeated health failure'
        if ($component -eq 'tunnel' -and $decision -eq 'Healthy' -and
            (Get-PublicRecoveryDecision $localHealth.healthy $tunnelHealth.healthy $dsState.publicFailures $publicHealth.httpStatus $since)) {
            $decision = 'Restart'
            $reason = 'five consecutive public connection failures'
        }
        $decisions[$component] = $decision
        if ($decision -in @('Start','Restart')) { Invoke-Recovery $component $decision $reason }
    }
    $summary = 'local={0}; tunnel={1}; public={2}; nodeAction={3}; tunnelAction={4}' -f $localHealth.healthy,$tunnelHealth.healthy,$publicHealth.healthy,$decisions.node,$decisions.tunnel
    Write-WatchLog ('Heartbeat #{0}: {1}' -f $dsState.heartbeatCount, $summary)
    $dsState.lastSummary = $summary
    Write-JsonAtomic @{checkedAtUtc=[DateTime]::UtcNow.ToString('o'); checkIntervalSeconds=30;
        local=$localHealth; tunnel=$tunnelHealth; public=$publicHealth; decisions=$decisions;
        nodePids=@(Get-ManagedProcess 'node' | ForEach-Object {$_.ProcessId});
        tunnelPids=@(Get-ManagedProcess 'tunnel' | ForEach-Object {$_.ProcessId});
        state=$dsState} $dsStatusPath
} catch {
    try { Write-WatchLog ('Check failed: ' + $_.Exception.Message) } catch {}
    exit 1
} finally {
    if ($dsLocked) {
        if ($null -ne $dsState) { Write-JsonAtomic $dsState $dsStatePath }
        $dsMutex.ReleaseMutex()
    }
    $dsMutex.Dispose()
}
