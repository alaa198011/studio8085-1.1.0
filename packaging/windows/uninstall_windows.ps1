# Removes the per-user install made by install_windows.ps1
$app = Join-Path $env:LOCALAPPDATA "8085 Studio"
$lnk = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\8085 Studio.lnk"
if (Test-Path $app) { Remove-Item -Recurse -Force $app }
if (Test-Path $lnk) { Remove-Item -Force $lnk }
Write-Host "8085 Studio removed. Settings live in the registry under HKCU\Software\Studio8085."
