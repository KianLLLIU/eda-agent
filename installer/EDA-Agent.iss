; ===========================================================================
;  EDA Agent desktop installer (Inno Setup 6)
;
;  Build:
;    ISCC.exe installer\EDA-Agent.iss
;  or from project root:
;    powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
;
;  Output: dist\installer\EDA-Agent-Setup-v2.0.5.exe
;  Installs: Start Menu entry, optional desktop shortcut, uninstaller.
;
;  NOTE: This file is intentionally pure ASCII. Inno Setup reads .iss files
;  using the system ANSI codepage unless a BOM is present, and the official
;  compiler does not ship ChineseSimplified.isl. Keeping everything ASCII
;  guarantees a clean build on any machine / CI runner. Localized docs live
;  in docs\DESKTOP-INSTALL.md (shipped with the installer).
; ===========================================================================

#define MyAppName "EDA Agent"
#define MyAppVersion "2.0.5"
#define MyAppPublisher "KianLLLIU"
#define MyAppURL "https://github.com/KianLLLIU/eda-agent"
#define MyAppExeName "EDA-Agent.exe"
#define MyAppId "{{8A4F2C1E-7B3D-4E9A-9C6F-1D2E3F4A5B6C}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\EDA Agent
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\installer
OutputBaseFilename=EDA-Agent-Setup-v{#MyAppVersion}
SetupIconFile=..\assets\eda-agent.ico
UninstallDisplayIcon={app}\eda-agent.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=AI Circuit Design Agent - natural language to KiCad schematics
VersionInfoProductName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; Main program: PyInstaller one-file exe (Python runtime, backend, frontend and
; templates are all embedded).
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Icon kept separately for shortcuts and the uninstaller entry
Source: "..\assets\eda-agent.ico"; DestDir: "{app}"; Flags: ignoreversion
; Offline documentation
Source: "..\docs\DESKTOP-INSTALL.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\eda-agent.ico"
Name: "{group}\User Guide"; Filename: "{app}\README.md"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\eda-agent.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch EDA Agent"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; User data (sessions, settings, generated projects) lives under the user's home
; directory and is intentionally NOT removed by the uninstaller.
Type: files; Name: "{app}\desktop.log"

[Code]
// Windows 10/11 normally ships WebView2. If missing, the app automatically
// falls back to opening the default browser, so installation is never blocked.
function IsWebView2Present(): Boolean;
begin
  Result :=
    RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') or
    RegKeyExists(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') or
    RegKeyExists(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not IsWebView2Present()) then
    MsgBox('Microsoft Edge WebView2 Runtime was not detected.' + #13#10 + #13#10 +
           'EDA Agent still works: it will automatically open in your default browser.' + #13#10 +
           'For a native window experience, install WebView2 Runtime and restart the app.',
           mbInformation, MB_OK);
end;
