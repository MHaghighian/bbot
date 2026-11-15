# Build standalone bbot.exe for Windows (no admin/UAC required)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
Remove-Item Env:HTTP_PROXY, Env:HTTPS_PROXY, Env:http_proxy, Env:https_proxy, Env:ALL_PROXY -ErrorAction SilentlyContinue

Write-Host "==> Syncing runtime dependencies..."
uv sync --python 3.12 --no-dev

Write-Host "==> Installing PyInstaller..."
uv pip install pyinstaller

$OutDir = Join-Path $Root "dist\windows"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Write-Host "==> Building bbot.exe..."
uv run --no-dev pyinstaller `
    --noconfirm `
    --clean `
    --distpath $OutDir `
    --workpath (Join-Path $Root "build\windows") `
    (Join-Path $Root "windows\bbot.spec")

$Exe = Join-Path $OutDir "bbot.exe"
if (-not (Test-Path $Exe)) {
    throw "Build failed: $Exe not found"
}

Write-Host ""
Write-Host "Built: $Exe"
Write-Host "Size : $([math]::Round((Get-Item $Exe).Length / 1MB, 1)) MB"
Write-Host ""
Write-Host "Run examples (no admin needed):"
Write-Host "  $Exe --help"
Write-Host "  $Exe -t example.com -m crt --yes"
Write-Host "  $Exe -t example.com -p subdomain-enum -rf passive --yes"
