# Builds dist\HandGestures-Setup-<version>.exe: the app bundled by PyInstaller, then
# wrapped in a Windows installer by Inno Setup. The version comes from handgestures\__init__.py.
#
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Invoke-Native {
    # PowerShell doesn't stop on a failing native command, so check its exit code.
    $exe, $rest = $args
    & $exe @rest
    if ($LASTEXITCODE -ne 0) { throw "$exe exited with code $LASTEXITCODE" }
}

$iscc = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup' }

$python = "$root\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host '== Creating .venv'
    Invoke-Native python -m venv .venv
}
Write-Host '== Installing dependencies'
Invoke-Native $python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt

Write-Host '== Preparing hand model and icon'
New-Item -ItemType Directory -Force build | Out-Null
Invoke-Native $python -c 'from handgestures.hand_tracker import download_model_if_missing; download_model_if_missing()'
Invoke-Native $python -c "from handgestures.tray_icon import save_icon_file; save_icon_file('build/icon.ico')"
$version = & $python -c 'import handgestures; print(handgestures.__version__)'
$fileVersion = [regex]::Match($version, '^\d+(\.\d+)*').Value  # 1.0.2BETA -> 1.0.2

Write-Host '== Bundling app with PyInstaller'
Invoke-Native $python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller installer\HandGestures.spec

Write-Host "== Compiling installer (version $version)"
Invoke-Native $iscc /Q "/DAppVersion=$version" "/DFileVersion=$fileVersion" installer\HandGestures.iss

Write-Host "`nDone: dist\HandGestures-Setup-$version.exe"
