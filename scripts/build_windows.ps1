param([string]$Python='python', [Parameter(Mandatory=$true)][string]$BuildRoot)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
$work=Join-Path $BuildRoot 'work'
$spec=Join-Path $BuildRoot 'spec'
$dist=Join-Path $repo 'dist'
New-Item -ItemType Directory -Path $work,$spec,$dist -Force | Out-Null
Push-Location $repo
try {
    $webData=(Join-Path $repo 'heartdevspace\web') + ';heartdevspace/web'
    $runtimeData=(Join-Path $repo 'heartdevspace\runtime') + ';heartdevspace/runtime'
    $env:PYINSTALLER_CONFIG_DIR=Join-Path $BuildRoot 'cache'
    & $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name Soft-HeartDevSpace --add-data $webData --add-data $runtimeData --workpath $work --specpath $spec --distpath $dist launch.py
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
    foreach ($name in @('README.md','README.zh-CN.md','LICENSE','NOTICE','docs')) { Copy-Item -LiteralPath (Join-Path $repo $name) -Destination (Join-Path $dist 'Soft-HeartDevSpace') -Recurse -Force }
    $pythonBase = & $Python -c 'import sys; print(sys.base_prefix)'
    Copy-Item -LiteralPath (Join-Path $pythonBase 'LICENSE.txt') -Destination (Join-Path $dist 'Soft-HeartDevSpace\PYTHON-LICENSE.txt')
    $logoDir=Join-Path $dist 'Soft-HeartDevSpace\heartdevspace\web'
    New-Item -ItemType Directory -Path $logoDir -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repo 'heartdevspace\web\logo.svg') -Destination $logoDir
    $sourceDir=Join-Path $dist 'Soft-HeartDevSpace\scripts'
    New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repo 'scripts\draw_overview.R') -Destination $sourceDir
    Compress-Archive -Path (Join-Path $dist 'Soft-HeartDevSpace') -DestinationPath (Join-Path $dist 'Soft-HeartDevSpace-0.1.0-windows-x64.zip') -Force
    $archive=Join-Path $dist 'Soft-HeartDevSpace-0.1.0-windows-x64.zip'
    ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower() + '  ' + (Split-Path $archive -Leaf)) | Set-Content -LiteralPath (Join-Path $dist 'SHA256SUMS.txt') -Encoding ASCII
} finally { Pop-Location }
