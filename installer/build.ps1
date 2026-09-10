# Build AURA-Installer.exe ~5MB (online-installer, model downloaded at first run)
param(
  [string]$Python = "py -3.11"
)
$ErrorActionPreference = "Stop"
Write-Host "[AURA] Building online-installer..."

# Ensure venv with pyinstaller
if (-not (Test-Path ".venv")) { & $Python -m venv .venv }
.\.venv\Scripts\Activate.ps1
pip install --quiet pyinstaller==6.10 huggingface_hub psutil

# Clean
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue

# Build single-file exe that bundles installer.py only (5MB)
pyinstaller --onefile --name AURA-Installer --console `
  --hidden-import=huggingface_hub --hidden-import=psutil `
  installer\installer.py

Write-Host "[AURA] Built dist\AURA-Installer.exe"
Get-Item dist\AURA-Installer.exe | Format-List Length, Name
Write-Host "Upload dist\AURA-Installer.exe to GitHub Releases (not git push) — 5MB"
