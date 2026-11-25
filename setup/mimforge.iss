; Mimforge — Inno Setup installer script (plan Phase 6.2)
; Built by setup\build-windows.ps1 after the PyInstaller build.
; Requires Inno Setup 6 (free, https://jrsoftware.org/isdl.php).
; Installs the onedir PyInstaller output (dist\Mimforge) so the
; LGPL libraries (Qt, OCCT) ship as separate files with the licence
; notices, per docs/SBOM.md.

#define MyAppName "Mimforge"
#define MyAppVersion "0.0.1"
#define MyAppPublisher "PrinceDevs"
#define MyAppURL "https://github.com/princeemma687-blip/mimforge"

[Setup]
AppId={{8F3A2C1E-4B7D-4A9E-9C2F-1D5E6A7B8C90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
; App icon: logo C "Machine Frame" (owner's pick, 2026-11-25). The .ico
; sits in assets\branding at the repo root, one level up from setup\.
SetupIconFile=..\assets\branding\mimforge.ico
OutputDir=..\dist
OutputBaseFilename=Mimforge-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Unsigned build: Windows SmartScreen will warn on first run.
; That is expected for an unsigned installer -- see docs/PACKAGING.md.
; (An Authenticode certificate is a paid convenience, not required.)

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Mimforge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Licence notices ship inside the app folder (see mimforge.spec datas).
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\SBOM.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\Mimforge.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\Mimforge.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Mimforge.exe"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
