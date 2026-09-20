# openEMS Build Script for Windows
# This script will install dependencies and compile openEMS
# Usage:
#   .\scripts\build_openems.ps1 [-OpenemsRoot "D:\openEMS"]
# (OpenemsRoot is the per-machine install root; defaults to D:\openEMS and is
#  also configurable via the OPENEMS_ROOT environment variable.)

param(
    [string]$OpenemsRoot = $(if ($env:OPENEMS_ROOT) { $env:OPENEMS_ROOT } else { "D:\openEMS" })
)

Write-Host "=== openEMS Build Script ===" -ForegroundColor Cyan
Write-Host "This will take 30-60 minutes to complete." -ForegroundColor Yellow
Write-Host ""

# Check prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor Cyan

# Check CMake
$cmake = Get-Command cmake -ErrorAction SilentlyContinue
if (-not $cmake) {
    Write-Host "ERROR: CMake not found. Please install CMake first." -ForegroundColor Red
    Write-Host "  winget install Kitware.CMake" -ForegroundColor Yellow
    exit 1
}
Write-Host "  CMake: OK" -ForegroundColor Green

# Check Visual Studio Build Tools
$vsPath = "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat"
if (-not (Test-Path $vsPath)) {
    $vsPath = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat"
}
if (-not (Test-Path $vsPath)) {
    Write-Host "ERROR: Visual Studio Build Tools not found." -ForegroundColor Red
    Write-Host "  winget install Microsoft.VisualStudio.2022.BuildTools" -ForegroundColor Yellow
    exit 1
}
Write-Host "  Visual Studio Build Tools: OK" -ForegroundColor Green

# Set up environment
Write-Host "Setting up build environment..." -ForegroundColor Cyan
& $vsPath x64

# Clone openEMS-Project if not exists
$openemsDir = Join-Path $OpenemsRoot "openEMS-Project"
if (-not (Test-Path $openemsDir)) {
    Write-Host "Cloning openEMS-Project..." -ForegroundColor Cyan
    git clone https://github.com/thliebig/openEMS-Project.git $openemsDir
}

# Build using the provided script
Write-Host "Building openEMS..." -ForegroundColor Cyan
cd $openemsDir

# Run the update script (handles all dependencies)
if (Test-Path ".\update_openEMS.sh") {
    bash .\update_openEMS.sh
} else {
    Write-Host "ERROR: update_openEMS.sh not found" -ForegroundColor Red
    exit 1
}

Write-Host "Build complete!" -ForegroundColor Green
Write-Host "openEMS installed to: $openemsDir" -ForegroundColor Cyan
