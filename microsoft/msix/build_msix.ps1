<#
.SYNOPSIS
  Wraps the existing PyInstaller output (dist\TypeSenseLogger\) into an
  unsigned .msix, using this folder's AppxManifest.xml and Assets\.

.NOTES
  Requires makeappx.exe from the Windows SDK - NOT Visual Studio. Get it via
  either:
    - the standalone Windows SDK installer (https://developer.microsoft.com/windows/downloads/windows-sdk/),
      selecting only the "Windows App Certification Kit" / "MSIX Packaging Tools" component, or
    - winget: winget install Microsoft.WindowsSDK
  Typical install path once present:
    C:\Program Files (x86)\Windows Kits\10\bin\<version>\x64\makeappx.exe

  Run build.bat first so dist\TypeSenseLogger\TypeSenseLogger.exe exists and
  is current.
#>

param(
    [string]$MakeAppxPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path

if (-not $MakeAppxPath) {
    $sdkRoot = "C:\Program Files (x86)\Windows Kits\10\bin"
    $found = $null
    if (Test-Path $sdkRoot) {
        $found = Get-ChildItem $sdkRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "x64\makeappx.exe" } |
            Where-Object { Test-Path $_ } |
            Select-Object -First 1
    }
    if (-not $found) {
        throw "makeappx.exe not found under $sdkRoot. Install the Windows SDK (MSIX Packaging Tools component) or pass -MakeAppxPath explicitly."
    }
    $MakeAppxPath = $found
}

$distExe = Join-Path $RepoRoot "dist\TypeSenseLogger"
$exePath = Join-Path $distExe "TypeSenseLogger.exe"
if (-not (Test-Path $exePath)) {
    throw "$exePath not found - run build.bat from the repo root first."
}

$configPath = Join-Path $RepoRoot "config.json"
if (-not (Test-Path $configPath)) {
    throw "$configPath not found - this needs to exist (with real server_url/secret_token) before packaging, same as build.bat expects."
}

$manifestPath = Join-Path $PSScriptRoot "AppxManifest.xml"
if ((Get-Content $manifestPath -Raw) -match "REPLACE_WITH_PARTNER_CENTER") {
    Write-Warning "AppxManifest.xml still has REPLACE_WITH_PARTNER_CENTER_* placeholders. The package will build, but won't ingest into Partner Center or sideload with the right identity until you fill those in."
}

$stage = Join-Path $env:TEMP "TypeSenseMsixStage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

Copy-Item "$distExe\*" $stage -Recurse
Copy-Item $configPath $stage
Copy-Item $manifestPath $stage
Copy-Item (Join-Path $PSScriptRoot "Assets") $stage -Recurse

$outDir = Join-Path $PSScriptRoot "dist"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
$outFile = Join-Path $outDir "TypeSense.msix"

& $MakeAppxPath pack /d $stage /p $outFile /overwrite
if ($LASTEXITCODE -ne 0) {
    throw "makeappx pack failed (exit $LASTEXITCODE)."
}

Write-Host ""
Write-Host "Built: $outFile"
Write-Host ""
Write-Host "This package is UNSIGNED. To sideload/test locally, sign it first:"
Write-Host "  signtool sign /fd SHA256 /a /f <your-cert.pfx> /p <password> `"$outFile`""
Write-Host "The signing certificate's subject must exactly match the Publisher"
Write-Host "value in AppxManifest.xml (CN=...), or Add-AppxPackage will refuse it."
Write-Host ""
Write-Host "Partner Center re-signs on ingestion, so an unsigned .msix is fine"
Write-Host "to upload directly there - Partner Center accepts a plain .msix,"
Write-Host "a .msixupload bundle is only needed if you're submitting multiple"
Write-Host "architectures in one package."
