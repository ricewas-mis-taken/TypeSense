#define MyAppName "TypeSense"
#define MyAppExeName "TypeSenseLogger.exe"

[Setup]
AppId={{6B2F1B7C-5B7E-4C36-9C6B-2A1A2C6C1B7A}
AppName={#MyAppName}
AppVerName={#MyAppName}
AppVersion=1.3.0
AppMutex=Global\TypeSenseLogger_SingleInstance_Mutex
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=TypeSenseSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\TypeSenseLogger\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall

; keylogger.py's ensure_autostart()/ensure_relaunch_task() create these
; directly via winreg/schtasks, outside Inno's own bookkeeping, so uninstall
; must tear them down explicitly here or they're left pointing at a deleted exe.
[UninstallRun]
Filename: "{cmd}"; Parameters: "/C schtasks /Delete /TN TypeSenseLoggerWatchdog /F"; Flags: runhidden; RunOnceId: "DelWatchdogTask"
Filename: "{cmd}"; Parameters: "/C reg delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v TypeSenseLogger /f"; Flags: runhidden; RunOnceId: "DelAutostartKey"

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\TypeSense"
