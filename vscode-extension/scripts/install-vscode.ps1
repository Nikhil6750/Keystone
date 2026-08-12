# Install Keystone VS Code extension VSIX locally
$ErrorActionPreference = "Stop"

$vsixFiles = Get-ChildItem -Path "$PSScriptRoot/.." -Filter "*.vsix" | Sort-Object LastWriteTime -Descending

if ($vsixFiles.Count -eq 0) {
    Write-Host "No .vsix package found. Run 'npm run package' first." -ForegroundColor Red
    exit 1
}

$latestVsix = $vsixFiles[0].FullName
Write-Host "Found VSIX package: $latestVsix" -ForegroundColor Green

$codeCmd = Get-Command code -ErrorAction SilentlyContinue

if ($null -ne $codeCmd) {
    Write-Host "Installing extension into VS Code..." -ForegroundColor Cyan
    code --install-extension $latestVsix --force
    Write-Host "Extension installed successfully!" -ForegroundColor Green
} else {
    Write-Host "'code' CLI command not found in PATH." -ForegroundColor Yellow
    Write-Host "To install manually in VS Code / Antigravity:" -ForegroundColor Cyan
    Write-Host "  1. Open Extensions sidebar (Ctrl+Shift+X)" -ForegroundColor White
    Write-Host "  2. Click '...' (Views & More Actions)" -ForegroundColor White
    Write-Host "  3. Select 'Install from VSIX...'" -ForegroundColor White
    Write-Host "  4. Choose: $latestVsix" -ForegroundColor White
}
