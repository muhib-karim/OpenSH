# OpenSH - Windows PowerShell Installer
# Based on nlsh (https://github.com/junaid-mahmood/nlsh)
# Support: https://ko-fi.com/ai_dev_2024

$ErrorActionPreference = "Stop"

$INSTALL_DIR = "$env:USERPROFILE\.opsh"
$REPO_URL = "https://github.com/ai-dev-2024/OpenSH.git"

Write-Host "Installing OpenSH..." -ForegroundColor Cyan

# Check for Python
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $version = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $version -match "Python 3") {
            $pythonCmd = $cmd
            break
        }
    }
    catch {}
}

if (-not $pythonCmd) {
    Write-Host "Python 3 is required. Please install it from https://python.org" -ForegroundColor Red
    exit 1
}

Write-Host "Found $($pythonCmd): $((& $pythonCmd --version 2>&1))" -ForegroundColor Gray

# Install from a local checkout when run as a file (.\install.ps1).
# Under `irm ... | iex` there is no script path, so download with git instead.
$scriptPath = if ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { $null }
$isLocal = $scriptPath -and (Test-Path "$scriptPath\opsh.py") -and ($scriptPath -ne $INSTALL_DIR)

if ($isLocal) {
    # Local installation (development mode) - always copy the current source files
    Write-Host "Installing from local directory..." -ForegroundColor Gray
    New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null
    Copy-Item "$scriptPath\opsh.py" "$INSTALL_DIR\" -Force
    Copy-Item "$scriptPath\requirements.txt" "$INSTALL_DIR\" -Force
    # Don't replace API keys that an existing install already has
    if ((Test-Path "$scriptPath\.env") -and -not (Test-Path "$INSTALL_DIR\.env")) {
        Copy-Item "$scriptPath\.env" "$INSTALL_DIR\" -Force
    }
}
elseif (Test-Path "$INSTALL_DIR\.git") {
    Write-Host "Updating existing installation..." -ForegroundColor Yellow
    Push-Location $INSTALL_DIR
    try {
        git pull --quiet 2>&1 | Out-Null
    }
    catch {
        Write-Host "Warning: Could not update from git. Continuing with existing files." -ForegroundColor Yellow
    }
    Pop-Location
}
elseif (Test-Path "$INSTALL_DIR\opsh.py") {
    Write-Host "Warning: $INSTALL_DIR was installed from a local checkout and can't be updated here." -ForegroundColor Yellow
    Write-Host "Run .\install.ps1 from that checkout, or delete $INSTALL_DIR and run this installer again." -ForegroundColor Yellow
}
else {
    # Remote installation
    Write-Host "Downloading OpenSH..." -ForegroundColor Cyan
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "git is required to download OpenSH. Install it from https://git-scm.com" -ForegroundColor Red
        exit 1
    }
    try {
        git clone --quiet $REPO_URL $INSTALL_DIR 2>&1 | Out-Null
    }
    catch {}
    if (-not (Test-Path "$INSTALL_DIR\opsh.py")) {
        Write-Host "Failed to clone repository. Please check your internet connection." -ForegroundColor Red
        exit 1
    }
}

Push-Location $INSTALL_DIR

# Create Python virtual environment
Write-Host "Setting up Python environment..." -ForegroundColor Cyan

# Check exit codes of native commands instead of letting their stderr output
# stop the script (Windows PowerShell 5.1 turns it into errors under "Stop")
$ErrorActionPreference = "Continue"
& $pythonCmd -m venv venv
$venvPython = "$INSTALL_DIR\venv\Scripts\python.exe"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
    Write-Host "Failed to create a Python virtual environment." -ForegroundColor Red
    Pop-Location
    exit 1
}

# pip must be upgraded via "python -m pip" on Windows (pip.exe cannot replace itself)
& $venvPython -m pip install --quiet --upgrade pip 2>&1 | Out-Null
& $venvPython -m pip install --quiet -r "$INSTALL_DIR\requirements.txt" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to install Python dependencies." -ForegroundColor Red
    Pop-Location
    exit 1
}
$ErrorActionPreference = "Stop"

Pop-Location

# Create launcher batch file
Write-Host "Creating opsh command..." -ForegroundColor Cyan

# %~dp0 is the launcher's own folder, so the (ASCII) file needs no user profile path
$launcherContent = @'
@echo off
call "%~dp0venv\Scripts\activate.bat"
python "%~dp0opsh.py" %*
'@

$launcherPath = "$INSTALL_DIR\opsh.cmd"
Set-Content -Path $launcherPath -Value $launcherContent -Encoding ASCII

# Add to PATH if not already there
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$INSTALL_DIR*") {
    Write-Host "Adding OpenSH to PATH..." -ForegroundColor Cyan
    $newUserPath = if ($userPath) { "$INSTALL_DIR;$userPath" } else { $INSTALL_DIR }
    [Environment]::SetEnvironmentVariable("PATH", $newUserPath, "User")
    $env:PATH = "$INSTALL_DIR;$env:PATH"
}

# Ask about auto-start in new terminals
Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  OpenSH installed successfully!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""

$profilePath = $PROFILE.CurrentUserAllHosts
$autoStartMarker = "# OpenSH auto-start"

# Check if auto-start already configured
$hasAutoStart = $false
if (Test-Path $profilePath) {
    $profileContent = Get-Content $profilePath -Raw -ErrorAction SilentlyContinue
    if ($profileContent -and $profileContent -match "OpenSH auto-start") {
        $hasAutoStart = $true
    }
}

if (-not $hasAutoStart) {
    Write-Host "Would you like OpenSH to start automatically in every new terminal?" -ForegroundColor Cyan
    Write-Host "(You can exit anytime with 'exit' or Ctrl+C to use normal PowerShell)" -ForegroundColor Gray
    Write-Host ""
    $response = Read-Host "Enable auto-start? [Y/n]"
    
    if ($response -ne "n" -and $response -ne "N") {
        # Create profile directory if needed
        $profileDir = Split-Path $profilePath -Parent
        if (-not (Test-Path $profileDir)) {
            New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
        }
        
        # Add auto-start to profile
        $autoStartCode = @"

# OpenSH auto-start (remove these lines to disable)
if (`$Host.Name -eq 'ConsoleHost' -and -not [Console]::IsInputRedirected -and (Test-Path "`$env:USERPROFILE\.opsh\opsh.cmd")) { & "`$env:USERPROFILE\.opsh\opsh.cmd" }
"@
        Add-Content -Path $profilePath -Value $autoStartCode
        Write-Host ""
        Write-Host "Auto-start enabled! Every new terminal will start in OpenSH mode." -ForegroundColor Green
        Write-Host "To disable later, edit: $profilePath" -ForegroundColor Gray
    }
    else {
        Write-Host ""
        Write-Host "Auto-start skipped. Type 'opsh' to start OpenSH manually." -ForegroundColor Yellow
    }
}
else {
    Write-Host "Auto-start already configured." -ForegroundColor Gray
}

Write-Host ""
Write-Host "To start using OpenSH now:" -ForegroundColor Cyan
Write-Host "  opsh" -ForegroundColor Yellow
Write-Host ""
Write-Host "Based on nlsh by Junaid Mahmood" -ForegroundColor DarkGray
Write-Host "Support: https://ko-fi.com/ai_dev_2024" -ForegroundColor DarkGray
Write-Host ""
