; Inno Setup script for VibeCleaner Windows installer.
; Built by .github/workflows/release.yml against the PyInstaller onedir output
; in dist\VibeCleaner (produced on windows-latest before this script runs).

#define MyAppName "VibeCleaner"
#define MyAppVersion GetEnv("VIBECLEANER_VERSION")
#define MyAppExeName "VibeCleaner.exe"

[Setup]
AppId={{B36F2E1D-6C0D-4C39-9C7C-8E4C0D3D9B2E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=VibeCleaner-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\..\dist\VibeCleaner\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
