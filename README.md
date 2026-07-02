# GUIStream by Zeima

GUIStream est une interface graphique simple pour Streamlink.

Fonctions principales :

- tester un lien ;
- détecter les qualités disponibles ;
- enregistrer en `.ts` ;
- remuxer en `.mkv` ou `.mp4` avec FFmpeg ;
- remux même après un arrêt manuel ;
- afficher durée et taille ;
- ouvrir le dossier de sortie.

## Structure

```txt
guistream_project/
├── guistream.py
├── requirements.txt
├── build-linux.sh
├── build-windows.bat
├── GUIStream.desktop
├── AppRun
└── assets/
    └── icons/
        └── GUIStream.png
```

## Dépendances Linux

### Fedora

```bash
sudo dnf install python3 python3-pip python3-gobject gtk3 ffmpeg wget fuse fuse-libs patchelf
```

Si FFmpeg n'est pas disponible :

```bash
sudo dnf install https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install ffmpeg
```

### Debian / Ubuntu

```bash
sudo apt install python3 python3-pip python3-gi gir1.2-gtk-3.0 ffmpeg wget fuse patchelf
```

### Arch Linux

```bash
sudo pacman -S python python-pip python-gobject gtk3 ffmpeg wget fuse2 patchelf
```

## Build AppImage Linux

Depuis le dossier du projet :

```bash
chmod +x build-linux.sh
./build-linux.sh
```

Le fichier final sera :

```txt
GUIStream-x86_64.AppImage
```

## Lancer l'AppImage

```bash
chmod +x GUIStream-x86_64.AppImage
./GUIStream-x86_64.AppImage
```

## Build Windows

Depuis Windows :

```bat
build-windows.bat
```

Le fichier final sera :

```txt
dist\GUIStream.exe
```

## Note importante

GTK/PyGObject est utilisé pour l'interface.  
L'AppImage utilise en général GTK du système Linux.

FFmpeg et FFprobe sont copiés dans l'AppImage.  
Streamlink est aussi copié si `streamlink` est présent dans le PATH.
