@echo off
setlocal EnableExtensions
cd /D "%~dp0"

set "APP_NAME=GUIStream"
set "SOURCE_FILE=%CD%\guistream.py"
set "SPEC_FILE=%CD%\GUIStream.spec"

echo == GUIStream Windows build ==

if not exist "%SOURCE_FILE%" (
  echo Erreur : source introuvable : %SOURCE_FILE%
  exit /B 1
)

if not exist "%SPEC_FILE%" (
  echo Erreur : fichier PyInstaller introuvable : %SPEC_FILE%
  exit /B 1
)

findstr /C:"self.notebook = Gtk.Notebook()" "%SOURCE_FILE%" >nul
if errorlevel 1 (
  echo Erreur : guistream.py ne contient pas la nouvelle interface a onglets.
  exit /B 1
)

python -m pip install --upgrade pip wheel setuptools
if errorlevel 1 exit /B 1

python -m pip install -r requirements.txt
if errorlevel 1 exit /B 1

rmdir /S /Q build 2>nul
rmdir /S /Q dist 2>nul

python -m PyInstaller ^
  --clean ^
  --noconfirm ^
  "%SPEC_FILE%"
if errorlevel 1 exit /B 1

if not exist "dist\%APP_NAME%.exe" (
  echo Erreur : dist\%APP_NAME%.exe est introuvable.
  exit /B 1
)

echo.
echo Fichier genere :
echo %CD%\dist\%APP_NAME%.exe
exit /B 0