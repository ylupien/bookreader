; Installateur hors ligne de BookReader (Inno Setup 6).
; Compiler avec build\make-installer.ps1 après prepare-runtime.ps1 et « npm run pack ».
; DiskSpanning : NSIS est limité à 2 Go ; ici, BookReader-Setup.exe + des BookReader-Setup-N.bin
; de 2 Go, à garder ensemble dans le même dossier.

#define AppName "BookReader"
#define AppVersion "0.1.0"

[Setup]
AppId={{6E2D5F0A-4C1B-4B8E-9B1E-2F6C7A1D0B31}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=BookReader-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico
Compression=lzma2/fast
SolidCompression=no
DiskSpanning=yes
DiskSliceSize=2000000000
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; Flags: unchecked

[Files]
Source: "..\dist\win-unpacked\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion
; Python, modèle XTTS et ffmpeg : ne se compressent presque pas (torch/CUDA)
Source: "runtime\*"; DestDir: "{app}\runtime"; Flags: recursesubdirs ignoreversion nocompression

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\BookReader.exe"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\BookReader.exe"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\BookReader.exe"; Description: "Lancer {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Les livres et les voix (%APPDATA%\BookReader) sont volontairement conservés
Type: filesandordirs; Name: "{app}"
