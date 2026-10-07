; Per-user NSIS installer for myapp.
; Built with: makensis /DVERSION=1.2.3 /DEXE_PATH=dist\myapp-windows.exe packaging\windows\installer.nsi
; No admin/UAC required -- installs under %LOCALAPPDATA%\Programs\myapp so the
; self-updater (app/updater.py) can keep overwriting the exe in place.

!ifndef VERSION
  !define VERSION "0.0.0-dev"
!endif
!ifndef EXE_PATH
  !define EXE_PATH "dist\myapp-windows.exe"
!endif

Name "myapp"
OutFile "release\myapp-windows-installer.exe"
InstallDir "$LOCALAPPDATA\Programs\myapp"
RequestExecutionLevel user
SetCompressor /SOLID lzma

!include "MUI2.nsh"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

VIProductVersion "0.0.0.0"
VIAddVersionKey "ProductName" "myapp"
VIAddVersionKey "ProductVersion" "${VERSION}"

Section "Install"
  SetOutPath "$INSTDIR"
  File "/oname=myapp.exe" "${EXE_PATH}"

  CreateDirectory "$SMPROGRAMS\myapp"
  CreateShortcut "$SMPROGRAMS\myapp\myapp.lnk" "$INSTDIR\myapp.exe"
  CreateShortcut "$DESKTOP\myapp.lnk" "$INSTDIR\myapp.exe"

  WriteUninstaller "$INSTDIR\uninstall.exe"

  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\myapp" \
    "DisplayName" "myapp"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\myapp" \
    "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\myapp" \
    "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\myapp" \
    "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\myapp" \
    "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\myapp" \
    "NoRepair" 1
SectionEnd

Section "Uninstall"
  ; Deliberately does not touch $INSTDIR\data -- click history survives
  ; uninstall/reinstall. Only remove it manually if a full wipe is wanted.
  Delete "$INSTDIR\myapp.exe"
  Delete "$INSTDIR\uninstall.exe"
  Delete "$SMPROGRAMS\myapp\myapp.lnk"
  RMDir "$SMPROGRAMS\myapp"
  Delete "$DESKTOP\myapp.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\myapp"
SectionEnd
