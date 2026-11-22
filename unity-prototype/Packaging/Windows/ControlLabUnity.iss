#ifndef AppVersion
  #error AppVersion must be supplied by Build-Installer.ps1
#endif
#ifndef PayloadDir
  #error PayloadDir must point at a verified Unity Windows build
#endif
#ifndef ReleaseDir
  #error ReleaseDir must be supplied
#endif

[Setup]
AppId={{B6B2A45A-E5B3-49E9-8DB5-974C40B75963}
AppName=ControlLab Unity
AppVersion={#AppVersion}
AppPublisher=ControlLab
AppPublisherURL=https://github.com/Herd1s/Control_study
DefaultDirName={localappdata}\Programs\ControlLabUnity
DefaultGroupName=ControlLab Unity
PrivilegesRequired=lowest
UsePreviousAppDir=yes
UsePreviousGroup=yes
DisableDirPage=auto
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
CloseApplicationsFilter=ControlLab Unity.exe,UnityPlayer.dll
RestartApplications=no
OutputDir={#ReleaseDir}
OutputBaseFilename=ControlLab-Unity-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ControlLab Unity.exe
SetupLogging=yes
; User profiles live under LocalLow\ControlLab\ControlLab Unity, never under {app}.

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ControlLab Unity"; Filename: "{app}\ControlLab Unity.exe"

[Run]
Filename: "{app}\ControlLab Unity.exe"; Description: "Open ControlLab Unity"; Flags: nowait postinstall skipifsilent unchecked; Check: OfferLaunch

[UninstallDelete]
Type: files; Name: "{app}\installation.json"

[Code]
const
  SYNCHRONIZE = $00100000;
  WAIT_OBJECT_0 = 0;
  WAIT_TIMEOUT = $00000102;
  ERROR_INVALID_PARAMETER = 87;

function OpenProcess(Access: LongWord; InheritHandle: Boolean; ProcessId: LongWord): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(Handle: THandle; Milliseconds: LongWord): LongWord;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

var
  RestartRequested: Boolean;
  RestartProfile: String;

function QuoteArgument(Value: String): String;
var
  Index: Integer;
begin
  Result := Value;
  Index := Length(Value);
  while Index > 0 do begin
    if Value[Index] <> '\' then Break;
    Result := Result + '\';
    Index := Index - 1;
  end;
  Result := '"' + Result + '"';
end;

function RestartArguments: String;
begin
  Result := '';
  if RestartProfile <> '' then Result := '--profile-directory ' + QuoteArgument(RestartProfile);
end;

function OfferLaunch: Boolean;
begin
  Result := not RestartRequested;
end;

function InitializeSetup: Boolean;
var
  ParentPid, WaitResult, LastError: LongWord;
  ParentHandle: THandle;
  PidText: String;
begin
  Result := False;
  RestartRequested := ExpandConstant('{param:RESTARTAPP|0}') = '1';
  RestartProfile := ExpandConstant('{param:PROFILEDIR|}');
  if RestartProfile <> '' then begin
    if (Pos('"', RestartProfile) <> 0) or (Pos(#13, RestartProfile) <> 0)
      or (Pos(#10, RestartProfile) <> 0) or (ExtractFileDrive(RestartProfile) = '')
      or not DirExists(RestartProfile) then begin
      Log('Invalid isolated profile path; no files were changed.');
      Exit;
    end;
  end;
  PidText := ExpandConstant('{param:WAITFORPID|0}');
  ParentPid := StrToIntDef(PidText, 0);
  if (ParentPid = 0) and (PidText <> '0') then begin
    Log('Invalid WAITFORPID argument; no files were changed.');
    Exit;
  end;
  if ParentPid <> 0 then begin
    ParentHandle := OpenProcess(SYNCHRONIZE, False, ParentPid);
    if ParentHandle = 0 then begin
      LastError := DLLGetLastError;
      if LastError <> ERROR_INVALID_PARAMETER then begin
        Log(Format('Unable to verify that the old player exited (error %d).', [LastError]));
        Exit;
      end;
      Log('The original player already exited.');
    end else begin
      Log(Format('Waiting for player %d to save and exit.', [ParentPid]));
      WaitResult := WaitForSingleObject(ParentHandle, 45000);
      CloseHandle(ParentHandle);
      if WaitResult <> WAIT_OBJECT_0 then begin
        Log('The original player did not exit; installation aborted before replacing files.');
        Exit;
      end;
    end;
  end;
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssDone then begin
    if not SaveStringToFile(ExpandConstant('{app}\installation.json'),
      '{"productId":"controllab-unity","version":"{#AppVersion}","status":"installed"}', False) then
      Log('Could not write the installation marker. The app will not claim a confirmed update.');
    if RestartRequested then begin
      if not Exec(ExpandConstant('{app}\ControlLab Unity.exe'), RestartArguments, ExpandConstant('{app}'),
        SW_SHOWNORMAL, ewNoWait, ResultCode) then
        Log(Format('Installed successfully, but automatic restart failed: %d', [ResultCode]));
    end;
  end;
end;
