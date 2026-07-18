#!/usr/bin/env bash
set -euo pipefail

APP_NAME="GUIStream"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPDIR="$ROOT_DIR/AppDir"
ICON_SRC="$ROOT_DIR/assets/icons/GUIStream.png"
APPIMAGETOOL="$ROOT_DIR/appimagetool-x86_64.AppImage"
VENV_DIR="$ROOT_DIR/.venv"
SOURCE_FILE="$ROOT_DIR/guistream.py"
SPEC_FILE="$ROOT_DIR/GUIStream.spec"
OUTPUT_APPIMAGE="$ROOT_DIR/GUIStream-x86_64.AppImage"

echo "== GUIStream AppImage build =="
echo "Dossier : $ROOT_DIR"

if [ ! -f "$SOURCE_FILE" ]; then
    echo "Erreur : source introuvable : $SOURCE_FILE"
    exit 1
fi

if [ ! -f "$SPEC_FILE" ]; then
    echo "Erreur : fichier PyInstaller introuvable : $SPEC_FILE"
    exit 1
fi

if ! grep -qF 'self.notebook = Gtk.Notebook()' "$SOURCE_FILE"; then
    echo "Erreur : $SOURCE_FILE ne contient pas la nouvelle interface à onglets."
    echo "Le build est arrêté pour éviter de recréer accidentellement l’ancienne interface."
    exit 1
fi

echo "Source embarquée : $SOURCE_FILE"
echo "Empreinte de la source :"
sha256sum "$SOURCE_FILE"
cd "$ROOT_DIR"

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO_ID="${ID:-unknown}"
        DISTRO_LIKE="${ID_LIKE:-}"
    else
        DISTRO_ID="unknown"
        DISTRO_LIKE=""
    fi
}

detect_family() {
    detect_distro
    DISTRO_FAMILY="unknown"

    case "$DISTRO_ID" in
        arch|cachyos|endeavouros|manjaro)
            DISTRO_FAMILY="arch"
            ;;
        debian|ubuntu|linuxmint|pop)
            DISTRO_FAMILY="debian"
            ;;
        fedora|rhel|centos|rocky|almalinux)
            DISTRO_FAMILY="redhat"
            ;;
        *)
            if echo "$DISTRO_LIKE" | grep -qi "arch"; then
                DISTRO_FAMILY="arch"
            elif echo "$DISTRO_LIKE" | grep -qi "debian"; then
                DISTRO_FAMILY="debian"
            elif echo "$DISTRO_LIKE" | grep -Eqi "fedora|rhel"; then
                DISTRO_FAMILY="redhat"
            fi
            ;;
    esac

    echo "Distribution détectée : $DISTRO_ID"
    echo "Famille détectée : $DISTRO_FAMILY"
}

install_system_deps() {
    echo ""
    echo "== Installation des dépendances système =="
    echo "Cette étape peut demander ton mot de passe sudo."

    if ! command_exists sudo; then
        echo "Erreur : sudo est introuvable."
        echo "Installe les dépendances manuellement puis relance le build."
        exit 1
    fi

    case "$DISTRO_FAMILY" in
        arch)
            sudo pacman -S --needed --noconfirm \
                python python-pip python-virtualenv python-gobject gtk3 \
                ffmpeg wget fuse2 patchelf desktop-file-utils
            ;;
        debian)
            sudo apt update
            sudo apt install -y \
                python3 python3-pip python3-venv python3-gi gir1.2-gtk-3.0 \
                ffmpeg wget fuse patchelf desktop-file-utils
            ;;
        redhat)
            sudo dnf install -y \
                python3 python3-pip python3-gobject gtk3 \
                ffmpeg wget fuse fuse-libs patchelf desktop-file-utils
            ;;
        *)
            echo "Distribution non reconnue."
            echo ""
            echo "Dépendances à installer manuellement :"
            echo "- python3"
            echo "- pip"
            echo "- python venv"
            echo "- PyGObject / GTK3"
            echo "- ffmpeg / ffprobe"
            echo "- wget"
            echo "- fuse ou fuse2"
            echo "- patchelf"
            echo "- desktop-file-utils"
            exit 1
            ;;
    esac
}

check_system_deps() {
    MISSING=0

    if ! command_exists python3; then
        echo "Manquant : python3"
        MISSING=1
    fi

    if ! command_exists ffmpeg; then
        echo "Manquant : ffmpeg"
        MISSING=1
    fi

    if ! command_exists ffprobe; then
        echo "Manquant : ffprobe"
        MISSING=1
    fi

    if ! command_exists wget; then
        echo "Manquant : wget"
        MISSING=1
    fi

    if ! command_exists patchelf; then
        echo "Manquant : patchelf"
        MISSING=1
    fi

    if ! python3 -c "import venv" >/dev/null 2>&1; then
        echo "Manquant : module Python venv"
        MISSING=1
    fi

    if ! python3 -c "import gi; gi.require_version('Gtk','3.0')" >/dev/null 2>&1; then
        echo "Manquant : GTK/PyGObject"
        MISSING=1
    fi

    return "$MISSING"
}

write_apprun() {
    cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"

export PATH="$HERE/usr/bin:$PATH"

exec "$HERE/usr/bin/GUIStream" "$@"
EOF

    chmod +x "$APPDIR/AppRun"
}

write_desktop_file() {
    echo "== Génération du fichier .desktop =="

    cat > "$APPDIR/GUIStream.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=GUIStream
GenericName=Stream Recorder
Comment=Graphical Streamlink recorder
Exec=GUIStream
Icon=GUIStream
Categories=AudioVideo;Recorder;Video;
Terminal=false
StartupNotify=true
EOF

    mkdir -p "$APPDIR/usr/share/applications"
    cp "$APPDIR/GUIStream.desktop" "$APPDIR/usr/share/applications/GUIStream.desktop"

    if command_exists desktop-file-validate; then
        desktop-file-validate "$APPDIR/GUIStream.desktop" || true
    fi
}

echo "== Détection distribution =="
detect_family

echo "== Vérification des dépendances système =="
if check_system_deps; then
    echo "Dépendances système OK."
else
    echo ""
    read -r -p "Des dépendances manquent. Tenter l'installation automatique ? [o/N] " answer
    case "$answer" in
        o|O|oui|Oui|OUI|y|Y|yes|YES)
            install_system_deps
            ;;
        *)
            echo "Installation annulée."
            exit 1
            ;;
    esac
fi

echo "== Vérification finale des dépendances système =="
if ! check_system_deps; then
    echo "Certaines dépendances sont encore manquantes."
    exit 1
fi

echo "== Création de l'environnement Python local =="
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv --system-site-packages "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip wheel setuptools
python -m pip install --upgrade -r "$ROOT_DIR/requirements.txt"

echo "== Vérification Python/GTK dans le venv =="
if ! python -c "import gi; gi.require_version('Gtk','3.0')" >/dev/null 2>&1; then
    echo "GTK/PyGObject n'est pas visible depuis le venv."
    echo "Solution :"
    echo "rm -rf .venv"
    echo "./build-linux.sh"
    exit 1
fi

echo "== Nettoyage build =="
rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist" "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

echo "== Build PyInstaller =="
python -m PyInstaller \
    --clean \
    --noconfirm \
    --distpath "$ROOT_DIR/dist" \
    --workpath "$ROOT_DIR/build" \
    "$SPEC_FILE"

if [ ! -x "$ROOT_DIR/dist/$APP_NAME" ]; then
    echo "Erreur : PyInstaller n’a pas produit $ROOT_DIR/dist/$APP_NAME"
    exit 1
fi

echo "== Copie des binaires dans AppDir =="
cp "$ROOT_DIR/dist/$APP_NAME" "$APPDIR/usr/bin/$APP_NAME"
cp "$(command -v ffmpeg)" "$APPDIR/usr/bin/ffmpeg"
cp "$(command -v ffprobe)" "$APPDIR/usr/bin/ffprobe"

if command_exists streamlink; then
    cp "$(command -v streamlink)" "$APPDIR/usr/bin/streamlink" || true
elif [ -f "$VENV_DIR/bin/streamlink" ]; then
    cp "$VENV_DIR/bin/streamlink" "$APPDIR/usr/bin/streamlink"
else
    echo "Erreur : Streamlink introuvable après installation Python."
    exit 1
fi

echo "== Génération AppRun =="
write_apprun

write_desktop_file

echo "== Copie de l'icône =="
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$APPDIR/GUIStream.png"
    cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/GUIStream.png"
else
    echo "Icône introuvable : $ICON_SRC"
    exit 1
fi

echo "== Téléchargement appimagetool si absent =="
if [ ! -f "$APPIMAGETOOL" ]; then
    wget -O "$APPIMAGETOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

echo "== Création AppImage =="
cd "$ROOT_DIR"
rm -f "$OUTPUT_APPIMAGE"
ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "$OUTPUT_APPIMAGE"

echo ""
echo "Terminé."
echo "AppImage générée :"
ls -lh "$OUTPUT_APPIMAGE"
echo "Empreinte de l’AppImage :"
sha256sum "$OUTPUT_APPIMAGE"
echo ""
echo "Lancement :"
printf '  %q\n' "$OUTPUT_APPIMAGE"
