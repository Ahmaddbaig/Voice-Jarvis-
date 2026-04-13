# scripts/install_autostart.ps1
# Creates a shell:startup shortcut for Jarvis background mode (PROC-09).
# Run: powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1

param(
    [string]$ProjectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

# Resolve pythonw.exe in the project's .venv
$PythonW = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $PythonW)) {
    Write-Error "pythonw.exe not found at $PythonW"
    exit 1
}

# Resolve the entry point
$EntryPoint = Join-Path $ProjectRoot "src\jarvis.pyw"
if (-not (Test-Path $EntryPoint)) {
    Write-Error "jarvis.pyw not found at $EntryPoint"
    exit 1
}

# Create the shortcut in the user's Startup folder
$WshShell = New-Object -ComObject WScript.Shell
$StartupFolder = $WshShell.SpecialFolders("Startup")
$ShortcutPath = Join-Path $StartupFolder "Jarvis.lnk"

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PythonW
$Shortcut.Arguments = "`"$EntryPoint`""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = "Jarvis Voice Assistant (background)"
$Shortcut.Save()

Write-Host "Shortcut created at: $ShortcutPath"
Write-Host "  Target: $PythonW"
Write-Host "  Args:   $EntryPoint"
Write-Host "  CWD:    $ProjectRoot"
