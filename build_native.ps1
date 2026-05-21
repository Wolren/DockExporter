param(
    [switch]$Release,
    [switch]$Test
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition

Set-Location -LiteralPath "$ProjectRoot\woof_native"

if ($Test) {
    Write-Host "Running cargo test..." -ForegroundColor Green
    cargo test
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($Release) {
    Write-Host "Building release wheel..." -ForegroundColor Green
    maturin build --release --out "$ProjectRoot\dist"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Extracting .pyd to dock_export/_woof_native/..." -ForegroundColor Green
    $wheel = Get-ChildItem "$ProjectRoot\dist\_woof_native-*.whl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($wheel) {
        $tmp = Join-Path $env:TEMP "woof_extract_$(Get-Random)"
        Expand-Archive -Path $wheel.FullName -DestinationPath $tmp -Force
        $ext = if ($IsWindows -or (-not $IsLinux -and -not $IsMacOs)) { ".pyd" } elseif ($IsMacOs) { ".dylib" } else { ".so" }
        $bin = Get-ChildItem -Recurse -LiteralPath $tmp -Filter "*_native_impl*$ext" | Select-Object -First 1
        if ($bin) {
            Copy-Item -LiteralPath $bin.FullName -Destination "$ProjectRoot\dock_export\_woof_native\_native_impl$ext" -Force
            Write-Host "Copied to dock_export/_woof_native/" -ForegroundColor Green
        } else {
            Write-Warning "No native binary found in wheel"
        }
        Remove-Item -LiteralPath $tmp -Recurse -Force
    }
} else {
    Write-Host "Running maturin develop (debug)..." -ForegroundColor Green
    maturin develop
}
