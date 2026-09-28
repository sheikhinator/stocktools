; Inno Setup script: per-user install, no administrator rights needed.
#define AppName "Stock Compass"
#ifndef AppVersion
  #define AppVersion "0.9.4"
#endif

[Setup]
AppId={{6E3B7F2A-6A1C-4C47-9E4C-5C7A2B8D1F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=MAF Carrefour Pakistan (internal tool)
DefaultDirName={localappdata}\Programs\Stock Compass
DefaultGroupName=Stock Compass
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=StockCompass-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\StockCompass.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\StockCompass\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Stock Compass"; Filename: "{app}\StockCompass.exe"
Name: "{userdesktop}\Stock Compass"; Filename: "{app}\StockCompass.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\StockCompass.exe"; Description: "Open Stock Compass"; Flags: nowait postinstall skipifsilent

; Your data (database, settings) lives in %LOCALAPPDATA%\StockCompass and is kept on uninstall.
