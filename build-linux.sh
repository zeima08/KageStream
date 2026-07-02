#!/usr/bin/env bash
set -e

APP_NAME="GUIStream"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPDIR="$ROOT_DIR/AppDir"
ICON_SRC="$ROOT_DIR/assets/icons/GUIStream.png"
APPIMAGETOOL="$ROOT_DIR/appimagetool-x86_64.AppImage"

echo "== GUIStream AppImage build =="
echo "Dossier : $ROOT_DIR"

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

need_cmd() {
    if ! command_exists "$1"; then
        echo "Commande manquante : $1"
        exit 1
    fi
}

echo "== Vérification des outils système =="
need_cmd python3
need_cmd pip
need_cmd ffmpeg
need_cmd ffprobe

if ! python3 -c "import gi; gi.require_version('Gtk','3.0')" >/dev/null 2>&1; then
    echo "GTK/PyGObject manquant."
    echo ""
    echo "Fedora : sudo dnf install python3-gobject gtk3"
    echo "Debian/Ubuntu : sudo apt install python3-gi gir1.2-gtk-3.0"
    echo "Arch : sudo pacman -S python-gobject gtk3"
    exit 1
fi

echo "== Installation Python locale =="
python3 -m pip install --user --upgrade -r "$ROOT_DIR/requirements.txt"

echo "== Nettoyage =="
rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist" "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

echo "== Build PyInstaller =="
python3 -m PyInstaller \
    --onefile \
    --windowed \
    --name "$APP_NAME" \
    "$ROOT_DIR/guistream.py"

echo "== Copie dans AppDir =="
cp "$ROOT_DIR/dist/$APP_NAME" "$APPDIR/usr/bin/$APP_NAME"
cp "$(command -v ffmpeg)" "$APPDIR/usr/bin/ffmpeg"
cp "$(command -v ffprobe)" "$APPDIR/usr/bin/ffprobe"

# Streamlink peut être un script Python dans ~/.local/bin ou /usr/bin.
# On le copie si possible, sinon l'app utilisera le streamlink système.
if command_exists streamlink; then
    cp "$(command -v streamlink)" "$APPDIR/usr/bin/streamlink" || true
else
    echo "Streamlink n'est pas dans le PATH. Il sera embarqué via PyInstaller si disponible dans Python, sinon installe-le."
fi

cp "$ROOT_DIR/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
cp "$ROOT_DIR/GUIStream.desktop" "$APPDIR/GUIStream.desktop"

if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$APPDIR/GUIStream.png"
    cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/GUIStream.png"
else
    echo "Icône introuvable : $ICON_SRC"
    exit 1
fi

echo "== Téléchargement appimagetool si absent =="
if [ ! -f "$APPIMAGETOOL" ]; then
    wget -O "$APPIMAGETOOL" "https://github.com/AppImage/AppImageKit/releases/latest/download/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

echo "== Création AppImage =="
cd "$ROOT_DIR"
ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR"

echo ""
echo "Terminé."
echo "Fichier généré :"
ls -lh "$ROOT_DIR"/*.AppImage || true
