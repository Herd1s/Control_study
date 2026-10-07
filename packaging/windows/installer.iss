; Build the portable directory first. /DMyAppVersion may come from the release build.
#define MyAppName "ControlLab"
#ifndef MyAppVersion
#error MyAppVersion is required. Build with /DMyAppVersion from control_lab.__version__.
#endif
#ifndef AppSourceDir
#define AppSourceDir "..\..\dist\ControlLab"
#endif
#ifndef BuildOutputDir
#define BuildOutputDir "..\..\dist\installer"
#endif

[Setup]
AppId={{546AE213-0320-416B-B51A-F43F7D964BA2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\ControlLab
DefaultGroupName=ControlLab
PrivilegesRequired=lowest
UsePreviousAppDir=yes
UsePreviousGroup=yes
DisableDirPage=auto
CloseApplications=yes
CloseApplicationsFilter=ControlLab.exe,ControlLabCLI.exe
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#BuildOutputDir}
OutputBaseFilename=ControlLab-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ControlLab.exe
; User workspaces, experiments, models and update settings are outside {app}.
; Never add Documents\ControlLab to UninstallDelete or InstallDelete.

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ControlLab"; Filename: "{app}\ControlLab.exe"
Name: "{group}\ControlLab Guide"; Filename: "{app}\QUICKSTART.txt"

[Run]
Filename: "{app}\ControlLab.exe"; Description: "Open ControlLab"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: files; Name: "{app}\installation.json"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
  begin
    if not SaveStringToFile(ExpandConstant('{app}\installation.json'),
      '{"schema_version":1,"status":"installed_successfully","version":"{#MyAppVersion}"}', False) then
      Log('Could not write the installation completion marker.');
  end;
end;
