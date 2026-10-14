# Builds dist\Hard2Gesture-Setup-<version>.exe: the app bundled by PyInstaller, then
# wrapped in a Windows installer by Inno Setup. The version comes from hard2gesture\__init__.py.
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
# --no-cache-dir: the Microsoft Store Python's pip cache path is too long for some packages to build.
Invoke-Native $python -m pip install --quiet --disable-pip-version-check --no-cache-dir -r requirements-dev.txt

Write-Host '== Running tests'
Invoke-Native $python -m pytest -q -p no:cacheprovider

Write-Host '== Preparing hand model'
Invoke-Native $python -c 'from hard2gesture.hand_tracker import download_model_if_missing; download_model_if_missing()'
$version = & $python -c 'import hard2gesture; print(hard2gesture.__version__)'
$fileVersion = [regex]::Match($version, '^\d+(\.\d+)*').Value  # 2.0.0b1 -> 2.0.0

Write-Host '== Bundling app with PyInstaller'
Invoke-Native $python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller installer\Hard2Gesture.spec
Invoke-Native $python tools\collect_licenses.py dist\Hard2Gesture

Write-Host "== Compiling installer (version $version)"
Invoke-Native $iscc /Q "/DAppVersion=$version" "/DFileVersion=$fileVersion" installer\Hard2Gesture.iss

Write-Host "`nDone: dist\Hard2Gesture-Setup-$version.exe"
