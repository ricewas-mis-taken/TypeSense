# Run this in an elevated PowerShell (Run as Administrator)
$nssm = "C:\Users\Lucas\AppData\Local\Microsoft\WinGet\Packages\NSSM.NSSM_Microsoft.Winget.Source_8wekyb3d8bbwe\nssm-2.24-101-g897c7ad\win64\nssm.exe"
$python = "C:\Users\Lucas\AppData\Local\Programs\Python\Python311\python.exe"
$script = "C:\Users\Lucas\PycharmProjects\keeb_fresh\client_typesenseML.py"
$workdir = "C:\Users\Lucas\PycharmProjects\keeb_fresh"

& $nssm install TypeSenseServer $python $script
& $nssm set TypeSenseServer AppDirectory $workdir
& $nssm set TypeSenseServer AppStdout "$workdir\server_stdout.log"
& $nssm set TypeSenseServer AppStderr "$workdir\server_stderr.log"
& $nssm set TypeSenseServer Start SERVICE_AUTO_START
& $nssm set TypeSenseServer AppExit Default Restart
& $nssm set TypeSenseServer AppRestartDelay 5000
& $nssm start TypeSenseServer
Start-Sleep -Seconds 2
Get-Service TypeSenseServer
