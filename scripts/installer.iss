; Установщик VoiceFlow для Inno Setup 6.
;
; Ставится в профиль пользователя, поэтому не требует прав администратора
; и не показывает запрос UAC. Перед сборкой выполните build_portable.ps1:
; установщик упаковывает готовый каталог dist\VoiceFlow.

#define AppName "VoiceFlow"
#define AppVersion "0.2.0"
#define AppPublisher "VoiceFlow"
#define AppExeName "VoiceFlow.exe"

[Setup]
AppId={{7F3C1B84-19E5-4C7A-9F0D-2A6B8E4D5C11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\installer_output
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"; Flags: unchecked
Name: "autostart"; Description: "Запускать вместе с Windows"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
; portable.txt исключаем: в установленной версии данные идут в профиль,
; а маркер увёл бы их в папку программы, куда нет прав на запись.
;
; userdata исключаем обязательно: в каталоге сборки лежат настройки, история
; и загруженные модели разработчика. Без этого установщик разросся до
; двух с половиной гигабайт и раздавал бы чужие личные данные.
Source: "..\dist\VoiceFlow\*"; DestDir: "{app}"; \
    Excludes: "portable.txt,userdata,userdata\*"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "VoiceFlow"; ValueData: """{app}\{#AppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; Если поверх ставят версию, распакованную как portable, маркер надо убрать.
Type: files; Name: "{app}\portable.txt"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataDir: String;
  ModelsDir: String;
begin
  if CurUninstallStep <> usPostUninstall then
    exit;

  UserDataDir := ExpandConstant('{userappdata}\VoiceFlow');
  ModelsDir := ExpandConstant('{localappdata}\VoiceFlow\models');

  if DirExists(UserDataDir) then
  begin
    if MsgBox('Удалить настройки, инструкции и историю VoiceFlow?',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(UserDataDir, True, True, True);
      DelTree(ExpandConstant('{localappdata}\VoiceFlow\data'), True, True, True);
      DelTree(ExpandConstant('{localappdata}\VoiceFlow\logs'), True, True, True);
    end;
  end;

  if DirExists(ModelsDir) then
  begin
    if MsgBox('Удалить загруженные модели? Они могут занимать десятки гигабайт.',
              mbConfirmation, MB_YESNO) = IDYES then
      DelTree(ModelsDir, True, True, True);
  end;
end;
