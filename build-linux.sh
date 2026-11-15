#!/usr/bin/env bash
set -euo pipefail

APP_NAME="KageStream"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPDIR="$ROOT_DIR/AppDir"
ICON_SRC="$ROOT_DIR/assets/icons/kagestream.png"
APPIMAGETOOL="$ROOT_DIR/appimagetool-x86_64.AppImage"
VENV_DIR="$ROOT_DIR/.venv"
SOURCE_FILE="$ROOT_DIR/kagestream.py"
APP_PACKAGE_FILE="$ROOT_DIR/kagestream/app.py"
SPEC_FILE="$ROOT_DIR/kagestream.spec"
OUTPUT_APPIMAGE="$ROOT_DIR/KageStream-x86_64.AppImage"

echo "== KageStream AppImage build =="
echo "Dossier : $ROOT_DIR"

if [ ! -f "$SOURCE_FILE" ]; then
    echo "Erreur : source introuvable : $SOURCE_FILE"
    exit 1
fi

if [ ! -f "$SPEC_FILE" ]; then
    echo "Erreur : fichier PyInstaller introuvable : $SPEC_FILE"
    exit 1
fi

if [ ! -f "$APP_PACKAGE_FILE" ]; then
    echo "Erreur : $APP_PACKAGE_FILE introuvable."
    echo "kagestream.py doit rester un lanceur minimal qui importe le package kagestream/."
    exit 1
fi

if ! grep -qF 'from kagestream.main import main' "$SOURCE_FILE"; then
    echo "Erreur : $SOURCE_FILE ne lance plus l’application via le package kagestream/."
    exit 1
fi

if ! grep -qF 'self.stack = Gtk.Stack()' "$APP_PACKAGE_FILE"; then
    echo "Erreur : $APP_PACKAGE_FILE ne contient pas la nouvelle interface à barre latérale."
    echo "Le build est arrêté pour éviter de recréer accidentellement l’ancienne interface à onglets."
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

exec "$HERE/usr/bin/KageStream" "$@"
EOF

    chmod +x "$APPDIR/AppRun"
}

write_desktop_file() {
    echo "== Génération du fichier .desktop =="

    cat > "$APPDIR/KageStream.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=kagestream
GenericName=Simple but powerful stream recorder
Comment=Graphical Streamlink recorder   
Exec=KageStream
Icon=KageStream
Categories=AudioVideo;Recorder;Video;
Terminal=false
StartupNotify=true
EOF

    mkdir -p "$APPDIR/usr/share/applications"
    cp "$APPDIR/KageStream.desktop" "$APPDIR/usr/share/applications/KageStream.desktop"

    if command_exists desktop-file-validate; then
        desktop-file-validate "$APPDIR/KageStream.desktop" || true
    fi
}

echo "== Détection distribution =="
detect_family

echo "== Vérification des dépendances système =="
if check_system_deps; then
    echo "Dépendances système OK."
else
    echo ""
    if [ -n "${CI:-}" ] || [ "${KAGESTREAM_ASSUME_YES:-}" = "1" ]; then
        answer="o"
    else
        read -r -p "Des dépendances manquent. Tenter l'installation automatique ? [o/N] " answer
    fi
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
python -m pip install --upgrade -r "$ROOT_DIR/requirements-build.txt"

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

# On n'embarque un outil que s'il est réellement portable pour la machine
# cible. Un binaire lié dynamiquement aux bibliothèques du poste de build
# (ffmpeg → libav*) ou un script Python à shebang local (streamlink du venv)
# serait cassé chez l'utilisateur — et, pire, masquerait celui du système
# puisque AppRun place usr/bin en tête du PATH. KageStream sait installer
# ces deux outils de façon vérifiée depuis Outils.
copy_if_portable() {
    local source="$1" name="$2" kind
    if [ -z "$source" ] || [ ! -f "$source" ]; then
        echo "  $name : introuvable, non embarqué (installable depuis Outils)"
        return 0
    fi
    kind="$(file -b "$source" 2>/dev/null || true)"
    case "$kind" in
        *ELF*dynamically\ linked*)
            echo "  $name : binaire lié dynamiquement, non embarqué (installable depuis Outils)"
            return 0
            ;;
        *ELF*)
            cp "$source" "$APPDIR/usr/bin/$name"
            echo "  $name : embarqué (autonome)"
            return 0
            ;;
        *)
            echo "  $name : $kind — non portable, non embarqué (installable depuis Outils)"
            return 0
            ;;
    esac
}

copy_if_portable "$(command -v ffmpeg 2>/dev/null)" ffmpeg
copy_if_portable "$(command -v ffprobe 2>/dev/null)" ffprobe
copy_if_portable "$(command -v streamlink 2>/dev/null || echo "$VENV_DIR/bin/streamlink")" streamlink

echo "== Génération AppRun =="
write_apprun

write_desktop_file

echo "== Copie de l'icône =="
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$APPDIR/KageStream.png"
    cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/KageStream.png"
else
    echo "Icône introuvable : $ICON_SRC"
    exit 1
fi

echo "== appimagetool : version épinglée et vérifiée =="
# L'appimagetool téléchargé est EXÉCUTÉ : il est épinglé à une version précise
# et vérifié par SHA-256 à chaque utilisation, y compris s'il est déjà présent
# sur le disque (un fichier en cache n'est jamais exécuté sans contrôle).
APPIMAGETOOL_VERSION="${KAGESTREAM_APPIMAGETOOL_VERSION:-1.9.1}"
APPIMAGETOOL_SHA256="${KAGESTREAM_APPIMAGETOOL_SHA256:-ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0}"

verify_appimagetool() {
    [ -f "$1" ] || return 1
    local actual
    actual="$(sha256sum "$1" | awk '{print $1}')"
    [ "$actual" = "$APPIMAGETOOL_SHA256" ]
}

if command -v appimagetool >/dev/null 2>&1; then
    # Un appimagetool fourni par la distribution est suivi par ses mises à
    # jour : rien à télécharger ni à vérifier ici.
    APPIMAGETOOL="$(command -v appimagetool)"
    echo "Utilisation de l'appimagetool du système : $APPIMAGETOOL"
elif verify_appimagetool "$APPIMAGETOOL"; then
    echo "appimagetool déjà présent et vérifié (SHA-256)."
else
    TMP_TOOL="$(mktemp "${TMPDIR:-/tmp}/appimagetool.XXXXXX")"
    echo "Téléchargement d'appimagetool $APPIMAGETOOL_VERSION..."
    if ! wget -O "$TMP_TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"; then
        rm -f "$TMP_TOOL"
        echo "ERREUR : téléchargement d'appimagetool impossible." >&2
        echo "  Vérifie ta connexion, ou installe le paquet appimagetool de ta distribution." >&2
        exit 1
    fi
    ACTUAL_SHA="$(sha256sum "$TMP_TOOL" | awk '{print $1}')"
    if [ "$ACTUAL_SHA" != "$APPIMAGETOOL_SHA256" ]; then
        rm -f "$TMP_TOOL"
        echo "ERREUR : empreinte SHA-256 d'appimagetool incorrecte." >&2
        echo "  attendu : $APPIMAGETOOL_SHA256" >&2
        echo "  obtenu  : $ACTUAL_SHA" >&2
        exit 1
    fi
    mv "$TMP_TOOL" "$APPIMAGETOOL"
    chmod +x "$APPIMAGETOOL"
    echo "appimagetool $APPIMAGETOOL_VERSION vérifié et installé."
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
