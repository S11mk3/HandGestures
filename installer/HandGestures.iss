; Inno Setup script for HandGestures. Build with installer\build.ps1, which bundles
; the app into dist\HandGestures first and passes the version in /DAppVersion.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "HandGestures"
#define AppExe "HandGestures.exe"
; Settings and log; must match DATA_DIR in handgestures\paths.py.
#define DataDir "{localappdata}\HandGestures"

[Setup]
; Never change AppId: it's how later versions find and upgrade this install.
AppId={{7EF18DFA-1A36-4B3C-BE92-60F2D2231255}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
; Per-user install: no admin prompt, and matches the per-user settings and autostart.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Must match SINGLE_INSTANCE_MUTEX_NAME in main.py: setup asks the user to quit the app before replacing it.
AppMutex=HandGesturesRunning
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}

[Tasks]
Name: "autostart"; Description: "Start {#AppName} when I sign in to Windows"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; Created now so the "Settings and log" shortcut works before the first run.
Name: "{#DataDir}"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Settings and log"; Filename: "{#DataDir}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; At sign-in, start quietly in the tray; the preview can be shown from the tray menu.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --no-preview"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// A reinstall without the autostart task must not leave the old autostart entry behind.
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not WizardIsTaskSelected('autostart') then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  DataDir := ExpandConstant('{#DataDir}');
  if (CurUninstallStep = usPostUninstall) and DirExists(DataDir) then
    if SuppressibleMsgBox('Also delete your {#AppName} settings and log?' + #13#10#13#10 + DataDir,
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
      DelTree(DataDir, True, True, True);
end;
