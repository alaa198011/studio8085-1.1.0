# Installs 8085 Studio for the current user (no administrator rights needed).
# Requires Python 3.9+ from https://www.python.org/downloads/ (tick "Add python.exe to PATH"
# or keep the "py" launcher). Double-click install_windows.bat to run this script.
$ErrorActionPreference = "Stop"

$src = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$app = Join-Path $env:LOCALAPPDATA "8085 Studio"

$pyExe = "python"
$pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $pyExe = "py"; $pyArgs = @("-3") }
if (-not (Get-Command $pyExe -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.9 or newer from https://www.python.org/downloads/ and run this again."
}
& $pyExe @pyArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.9 or newer is required." }

Write-Host ">> Creating environment in $app"
New-Item -ItemType Directory -Force -Path $app | Out-Null
& $pyExe @pyArgs -m venv (Join-Path $app "venv")
if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
$venvPy = Join-Path $app "venv\Scripts\python.exe"
& $venvPy -m pip install --quiet --upgrade pip
Write-Host ">> Installing 8085 Studio and PySide6 (downloads Qt, about 100 MB)"
& $venvPy -m pip install --quiet $src
if ($LASTEXITCODE -ne 0) { throw "pip install failed." }

Copy-Item (Join-Path $src "packaging\icons\studio8085.ico") (Join-Path $app "studio8085.ico") -Force

# Start Menu shortcut (pythonw = no console window)
$shell = New-Object -ComObject WScript.Shell
$lnkPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\8085 Studio.lnk"
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = Join-Path $app "venv\Scripts\pythonw.exe"
$lnk.Arguments = "-m studio8085"
$lnk.WorkingDirectory = $env:USERPROFILE
$lnk.IconLocation = (Join-Path $app "studio8085.ico")
$lnk.Description = "Assemble, run and debug Intel 8085 programs"
$lnk.Save()

Write-Host ""
Write-Host "Installed. Open the Start menu and type '8085 Studio'."
