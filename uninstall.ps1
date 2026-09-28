# OpenSH - Windows PowerShell Uninstaller
# Based on nlsh (https://github.com/junaid-mahmood/nlsh)

$INSTALL_DIR = "$env:USERPROFILE\.opsh"

Write-Host "Uninstalling OpenSH..." -ForegroundColor Yellow

# Remove installation directory
if (Test-Path $INSTALL_DIR) {
    Remove-Item -Path $INSTALL_DIR -Recurse -Force
    Write-Host "Removed installation directory" -ForegroundColor Gray
}

# Remove from PATH
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -like "*$INSTALL_DIR*") {
    $newPath = ($userPath -split ";" | Where-Object { $_ -ne $INSTALL_DIR -and $_ -ne "" }) -join ";"
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Host "Removed from PATH" -ForegroundColor Gray
}

# Clean up PowerShell profile if it has OpenSH entries
$profilePath = $PROFILE.CurrentUserAllHosts
if (Test-Path $profilePath) {
    $content = Get-Content $profilePath -Raw
    if ($content -match "OpenSH") {
        $newContent = $content -replace "# OpenSH auto-start.*\r?\n.*opsh.*\r?\n?", ""
        Set-Content -Path $profilePath -Value $newContent
        Write-Host "Cleaned up PowerShell profile" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "OpenSH has been removed" -ForegroundColor Green
Write-Host ""
