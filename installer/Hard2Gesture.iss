; Inno Setup script for Hard2Gesture. Build with installer\build.ps1, which bundles
; the app into dist\Hard2Gesture first and passes the version in /DAppVersion.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; The version in the setup file's properties must be numbers only, e.g. 2.0.0 for 2.0.0b1.
#ifndef FileVersion
  #define FileVersion AppVersion
#endif
#define AppName "Hard2Gesture"
#define AppExe "Hard2Gesture.exe"
#define AppPublisher "Andrija Simic"
; Settings and log; must match DATA_DIR in hard2gesture\paths.py.
#define DataDir "{localappdata}\Hard2Gesture"

[Setup]
; Never change AppId: it's how later versions find and upgrade this install.
AppId={{7EF18DFA-1A36-4B3C-BE92-60F2D2231255}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=Copyright (c) 2026 {#AppPublisher}
VersionInfoVersion={#FileVersion}
; Per-user install: no admin prompt, and matches the per-user settings and autostart.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Must match SINGLE_INSTANCE_MUTEX_NAME in hard2gesture\app.py: setup asks the user to quit the app before replacing it.
; HandGesturesRunning is the same mutex from before the app was renamed from HandGestures.
AppMutex=Hard2GestureRunning,HandGesturesRunning
; Versions from before the rename were installed in a HandGestures folder and Start Menu group.
; Install into the new ones instead; [InstallDelete] removes the old ones.
UsePreviousAppDir=no
UsePreviousGroup=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
SetupIconFile=..\assets\icon.ico
LicenseFile=..\LICENSE
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
; The About box links to the notices next to the .exe.
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"

[Dirs]
; Created now so the "Settings and log" shortcut works before the first run.
Name: "{#DataDir}"; Flags: uninsneveruninstall

[InstallDelete]
; The bundled libraries change between versions: remove the old ones rather than leave them mixed in.
Type: filesandordirs; Name: "{app}\_internal"
; What a version from before the rename left behind: its program folder and shortcuts.
Type: filesandordirs; Name: "{autopf}\HandGestures"
Type: filesandordirs; Name: "{autoprograms}\HandGestures"
Type: files; Name: "{autodesktop}\HandGestures.lnk"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Settings and log"; Filename: "{#DataDir}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; At sign-in, start quietly in the tray; the preview can be shown from the tray menu.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --no-preview"; Flags: uninsdeletevalue; Tasks: autostart
; The sign-in entry of a version from before the rename.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "HandGestures"; Flags: deletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  OldDataDir, DataDir: String;
begin
  // Settings, calibration and log from before the rename move to the new folder. This runs
  // before [Dirs] creates that folder, so it only exists already if this version ran before.
  if CurStep = ssInstall then
  begin
    OldDataDir := ExpandConstant('{localappdata}\HandGestures');
    DataDir := ExpandConstant('{#DataDir}');
    if DirExists(OldDataDir) and not DirExists(DataDir) then
      if not RenameFile(OldDataDir, DataDir) then
        Log('Could not move ' + OldDataDir + ' to ' + DataDir);
  end;
  // A reinstall without the autostart task must not leave the old autostart entry behind.
  if (CurStep = ssPostInstall) and not WizardIsTaskSelected('autostart') then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  // The app's Settings can turn on start at sign-in too, so the entry may exist without the task.
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
  DataDir := ExpandConstant('{#DataDir}');
  if (CurUninstallStep = usPostUninstall) and DirExists(DataDir) then
    if SuppressibleMsgBox('Also delete your {#AppName} settings and log?' + #13#10#13#10 + DataDir,
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
      DelTree(DataDir, True, True, True);
end;
