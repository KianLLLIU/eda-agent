; ===========================================================================
;  EDA Agent 桌面版安装程序（Inno Setup 6）
;
;  编译方式：
;    ISCC.exe installer\EDA-Agent.iss
;  或在项目根目录运行（推荐）：
;    powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
;
;  产物：dist\installer\EDA-Agent-Setup-v2.0.0.exe
;  安装后：开始菜单 + 可选桌面快捷方式 + 控制面板可卸载
; ===========================================================================

#define MyAppName "EDA Agent"
#define MyAppVersion "2.0.0"
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
VersionInfoDescription=AI 电路设计智能体 - 自然语言驱动 KiCad 电路设计
VersionInfoProductName={#MyAppName}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 主程序：PyInstaller 单文件 exe（已内含 Python 运行时、后端、前端与模板）
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; 图标单独放一份，供快捷方式与卸载程序使用
Source: "..\assets\eda-agent.ico"; DestDir: "{app}"; Flags: ignoreversion
; 随包附带说明，方便离线用户查看
Source: "..\docs\DESKTOP-INSTALL.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\eda-agent.ico"
Name: "{group}\查看使用说明"; Filename: "{app}\README.md"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\eda-agent.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载不删除用户数据（会话历史 / 设置 / 生成的工程），避免误删用户成果；
; 仅清理可能残留在安装目录的临时文件。
Type: files; Name: "{app}\desktop.log"

[Code]
// Windows 10/11 一般自带 WebView2；万一缺失，程序会自动降级到浏览器模式。
// 这里只做友好提示，不阻断安装。
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
    MsgBox('未检测到 Microsoft Edge WebView2 运行时。' + #13#10 + #13#10 +
           'EDA Agent 仍可正常使用（会自动改用默认浏览器打开界面）。' + #13#10 +
           '如需原生窗口体验，建议安装 WebView2 Runtime 后重新启动本程序。',
           mbInformation, MB_OK);
end;
