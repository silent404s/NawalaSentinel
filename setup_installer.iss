[Setup]
AppName=NawalaSentinel
AppVersion=2.0.0
DefaultDirName={pf}\NawalaSentinel
DefaultGroupName=NawalaSentinel
UninstallDisplayIcon={app}\gui_client.exe
Compression=lzma2
SolidCompression=yes
OutputDir=Output
OutputBaseFilename=NawalaSentinel_Setup_v2.0

[Files]
; Asumsikan file exe dihasilkan dari PyInstaller di folder dist
Source: "dist\gui_client.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\NawalaSentinel"; Filename: "{app}\gui_client.exe"
Name: "{commondesktop}\NawalaSentinel"; Filename: "{app}\gui_client.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Buat shortcut di Desktop"; GroupDescription: "Additional icons:"
