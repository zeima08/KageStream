@echo off
setlocal EnableExtensions
cd /D "%~dp0"

set "APP_NAME=KageStream"
set "ROOT_DIR=%CD%"
set "SOURCE_FILE=%ROOT_DIR%\kagestream.py"
set "APP_PACKAGE_FILE=%ROOT_DIR%\kagestream\app.py"
set "SPEC_FILE=%ROOT_DIR%\kagestream.spec"
set "VENV_DIR=%ROOT_DIR%\.venv-windows"
set "DIST_DIR=%ROOT_DIR%\dist"
set "BUILD_DIR=%ROOT_DIR%\build"

echo == KageStream Windows build ==
echo Dossier : %ROOT_DIR%

if not exist "%SOURCE_FILE%" (
    echo Erreur : source introuvable : %SOURCE_FILE%
    exit /B 1
)

if not exist "%SPEC_FILE%" (
    echo Erreur : fichier PyInstaller introuvable : %SPEC_FILE%
    exit /B 1
)

if not exist "%APP_PACKAGE_FILE%" (
    echo Erreur : %APP_PACKAGE_FILE% introuvable.
    echo kagestream.py doit rester un lanceur minimal qui importe le package kagestream\
    exit /B 1
)

findstr /C:"from kagestream.main import main" "%SOURCE_FILE%" >nul
if errorlevel 1 (
    echo Erreur : %SOURCE_FILE% ne lance plus l'application via le package kagestream\
    exit /B 1
)

findstr /C:"self.stack = Gtk.Stack()" "%APP_PACKAGE_FILE%" >nul
if errorlevel 1 (
    echo Erreur : %APP_PACKAGE_FILE% ne contient pas l'interface a barre laterale actuelle.
    echo Build arrete pour eviter de recreer accidentellement une ancienne interface.
    exit /B 1
)

echo.
echo == Verification de l'environnement Python/GTK ==
echo KageStream a besoin de Python + PyGObject + GTK3. Sur Windows, la seule voie fiable
echo est l'environnement MSYS2 MinGW64 ^(il n'existe pas de paquet PyGObject officiel sur PyPI^).

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo Erreur : "python" est introuvable dans le PATH.
    call :print_msys2_help
    exit /B 1
)

python -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk" >nul 2>nul
if errorlevel 1 (
    echo.
    echo Erreur : ce Python ne trouve pas GTK3/PyGObject ^(module "gi"^).
    echo C'est attendu si tu utilises le Python officiel de python.org : il ne fournit pas "gi".
    call :print_msys2_help
    exit /B 1
)

echo Python detecte :
where python

echo.
echo == Mise a jour des paquets MSYS2 utiles si possible ==
where pacman >nul 2>nul
if not errorlevel 1 (
    pacman -S --needed --noconfirm mingw-w64-x86_64-python-pip mingw-w64-x86_64-python-gobject mingw-w64-x86_64-gtk3
) else (
    echo "pacman" introuvable depuis ce terminal : verifie manuellement que GTK3/PyGObject sont a jour.
)

echo.
echo == Creation de l'environnement Python local ==
if not exist "%VENV_DIR%" (
    python -m venv --system-site-packages "%VENV_DIR%"
    if errorlevel 1 exit /B 1
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 exit /B 1

python -m pip install --upgrade pip wheel setuptools
if errorlevel 1 exit /B 1

python -m pip install --upgrade -r "%ROOT_DIR%\requirements.txt"
if errorlevel 1 exit /B 1

echo.
echo == Verification GTK/PyGObject dans le venv ==
python -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk" >nul 2>nul
if errorlevel 1 (
    echo GTK/PyGObject n'est pas visible depuis le venv.
    echo Solution :
    echo   rmdir /S /Q "%VENV_DIR%"
    echo   build-windows.bat
    exit /B 1
)

echo.
echo == Nettoyage build ==
if exist "%BUILD_DIR%" rmdir /S /Q "%BUILD_DIR%"
if exist "%DIST_DIR%" rmdir /S /Q "%DIST_DIR%"

echo.
echo == Build PyInstaller ==
python -m PyInstaller ^
    --clean ^
    --noconfirm ^
    --distpath "%DIST_DIR%" ^
    --workpath "%BUILD_DIR%" ^
    "%SPEC_FILE%"
if errorlevel 1 exit /B 1

if not exist "%DIST_DIR%\%APP_NAME%.exe" (
    echo Erreur : %DIST_DIR%\%APP_NAME%.exe est introuvable.
    exit /B 1
)

echo.
echo == Empaquetage de Streamlink a cote de l'executable ==
rem KageStream cherche ses outils dans <dossier de l'exe>\bin\ avant le PATH.
rem Il n'existe pas d'installateur direct Streamlink pour Windows (contrairement a
rem Linux) : on copie donc celui installe par pip dans le venv.
if exist "%VENV_DIR%\Scripts\streamlink.exe" (
    if not exist "%DIST_DIR%\bin" mkdir "%DIST_DIR%\bin"
    copy /Y "%VENV_DIR%\Scripts\streamlink.exe" "%DIST_DIR%\bin\streamlink.exe" >nul
    echo Streamlink copie dans %DIST_DIR%\bin\streamlink.exe
) else (
    echo Attention : streamlink.exe introuvable dans le venv, non embarque.
)

echo.
echo Fichier genere :
echo %DIST_DIR%\%APP_NAME%.exe
where certutil >nul 2>nul
if not errorlevel 1 (
    certutil -hashfile "%DIST_DIR%\%APP_NAME%.exe" SHA256
)

echo.
echo == Lancement de %APP_NAME% ==
echo FFmpeg, yt-dlp et Deno restent a installer depuis l'onglet Outils au premier
echo lancement ^(telechargement direct integre a KageStream^).
echo Si la fenetre ne s'ouvre pas ou plante immediatement, relance ce script depuis
echo le terminal "MSYS2 MinGW64" pour que les bibliotheques GTK soient sur le PATH.
echo.

"%DIST_DIR%\%APP_NAME%.exe"
set "RUN_RESULT=%ERRORLEVEL%"

echo.
echo %APP_NAME% s'est ferme (code %RUN_RESULT%).
exit /B %RUN_RESULT%

:print_msys2_help
echo.
echo 1. Installe MSYS2 depuis https://www.msys2.org/
echo 2. Ouvre le terminal "MSYS2 MinGW64" ^(pas "MSYS2 MSYS", pas "MSYS2 UCRT64"^).
echo 3. Dans ce terminal, lance :
echo      pacman -Syu
echo    Si le terminal se ferme et demande de le relancer, relance-le puis refais pacman -Syu.
echo 4. Toujours dans ce terminal, lance :
echo      pacman -S --needed mingw-w64-x86_64-python mingw-w64-x86_64-python-pip mingw-w64-x86_64-python-gobject mingw-w64-x86_64-gtk3
echo 5. Relance ce script depuis ce meme terminal MSYS2 MinGW64 :
echo      ./build-windows.bat
exit /B 0
