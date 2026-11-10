# OpenSH - Windows PowerShell Installer
# Based on nlsh (https://github.com/junaid-mahmood/nlsh)
# Support: https://ko-fi.com/ai_dev_2024
#
# Runs as a file (.\install.ps1) or piped (irm <url> | iex). The piped form runs
# inside your own session, so everything lives in a function: settings such as
# $ErrorActionPreference stay local, and the script uses `return`, never `exit`,
# which would close your window.
#
# Keep this file ASCII-only: Windows PowerShell 5.1 misreads UTF-8 without a BOM.

function Install-OpenSH {
    $ErrorActionPreference = "Stop"

    $INSTALL_DIR = Join-Path $env:USERPROFILE ".opsh"
    $REPO_URL = "https://github.com/muhib-karim/OpenSH.git"

    Write-Host "Installing OpenSH..." -ForegroundColor Cyan

    # Find Python 3.9+. Native commands are run with "Continue" so that anything
    # they print on stderr is not turned into a terminating error.
    $pythonCmd = $null
    foreach ($cmd in @("python", "python3", "py")) {
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { continue }
        $ErrorActionPreference = "Continue"
        $version = (& $cmd --version 2>&1 | Out-String).Trim()
        $found = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = "Stop"
        if ($found -and $version -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 9) {
            $pythonCmd = $cmd
            break
        }
    }

    if (-not $pythonCmd) {
        Write-Host "Python 3.9 or newer is required. Please install it from https://python.org" -ForegroundColor Red
        return
    }
    Write-Host "Found ${pythonCmd}: $version" -ForegroundColor Gray

    $haveGit = [bool](Get-Command git -ErrorAction SilentlyContinue)

    # The folder this script was started from. Empty when piped into iex; the
    # current directory is never used as a source.
    $sourceDir = $PSScriptRoot
    $fromSource = $false
    if ($sourceDir -and (Test-Path (Join-Path $sourceDir "opsh.py"))) {
        $fromSource = ((Resolve-Path $sourceDir).Path -ne $INSTALL_DIR)
    }

    $ErrorActionPreference = "Continue"
    if ($fromSource) {
        # Local installation (development mode). Also refreshes an earlier local install.
        Write-Host "Installing from $sourceDir..." -ForegroundColor Gray
        New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null
        foreach ($name in @("opsh.py", "requirements.txt", "uninstall.ps1")) {
            $item = Join-Path $sourceDir $name
            if (Test-Path $item) { Copy-Item $item $INSTALL_DIR -Force }
        }
        # Bring an API key along, but never overwrite one that is already installed.
        $sourceEnv = Join-Path $sourceDir ".env"
        if ((Test-Path $sourceEnv) -and -not (Test-Path (Join-Path $INSTALL_DIR ".env"))) {
            Copy-Item $sourceEnv $INSTALL_DIR
        }
    }
    elseif (Test-Path (Join-Path $INSTALL_DIR ".git")) {
        Write-Host "Updating existing installation..." -ForegroundColor Yellow
        if ($haveGit) {
            & git -C $INSTALL_DIR pull --quiet --ff-only
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Warning: could not update from git. Continuing with existing files." -ForegroundColor Yellow
            }
        }
        else {
            Write-Host "Warning: git not found. Continuing with existing files." -ForegroundColor Yellow
        }
    }
    else {
        if (-not $haveGit) {
            Write-Host "Git is required to download OpenSH. Install it from https://git-scm.com and run this again." -ForegroundColor Red
            return
        }
        if (Test-Path (Join-Path $INSTALL_DIR "opsh.py")) {
            # Installed earlier by copying files: fetch the current program into place.
            Write-Host "Updating existing installation..." -ForegroundColor Yellow
            $tempDir = Join-Path ([IO.Path]::GetTempPath()) ("opsh-" + [Guid]::NewGuid().ToString("N"))
            & git clone --quiet --depth 1 $REPO_URL $tempDir
            if ($LASTEXITCODE -eq 0) {
                foreach ($name in @("opsh.py", "requirements.txt", "uninstall.ps1")) {
                    Copy-Item (Join-Path $tempDir $name) $INSTALL_DIR -Force
                }
            }
            else {
                Write-Host "Warning: could not download the update. Continuing with existing files." -ForegroundColor Yellow
            }
            if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue }
        }
        else {
            Write-Host "Downloading OpenSH..." -ForegroundColor Cyan
            & git clone --quiet --depth 1 $REPO_URL $INSTALL_DIR
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Failed to clone the repository. Please check your internet connection." -ForegroundColor Red
                return
            }
        }
    }

    # Virtual environment: only needed for pyreadline3 (arrow-key history).
    Write-Host "Setting up Python environment..." -ForegroundColor Cyan
    $venvPython = Join-Path $INSTALL_DIR "venv\Scripts\python.exe"
    & $pythonCmd -m venv (Join-Path $INSTALL_DIR "venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        Write-Host "Could not create the Python virtual environment in $INSTALL_DIR\venv." -ForegroundColor Red
        return
    }
    & $venvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $INSTALL_DIR "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Warning: could not install pyreadline3 (arrow-key history). OpenSH works without it." -ForegroundColor Yellow
    }
    $ErrorActionPreference = "Stop"

    # Launcher. It refers to %USERPROFILE% instead of the expanded path, so it also
    # works when the user name contains characters outside ASCII.
    Write-Host "Creating opsh command..." -ForegroundColor Cyan
    $launcherPath = Join-Path $INSTALL_DIR "opsh.cmd"
    $launcherContent = @'
@echo off
"%USERPROFILE%\.opsh\venv\Scripts\python.exe" "%USERPROFILE%\.opsh\opsh.py" %*
'@
    Set-Content -Path $launcherPath -Value $launcherContent -Encoding ASCII

    # Add to PATH if not already there
    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    $entries = @("$userPath" -split ";" | Where-Object { $_ })
    if ($entries -notcontains $INSTALL_DIR) {
        Write-Host "Adding OpenSH to PATH..." -ForegroundColor Cyan
        [Environment]::SetEnvironmentVariable("PATH", ((@($INSTALL_DIR) + $entries) -join ";"), "User")
        $env:PATH = "$INSTALL_DIR;$env:PATH"
    }

    Write-Host ""
    Write-Host "================================================" -ForegroundColor Green
    Write-Host "  OpenSH installed successfully!" -ForegroundColor Green
    Write-Host "================================================" -ForegroundColor Green
    Write-Host ""

    # Auto-start is opt-in. The profile line only fires in an interactive console
    # that was not started to run a script or a command.
    $profilePath = $PROFILE.CurrentUserAllHosts
    $hasAutoStart = $false
    if ($profilePath -and (Test-Path $profilePath)) {
        $profileContent = Get-Content $profilePath -Raw -ErrorAction SilentlyContinue
        if ($profileContent -and $profileContent -match "OpenSH auto-start") {
            $hasAutoStart = $true
        }
    }

    if ($hasAutoStart) {
        Write-Host "Auto-start already configured." -ForegroundColor Gray
    }
    elseif ($profilePath -and [Environment]::UserInteractive) {
        Write-Host "Would you like OpenSH to start automatically in every new terminal?" -ForegroundColor Cyan
        Write-Host "(You can leave it anytime with 'exit' or Ctrl+C to use normal PowerShell)" -ForegroundColor Gray
        Write-Host ""
        $response = ""
        try { $response = Read-Host "Enable auto-start? [y/N]" } catch { $response = "" }

        if ($response -match "^\s*y(es)?\s*$") {
            $profileDir = Split-Path $profilePath -Parent
            if (-not (Test-Path $profileDir)) {
                New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
            }
            $autoStartCode = @'

# OpenSH auto-start (remove these lines to disable)
if ($Host.Name -eq 'ConsoleHost' -and [Environment]::UserInteractive -and -not [Console]::IsInputRedirected -and -not ([Environment]::GetCommandLineArgs() -match '^-(f|file|c|command|e|ec|enc|encodedcommand|noni|noninteractive)$') -and (Test-Path "$env:USERPROFILE\.opsh\opsh.cmd")) { & "$env:USERPROFILE\.opsh\opsh.cmd" }
'@
            Add-Content -Path $profilePath -Value $autoStartCode
            Write-Host ""
            Write-Host "Auto-start enabled. New interactive terminals will start in OpenSH." -ForegroundColor Green
            Write-Host "To disable later, edit: $profilePath" -ForegroundColor Gray
        }
        else {
            Write-Host ""
            Write-Host "Auto-start skipped. Type 'opsh' to start OpenSH." -ForegroundColor Yellow
        }
    }

    Write-Host ""
    Write-Host "To start using OpenSH now:" -ForegroundColor Cyan
    Write-Host "  opsh" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Based on nlsh by Junaid Mahmood" -ForegroundColor DarkGray
    Write-Host "Support: https://ko-fi.com/ai_dev_2024" -ForegroundColor DarkGray
    Write-Host ""
}

Install-OpenSH
