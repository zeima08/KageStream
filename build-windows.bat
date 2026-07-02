@echo off
set APP_NAME=GUIStream

echo == GUIStream Windows build ==

python -m pip install --upgrade -r requirements.txt

rmdir /S /Q build 2>nul
rmdir /S /Q dist 2>nul

python -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name %APP_NAME% ^
  guistream.py

echo.
echo Fichier genere :
echo dist\GUIStream.exe
pause
