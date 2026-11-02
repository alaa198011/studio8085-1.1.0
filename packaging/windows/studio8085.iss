; Inno Setup script - builds a normal Windows installer from the PyInstaller output.
;   1) pyinstaller packaging/studio8085.spec --noconfirm        (creates dist\8085Studio\)
;   2) iscc packaging\windows\studio8085.iss                     (creates dist\installer\...Setup.exe)
#define AppName "8085 Studio"
#define AppVersion "1.1.0"
#define AppExe "8085Studio.exe"

[Setup]
AppId={{6F0B2D2E-8C41-4A57-9E64-8085AB5D1085}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=8085 Studio contributors
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=8085Studio-Setup-{#AppVersion}
SetupIconFile=..\icons\studio8085.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\..\dist\8085Studio\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
