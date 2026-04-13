# scripts/uninstall_autostart.ps1
# Removes the Jarvis shell:startup shortcut.
# Run: powershell -ExecutionPolicy Bypass -File scripts\uninstall_autostart.ps1

$WshShell = New-Object -ComObject WScript.Shell
$StartupFolder = $WshShell.SpecialFolders("Startup")
$ShortcutPath = Join-Path $StartupFolder "Jarvis.lnk"

if (Test-Path $ShortcutPath) {
    Remove-Item $ShortcutPath -Force
    Write-Host "Removed shortcut: $ShortcutPath"
} else {
    Write-Host "No Jarvis shortcut found at: $ShortcutPath"
}
