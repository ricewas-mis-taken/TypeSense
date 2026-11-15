# TypeSense - participant setup: downloads the client into %LOCALAPPDATA%\Programs\TypeSense, installs deps, registers autostart, launches.
$ErrorActionPreference = "Stop"
$raw = "https://raw.githubusercontent.com/ricewas-mis-taken/TypeSense/main"
$dir = Join-Path $env:LOCALAPPDATA "Programs\TypeSense"
New-Item -ItemType Directory -Force $dir | Out-Null

function Find-Python {
    foreach ($v in "311","312","313","310") {
        foreach ($root in "$env:LOCALAPPDATA\Programs\Python","$env:ProgramFiles") {
            $p = Join-Path $root "Python$v\python.exe"
            if (Test-Path $p) { return $p }
        }
    }
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c) {
        $ver = & $c.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver -and [version]$ver -ge [version]"3.10" -and [version]$ver -lt [version]"3.14") { return $c.Source }
    }
}
$python = Find-Python
if (-not $python) {
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    $python = Find-Python
}
if (-not $python) { throw "Could not find or install Python 3.10-3.13." }

foreach ($f in "keylogger.py","survey.py","user_send.py","updater.py","app_paths.py","align.py","version.py","requirements.txt") {
    Invoke-WebRequest "$raw/$f" -OutFile (Join-Path $dir $f) -UseBasicParsing
}

$req = Join-Path $dir "client-requirements.txt"
Get-Content (Join-Path $dir "requirements.txt") | Where-Object { $_ -notmatch "^(?i)(flask|waitress|pyinstaller)" } | Set-Content $req
& $python -m pip install --upgrade pip --quiet --no-warn-script-location
& $python -m pip install -r $req --quiet --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed - nothing was registered." }

$pythonw = Join-Path (Split-Path $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }
$script = Join-Path $dir "keylogger.py"
Set-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "TypeSenseLogger" -Value "`"$pythonw`" `"$script`""
schtasks /Create /F /TN "TypeSenseLoggerWatchdog" /TR "`"$pythonw`" `"$script`"" /SC MINUTE /MO 20 | Out-Null
Start-Process $pythonw -ArgumentList "`"$script`"" -WorkingDirectory $dir -WindowStyle Hidden
Write-Host "TypeSense is running and will restart on every login."
