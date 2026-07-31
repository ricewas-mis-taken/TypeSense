#define MyAppName "TypeSense"
#define MyAppExeName "TypeSenseLogger.exe"

[Setup]
AppId={{6B2F1B7C-5B7E-4C36-9C6B-2A1A2C6C1B7A}
AppName={#MyAppName}
; Without this, Inno defaults the Apps & Features "Name" column to
; "AppName AppVersion" ("TypeSense 1.3.0") - pin it to just the app name so
; the version only shows in its own column, not baked into the title.
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
; outside of Inno's own [Registry]/[Icons] bookkeeping (they're written
; directly via winreg/schtasks so they survive even a portable/non-installer
; run), so the installer has to explicitly tear them down on uninstall too -
; otherwise they're left behind pointing at a now-deleted exe.
; RELAUNCH_TASK_NAME in keylogger.py must stay in sync with the /TN value below.
[UninstallRun]
Filename: "{cmd}"; Parameters: "/C schtasks /Delete /TN TypeSenseLoggerWatchdog /F"; Flags: runhidden; RunOnceId: "DelWatchdogTask"
Filename: "{cmd}"; Parameters: "/C reg delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v TypeSenseLogger /f"; Flags: runhidden; RunOnceId: "DelAutostartKey"

; Removes the per-user data dir (session id, logs, queued CSVs) so uninstall
; leaves nothing behind on the participant's machine.
[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\TypeSense"
