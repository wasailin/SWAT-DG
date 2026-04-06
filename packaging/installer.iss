; SWAT-DG Inno Setup Installer Script
; ----------------------------------------
; Prerequisites:
;   1. Run build_portable.py --keep-build first
;   2. Install Inno Setup 6+ from https://jrsoftware.org/isinfo.php
;
; Build:
;   iscc /DAppVersion=0.5.0 packaging/installer.iss
;
; Or open this file in Inno Setup Compiler and click Build.

#ifndef AppVersion
  #define AppVersion "0.5.0"
#endif

#define AppName "SWAT-DG"
#define AppPublisher "SWAT-DG Team"
#define AppURL "https://github.com/wasailin/SWAT-DG"

[Setup]
AppId={{7E4F8A2B-3C1D-4E5F-9A6B-8D7C2E1F0A3B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} v{#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={autopf}\SWAT-DG
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=SWAT-DG-v{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
; No admin required - installs to user's Program Files
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Show license page
LicenseFile=..\LICENSE
SetupIconFile=compiler:SetupClassicIcon.ico
UninstallDisplayIcon={app}\python\python.exe
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Include everything from the portable build
Source: "build\SWAT-DG\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut
Name: "{group}\{#AppName}"; Filename: "{app}\SWAT-DG.bat"; WorkingDir: "{app}"; Comment: "Launch SWAT-DG Calibration Tool"
; Desktop shortcut (optional)
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\SWAT-DG.bat"; WorkingDir: "{app}"; Comment: "Launch SWAT-DG Calibration Tool"; Tasks: desktopicon
; Uninstall shortcut in Start Menu
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Run]
; Option to launch after install
Filename: "{app}\SWAT-DG.bat"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
; Clean up Python cache files created at runtime
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\__pycache__"
Type: filesandordirs; Name: "{app}\app\swat_modern\__pycache__"
Type: filesandordirs; Name: "{app}\app\.streamlit"

[Messages]
WelcomeLabel2=This will install {#AppName} v{#AppVersion} on your computer.%n%n{#AppName} is a calibration tool for the SWAT2012 hydrological model. It includes an embedded Python runtime — no additional software is required.%n%nAll data processing runs locally on your computer.
