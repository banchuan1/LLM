; ============================================================
; NAgent 安装程序配置（Inno Setup 6）
; 使用方式：
;   "D:\Inno Setup 6\ISCC.exe" "installer\NAgent.iss"
; 或直接运行项目根目录下的 build_package.ps1（推荐）
;
; 说明：
;   - 源码来自 PyInstaller 构建产物 dist\Nagent\*
;   - config.ini 会被一并打包（内含 API 密钥，仅供本人使用；
;     若需对外分发请先用占位符替换再打包）
; ============================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "NAgent"
#define MyAppPublisher "NAgent"
#define MyAppExeName "Nagent.exe"

[Setup]
AppId={{E5A3F700-C3BE-4F41-9F00-B28552201E84}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir={#SourcePath}
OutputBaseFilename=NAgent-setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "..\dist\Nagent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\config.ini"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
