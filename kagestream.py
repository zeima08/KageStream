#!/usr/bin/env python3
import os
import sys
import gi
import re
import hashlib
import shutil
import signal
import subprocess
import threading
import time
import platform
import json
import tarfile
import zipfile
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse
from datetime import datetime

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

APP_NAME = "KageStream"
APP_AUTHOR = "Zeima"
APP_TITLE = f"{APP_NAME} by {APP_AUTHOR}"

BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ICON_PATH = os.path.join(BASE_DIR, "assets", "icons", "kagestream.png")

YTDLP_RELEASE_BASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download"
DENO_RELEASE_BASE = "https://github.com/denoland/deno/releases/latest/download"
GITHUB_API_BASE = "https://api.github.com/repos"


BAD_STREAM_PATTERNS = [
    "error", "failed", "timeout", "timed out", "discontinuity",
    "corrupt", "packet corrupt", "segment", "retry",
    "403", "404", "connection reset", "connection aborted"
]

FFMPEG_HEALTH_PATTERNS = [
    "non-monotonous dts", "invalid timestamp", "corrupt",
    "packet corrupt", "error while decoding", "missing picture",
    "pts", "dts", "timestamp", "invalid data"
]


def is_frozen():
    return getattr(sys, "frozen", False)


def app_dir():
    return os.path.dirname(sys.executable) if is_frozen() else os.path.dirname(os.path.abspath(__file__))


def external_app_dir():
    """Dossier contenant l'AppImage, ou le script hors AppImage."""
    appimage_path = os.environ.get("APPIMAGE")
    if appimage_path:
        return os.path.dirname(os.path.realpath(appimage_path))

    return app_dir()


def user_data_dir():
    """Dossier inscriptible et persistant, y compris depuis une AppImage."""
    if sys.platform == "win32":
        base = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        )
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share"
        )

    return os.path.join(base, APP_NAME)


def user_bin_dir():
    return os.path.join(user_data_dir(), "bin")


def find_tool(name):
    for path in [
        os.path.join(user_bin_dir(), name),
        os.path.join(user_bin_dir(), name + ".exe"),
        os.path.join(app_dir(), "bin", name),
        os.path.join(app_dir(), "bin", name + ".exe"),
    ]:
        if os.path.exists(path):
            return path

    return shutil.which(name)


def ytdlp_release_asset():
    """Retourne le binaire autonome officiel adapté à la machine."""
    machine = platform.machine().lower()

    if sys.platform == "win32":
        if machine in ("arm64", "aarch64"):
            return "yt-dlp_arm64.exe", "yt-dlp.exe"
        return "yt-dlp.exe", "yt-dlp.exe"

    if sys.platform == "darwin":
        return "yt-dlp_macos", "yt-dlp"

    if sys.platform.startswith("linux"):
        if machine in ("x86_64", "amd64"):
            return "yt-dlp_linux", "yt-dlp"
        if machine in ("arm64", "aarch64"):
            return "yt-dlp_linux_aarch64", "yt-dlp"
        if machine in ("armv7l", "armv7"):
            return "yt-dlp_linux_armv7l", "yt-dlp"

    raise RuntimeError(
        f"Aucun binaire yt-dlp autonome prévu pour {sys.platform} / {machine}."
    )


def ytdlp_expected_checksum(checksums_text, asset_name):
    for line in checksums_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == asset_name:
            checksum = parts[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", checksum):
                return checksum

    raise RuntimeError(f"Somme SHA-256 officielle introuvable pour {asset_name}.")


def download_ytdlp_binary(progress_callback=None, timeout=30):
    """Télécharge, vérifie et installe atomiquement le binaire officiel yt-dlp."""
    asset_name, installed_name = ytdlp_release_asset()
    target_dir = user_bin_dir()
    target_path = os.path.join(target_dir, installed_name)
    temporary_path = target_path + (".download.exe" if sys.platform == "win32" else ".download")
    os.makedirs(target_dir, exist_ok=True)

    headers = {"User-Agent": f"{APP_NAME} Dependency Installer"}
    checksums_request = urllib.request.Request(
        f"{YTDLP_RELEASE_BASE}/SHA2-256SUMS",
        headers=headers
    )

    try:
        if progress_callback:
            progress_callback("Récupération de la somme SHA-256 officielle…")

        with urllib.request.urlopen(checksums_request, timeout=timeout) as response:
            checksums_text = response.read().decode("utf-8", errors="replace")

        expected_checksum = ytdlp_expected_checksum(checksums_text, asset_name)
        binary_request = urllib.request.Request(
            f"{YTDLP_RELEASE_BASE}/{asset_name}",
            headers=headers
        )

        digest = hashlib.sha256()
        downloaded = 0

        with urllib.request.urlopen(binary_request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)

            with open(temporary_path, "wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)

                    if progress_callback:
                        if total:
                            percent = min(100, int(downloaded * 100 / total))
                            progress_callback(f"Téléchargement de yt-dlp… {percent} %")
                        else:
                            progress_callback(
                                f"Téléchargement de yt-dlp… {downloaded / 1048576:.1f} Mio"
                            )

        actual_checksum = digest.hexdigest().lower()
        if actual_checksum != expected_checksum:
            raise RuntimeError(
                "La somme SHA-256 du fichier téléchargé ne correspond pas à la somme officielle."
            )

        if sys.platform != "win32":
            os.chmod(temporary_path, 0o755)

        validation = subprocess.run(
            [temporary_path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20
        )
        if validation.returncode != 0:
            raise RuntimeError("Le binaire yt-dlp téléchargé ne démarre pas correctement.")

        os.replace(temporary_path, target_path)
        version = validation.stdout.strip().splitlines()[0] if validation.stdout.strip() else "inconnue"
        return target_path, version, expected_checksum

    except Exception:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass
        raise


def fetch_text(url, timeout=30):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"{APP_NAME} Dependency Installer"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def download_verified_file(url, destination, expected_checksum, label,
                           progress_callback=None, timeout=60):
    expected_checksum = (expected_checksum or "").lower().removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_checksum):
        raise RuntimeError(f"Somme SHA-256 invalide ou absente pour {label}.")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"{APP_NAME} Dependency Installer"}
    )
    digest = hashlib.sha256()
    downloaded = 0
    last_percent = -1

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            with open(destination, "wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)

                    if progress_callback:
                        if total:
                            percent = min(100, int(downloaded * 100 / total))
                            if percent != last_percent:
                                last_percent = percent
                                progress_callback(f"Téléchargement de {label}… {percent} %")
                        elif downloaded % (4 * 1024 * 1024) < len(chunk):
                            progress_callback(
                                f"Téléchargement de {label}… {downloaded / 1048576:.1f} Mio"
                            )

        actual_checksum = digest.hexdigest().lower()
        if actual_checksum != expected_checksum:
            raise RuntimeError(
                f"La somme SHA-256 de {label} ne correspond pas à la somme publiée."
            )
        return actual_checksum

    except Exception:
        try:
            if os.path.exists(destination):
                os.remove(destination)
        except OSError:
            pass
        raise


def github_latest_release(repo, timeout=30):
    return fetch_json(f"{GITHUB_API_BASE}/{repo}/releases/latest", timeout=timeout)


def github_asset_details(release, asset_name):
    for asset in release.get("assets", []):
        if asset.get("name") == asset_name:
            return (
                asset.get("browser_download_url", ""),
                (asset.get("digest") or "").removeprefix("sha256:")
            )
    raise RuntimeError(f"Fichier de version introuvable : {asset_name}.")


def deno_release_asset():
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        architecture = "x86_64"
    elif machine in ("arm64", "aarch64"):
        architecture = "aarch64"
    else:
        raise RuntimeError(f"Architecture Deno non prise en charge : {machine}.")

    if sys.platform.startswith("linux"):
        platform_name = "unknown-linux-gnu"
    elif sys.platform == "darwin":
        platform_name = "apple-darwin"
    elif sys.platform == "win32":
        platform_name = "pc-windows-msvc"
    else:
        raise RuntimeError(f"Plateforme Deno non prise en charge : {sys.platform}.")

    return f"deno-{architecture}-{platform_name}.zip", "deno.exe" if sys.platform == "win32" else "deno"


def download_deno_binary(progress_callback=None, timeout=60):
    asset_name, installed_name = deno_release_asset()
    target_dir = user_bin_dir()
    target_path = os.path.join(target_dir, installed_name)
    archive_path = os.path.join(target_dir, ".deno.download.zip")
    temporary_path = target_path + (".download.exe" if sys.platform == "win32" else ".download")
    os.makedirs(target_dir, exist_ok=True)

    if progress_callback:
        progress_callback("Récupération de la somme SHA-256 officielle de Deno…")

    checksum_text = fetch_text(
        f"{DENO_RELEASE_BASE}/{asset_name}.sha256sum",
        timeout=timeout
    )
    expected_checksum = checksum_text.strip().split()[0].lower() if checksum_text.strip() else ""

    try:
        download_verified_file(
            f"{DENO_RELEASE_BASE}/{asset_name}",
            archive_path,
            expected_checksum,
            "Deno",
            progress_callback,
            timeout
        )

        with zipfile.ZipFile(archive_path) as archive:
            member = next(
                (name for name in archive.namelist() if os.path.basename(name) == installed_name),
                None
            )
            if not member:
                raise RuntimeError("Le binaire Deno est absent de l’archive officielle.")
            with archive.open(member) as source, open(temporary_path, "wb") as destination:
                shutil.copyfileobj(source, destination)

        if sys.platform != "win32":
            os.chmod(temporary_path, 0o755)

        validation = subprocess.run(
            [temporary_path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20
        )
        if validation.returncode != 0:
            raise RuntimeError("Le binaire Deno téléchargé ne démarre pas correctement.")

        os.replace(temporary_path, target_path)
        version = validation.stdout.strip().splitlines()[0] if validation.stdout.strip() else "Deno"
        return target_path, version, expected_checksum

    finally:
        for path in (archive_path, temporary_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


def download_streamlink_appimage(progress_callback=None, timeout=90):
    if not sys.platform.startswith("linux"):
        raise RuntimeError("L’installation directe de Streamlink est disponible sous Linux.")

    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        suffix = "_x86_64.AppImage"
    elif machine in ("arm64", "aarch64"):
        suffix = "_aarch64.AppImage"
    else:
        raise RuntimeError(f"Architecture Streamlink non prise en charge : {machine}.")

    if progress_callback:
        progress_callback("Recherche de la dernière AppImage officielle Streamlink…")
    release = github_latest_release("streamlink/streamlink-appimage", timeout)
    candidates = [
        asset for asset in release.get("assets", [])
        if asset.get("name", "").startswith("streamlink-")
        and asset.get("name", "").endswith(suffix)
    ]
    if not candidates:
        raise RuntimeError("AppImage Streamlink officielle introuvable pour cette architecture.")

    asset = candidates[0]
    expected_checksum = (asset.get("digest") or "").removeprefix("sha256:")
    target_dir = user_bin_dir()
    appimage_path = os.path.join(target_dir, "streamlink.AppImage")
    archive_path = appimage_path + ".download"
    launcher_path = os.path.join(target_dir, "streamlink")
    launcher_temporary = launcher_path + ".download"
    os.makedirs(target_dir, exist_ok=True)

    try:
        checksum = download_verified_file(
            asset.get("browser_download_url", ""),
            archive_path,
            expected_checksum,
            "Streamlink",
            progress_callback,
            timeout
        )
        os.chmod(archive_path, 0o755)

        environment = os.environ.copy()
        environment["APPIMAGE_EXTRACT_AND_RUN"] = "1"
        validation = subprocess.run(
            [archive_path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=90,
            env=environment
        )
        if validation.returncode != 0:
            raise RuntimeError("L’AppImage Streamlink téléchargée ne démarre pas correctement.")

        os.replace(archive_path, appimage_path)
        launcher = (
            "#!/bin/sh\n"
            "SELF_DIR=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
            "APPIMAGE_EXTRACT_AND_RUN=1 exec \"$SELF_DIR/streamlink.AppImage\" \"$@\"\n"
        )
        with open(launcher_temporary, "w", encoding="utf-8") as handle:
            handle.write(launcher)
        os.chmod(launcher_temporary, 0o755)
        os.replace(launcher_temporary, launcher_path)

        version = validation.stdout.strip().splitlines()[0] if validation.stdout.strip() else release.get("tag_name", "Streamlink")
        return launcher_path, version, checksum

    finally:
        for path in (archive_path, launcher_temporary):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


def download_ffmpeg_binaries(progress_callback=None, timeout=120):
    if not sys.platform.startswith("linux"):
        raise RuntimeError("L’installation directe de FFmpeg est disponible sous Linux.")

    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        platform_name = "linux64"
    elif machine in ("arm64", "aarch64"):
        platform_name = "linuxarm64"
    else:
        raise RuntimeError(f"Architecture FFmpeg non prise en charge : {machine}.")

    if progress_callback:
        progress_callback("Recherche du dernier build Linux FFmpeg recommandé…")
    release = github_latest_release("BtbN/FFmpeg-Builds", timeout)
    pattern = re.compile(
        rf"^ffmpeg-n(\d+(?:\.\d+)+)-latest-{platform_name}-gpl-\1\.tar\.xz$"
    )
    candidates = []
    for asset in release.get("assets", []):
        match = pattern.match(asset.get("name", ""))
        if match:
            candidates.append((version_tuple(match.group(1)), asset))
    if not candidates:
        raise RuntimeError("Build Linux FFmpeg vérifiable introuvable pour cette architecture.")

    _version_key, asset = max(candidates, key=lambda item: item[0])
    expected_checksum = (asset.get("digest") or "").removeprefix("sha256:")
    target_dir = user_bin_dir()
    archive_path = os.path.join(target_dir, ".ffmpeg.download.tar.xz")
    temporary_paths = {
        "ffmpeg": os.path.join(target_dir, ".ffmpeg.download"),
        "ffprobe": os.path.join(target_dir, ".ffprobe.download"),
    }
    os.makedirs(target_dir, exist_ok=True)

    try:
        checksum = download_verified_file(
            asset.get("browser_download_url", ""),
            archive_path,
            expected_checksum,
            "FFmpeg + FFprobe",
            progress_callback,
            timeout
        )

        found = set()
        with tarfile.open(archive_path, mode="r:xz") as archive:
            for member in archive.getmembers():
                binary_name = os.path.basename(member.name)
                if (
                    member.isfile()
                    and binary_name in temporary_paths
                    and "/bin/" in member.name.replace("\\", "/")
                ):
                    source = archive.extractfile(member)
                    if source is None:
                        continue
                    with source, open(temporary_paths[binary_name], "wb") as destination:
                        shutil.copyfileobj(source, destination)
                    os.chmod(temporary_paths[binary_name], 0o755)
                    found.add(binary_name)

        if found != set(temporary_paths):
            raise RuntimeError("FFmpeg ou FFprobe est absent de l’archive téléchargée.")

        versions = {}
        for binary_name, temporary_path in temporary_paths.items():
            validation = subprocess.run(
                [temporary_path, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=20
            )
            if validation.returncode != 0:
                raise RuntimeError(f"Le binaire {binary_name} téléchargé ne démarre pas.")
            versions[binary_name] = (
                validation.stdout.strip().splitlines()[0]
                if validation.stdout.strip()
                else binary_name
            )

        for binary_name, temporary_path in temporary_paths.items():
            os.replace(temporary_path, os.path.join(target_dir, binary_name))

        return (
            os.path.join(target_dir, "ffmpeg"),
            versions["ffmpeg"],
            checksum
        )

    finally:
        for path in [archive_path] + list(temporary_paths.values()):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


def find_javascript_runtime():
    candidates = [
        ("deno", ["deno"]),
        ("node", ["node", "nodejs"]),
        ("quickjs", ["qjs", "quickjs"]),
        ("bun", ["bun"]),
    ]

    for runtime_name, binaries in candidates:
        for binary in binaries:
            path = find_tool(binary)
            if path:
                return runtime_name, path

    return None, None


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120] if name else ""


def playlist_title_from_location(location):
    try:
        parsed = urlparse(location)
        path = unquote(parsed.path).rstrip("/")
        name = os.path.basename(path)
        return sanitize_filename(name) or parsed.hostname or location
    except Exception:
        return location


def resolve_playlist_location(location, playlist_path):
    location = (location or "").strip()
    if not location:
        return ""

    if re.match(r"^[A-Za-z]:[\\/]", location) or os.path.isabs(location):
        return location

    parsed = urlparse(location)
    if parsed.scheme:
        return location

    return os.path.abspath(os.path.join(os.path.dirname(playlist_path), location))


def deduplicate_playlist_entries(entries):
    unique = []
    seen = set()

    for entry in entries:
        url = entry.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(entry)

    return unique


def parse_m3u_file(path):
    entries = []
    current_title = ""
    current_group = ""

    with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue

            if line.upper().startswith("#EXTINF:"):
                metadata, separator, label = line.partition(",")
                current_title = label.strip() if separator else ""

                group_match = re.search(
                    r'group-title\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
                    metadata,
                    flags=re.IGNORECASE
                )
                if group_match:
                    current_group = (group_match.group(1) or group_match.group(2) or "").strip()

                if not current_title:
                    name_match = re.search(
                        r'tvg-name\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
                        metadata,
                        flags=re.IGNORECASE
                    )
                    if name_match:
                        current_title = (name_match.group(1) or name_match.group(2) or "").strip()
                continue

            if line.upper().startswith("#EXTGRP:"):
                current_group = line.split(":", 1)[1].strip()
                continue

            if line.startswith("#"):
                continue

            location = resolve_playlist_location(line, path)
            if location:
                entries.append({
                    "title": current_title or playlist_title_from_location(location),
                    "group": current_group,
                    "url": location,
                })

            current_title = ""
            current_group = ""

    return deduplicate_playlist_entries(entries)


def xml_child_text(element, local_name):
    for child in list(element):
        tag = child.tag.rsplit("}", 1)[-1] if isinstance(child.tag, str) else ""
        if tag == local_name:
            return (child.text or "").strip()
    return ""


def parse_xspf_file(path):
    entries = []
    tree = ET.parse(path)

    for track in tree.getroot().iter():
        tag = track.tag.rsplit("}", 1)[-1] if isinstance(track.tag, str) else ""
        if tag != "track":
            continue

        location = resolve_playlist_location(xml_child_text(track, "location"), path)
        if not location:
            continue

        title = xml_child_text(track, "title") or playlist_title_from_location(location)
        group = xml_child_text(track, "album") or xml_child_text(track, "creator")
        entries.append({"title": title, "group": group, "url": location})

    return deduplicate_playlist_entries(entries)


def parse_playlist_file(path):
    extension = os.path.splitext(path)[1].lower()
    if extension in (".m3u", ".m3u8"):
        return parse_m3u_file(path)
    if extension == ".xspf":
        return parse_xspf_file(path)
    return []


def open_folder(path):
    folder = os.path.dirname(path) if os.path.isfile(path) else path

    try:
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", folder])
        elif sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
    except Exception:
        pass


def get_tool_version(path, args):
    if not path:
        return "Non détecté"

    try:
        result = subprocess.run(
            [path] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5
        )
        return result.stdout.splitlines()[0].strip() if result.stdout.splitlines() else "Détecté"
    except Exception:
        return "Détecté"


def extract_version_number(text):
    match = re.search(r"(\d+(?:\.\d+)+)", text or "")
    return match.group(1) if match else ""


def version_tuple(version):
    parts = re.findall(r"\d+", version or "")
    return tuple(int(p) for p in parts[:4]) if parts else tuple()


def is_newer_version(latest, current):
    latest_tuple = version_tuple(latest)
    current_tuple = version_tuple(current)

    if not latest_tuple or not current_tuple:
        return False

    return latest_tuple > current_tuple


def fetch_json(url, timeout=12):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"{APP_NAME} Update Checker"
        }
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_latest_streamlink_version():
    data = fetch_json("https://pypi.org/pypi/streamlink/json")
    return data.get("info", {}).get("version", "")


def get_latest_ytdlp_version():
    data = fetch_json("https://pypi.org/pypi/yt-dlp/json")
    return data.get("info", {}).get("version", "")


def get_latest_gui_version():
    """
    Fonction prête pour plus tard.
    Si tu publies KageStream sur GitHub, remplace l'URL par :
    https://api.github.com/repos/TON_COMPTE/KageStream/releases/latest
    """
    return ""


def get_streamlink_installed_version(streamlink_path):
    if not streamlink_path:
        return ""

    output = get_tool_version(streamlink_path, ["--version"])
    return extract_version_number(output)


def get_ffmpeg_installed_version(ffmpeg_path):
    if not ffmpeg_path:
        return ""

    output = get_tool_version(ffmpeg_path, ["-version"])
    return extract_version_number(output)


def get_ytdlp_installed_version(ytdlp_path):
    if not ytdlp_path:
        return ""

    output = get_tool_version(ytdlp_path, ["--version"])
    return extract_version_number(output)



class KageStream(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_TITLE)

        self.set_default_size(1100, 820)
        if os.path.isfile(ICON_PATH):
            self.set_icon_from_file(ICON_PATH)

        self.process = None
        self.user_stopped = False
        self.remux_dialog = None
        self.recording_start = None
        self.current_ts_file = None
        self.final_file = None
        self.stats_timer_id = None
        self.active_backend = None
        self.youtube_progress = ""
        self.youtube_auto_only_codes = set()
        self.javascript_runtime_name = None
        self.javascript_runtime_path = None
        self.local_playlist_files = []
        self.ytdlp_installing = False
        self.dependency_installing = False

        self.stream_warning_count = 0
        self.stream_health = "Non analysé"
        self.last_health_report = "Aucun enregistrement analysé."

        self.streamlink = None
        self.streamlink_version = ""
        self.streamlink_version_path = None
        self.ffmpeg = None
        self.ffprobe = None
        self.ytdlp = None

        self.build_ui()
        self.check_dependencies(silent=True)
        self.log_startup()
        self.refresh_local_playlist_files(log_result=True)

    def build_ui(self):
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main.set_margin_top(14)
        main.set_margin_bottom(14)
        main.set_margin_start(14)
        main.set_margin_end(14)
        self.add(main)

        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{APP_TITLE}</b>")
        main.pack_start(title, False, False, 0)

        self.status = Gtk.Label(label="Prêt.", xalign=0)
        main.pack_start(self.status, False, False, 0)

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.connect("switch-page", self.on_tab_changed)
        main.pack_start(self.notebook, False, False, 0)

        # Onglet Flux & IPTV : Streamlink, Twitch et sources directes FFmpeg.
        stream_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        stream_page.set_border_width(12)

        stream_intro = Gtk.Label(
            label="Twitch, IPTV, HLS, MPEG-TS et autres sources compatibles Streamlink ou FFmpeg.",
            xalign=0
        )
        stream_intro.set_line_wrap(True)
        stream_page.pack_start(stream_intro, False, False, 0)

        self.url_entry = Gtk.Entry()
        self.url_entry.set_placeholder_text("Colle un lien Twitch, IPTV, HLS ou MPEG-TS...")
        self.url_entry.connect("changed", self.on_stream_url_changed)
        stream_page.pack_start(self.url_entry, False, False, 0)

        stream_grid = Gtk.Grid(column_spacing=14, row_spacing=10)
        stream_page.pack_start(stream_grid, False, False, 0)

        self.quality = Gtk.ComboBoxText()
        self.quality.append_text("best")
        self.quality.set_active(0)

        self.twitch_codec_preference = Gtk.ComboBoxText()
        self.twitch_codec_preference.append("h264", "H.264 uniquement — compatibilité maximale")
        self.twitch_codec_preference.append("av1", "H.264 + AV1 — hautes qualités autorisées")
        self.twitch_codec_preference.append("all", "Tous — H.264, HEVC et AV1")
        self.twitch_codec_preference.set_active_id("h264")
        self.twitch_codec_preference.set_sensitive(False)

        self.stream_profile = Gtk.ComboBoxText()
        self.stream_profile.append("copy", "Original — sans conversion, recommandé")
        self.stream_profile.append("h264_aac", "Convertir après capture — H.264 + AAC")
        self.stream_profile.append("av1_opus", "Convertir après capture — AV1 + Opus (lent)")
        self.stream_profile.set_active_id("copy")
        self.stream_profile.connect("changed", self.on_stream_profile_changed)

        self.output_format = Gtk.ComboBoxText()

        self.filename = Gtk.Entry()
        self.filename.set_placeholder_text("Nom du fichier sans extension — optionnel")

        self.folder = Gtk.FileChooserButton(
            title="Choisir le dossier de sortie",
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        self.folder.set_filename(os.getcwd())

        self.twitch_codec_label = Gtk.Label(label="Codecs vidéo Twitch (Streamlink 8+)", xalign=0)
        stream_grid.attach(Gtk.Label(label="Qualité du flux", xalign=0), 0, 0, 1, 1)
        stream_grid.attach(self.quality, 1, 0, 1, 1)
        stream_grid.attach(self.twitch_codec_label, 0, 1, 1, 1)
        stream_grid.attach(self.twitch_codec_preference, 1, 1, 1, 1)
        stream_grid.attach(Gtk.Label(label="Traitement final", xalign=0), 0, 2, 1, 1)
        stream_grid.attach(self.stream_profile, 1, 2, 1, 1)
        stream_grid.attach(Gtk.Label(label="Conteneur final", xalign=0), 0, 3, 1, 1)
        stream_grid.attach(self.output_format, 1, 3, 1, 1)
        stream_grid.attach(Gtk.Label(label="Nom du fichier", xalign=0), 0, 4, 1, 1)
        stream_grid.attach(self.filename, 1, 4, 1, 1)
        stream_grid.attach(Gtk.Label(label="Dossier", xalign=0), 0, 5, 1, 1)
        stream_grid.attach(self.folder, 1, 5, 1, 1)

        stream_help = Gtk.Label(
            label=(
                "La préférence de codec source ne concerne que Twitch. Pour l’IPTV, KageStream "
                "conserve le codec reçu. Les profils H.264/AAC et AV1/Opus sont convertis après "
                "la capture afin de protéger l’enregistrement en direct."
            ),
            xalign=0
        )
        stream_help.set_line_wrap(True)
        stream_page.pack_start(stream_help, False, False, 0)

        self.notebook.append_page(stream_page, Gtk.Label(label="Flux & IPTV"))

        # Onglet YouTube : interface yt-dlp indépendante des flux classiques.
        youtube_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        youtube_page.set_border_width(12)

        youtube_intro = Gtk.Label(
            label="Vidéos, premières et lives YouTube avec yt-dlp.",
            xalign=0
        )
        youtube_page.pack_start(youtube_intro, False, False, 0)

        self.youtube_url_entry = Gtk.Entry()
        self.youtube_url_entry.set_placeholder_text("Colle un lien YouTube...")
        youtube_page.pack_start(self.youtube_url_entry, False, False, 0)

        youtube_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        youtube_grid.set_margin_top(8)
        youtube_grid.set_margin_bottom(4)
        youtube_grid.set_margin_start(8)
        youtube_grid.set_margin_end(8)
        youtube_page.pack_start(youtube_grid, False, False, 0)

        self.source_mode = Gtk.ComboBoxText()
        self.source_mode.append("youtube_video", "Télécharger une vidéo YouTube")
        self.source_mode.append("youtube_live", "Live YouTube — à partir de maintenant")
        self.source_mode.append("youtube_live_start", "Live YouTube — depuis le début (expérimental)")
        self.source_mode.set_active_id("youtube_video")

        self.youtube_resolution = Gtk.ComboBoxText()
        for value, label in [
            ("best", "Meilleure disponible — sans limite"),
            ("4320", "Jusqu’à 4320p / 8K"),
            ("2160", "Jusqu’à 2160p / 4K"),
            ("1440", "Jusqu’à 1440p"),
            ("1080", "Jusqu’à 1080p"),
            ("720", "Jusqu’à 720p"),
            ("480", "Jusqu’à 480p"),
            ("360", "Jusqu’à 360p"),
        ]:
            self.youtube_resolution.append(value, label)
        self.youtube_resolution.set_active_id("best")

        self.youtube_container = Gtk.ComboBoxText()
        self.youtube_container.append("mkv", "MKV — recommandé")
        self.youtube_container.append("mp4", "MP4")
        self.youtube_container.set_active_id("mkv")

        self.youtube_subtitles = Gtk.ComboBoxText()
        self.youtube_subtitles.append("none", "Aucun sous-titre")
        self.youtube_subtitles.append("all", "Tous les sous-titres — sauf chat")
        self.youtube_subtitles.append("fr", "Français (fr)")
        self.youtube_subtitles.append("en", "Anglais (en)")
        self.youtube_subtitles.set_active_id("none")

        self.youtube_filename = Gtk.Entry()
        self.youtube_filename.set_placeholder_text("Nom du fichier sans extension — titre automatique si vide")

        self.youtube_folder = Gtk.FileChooserButton(
            title="Choisir le dossier YouTube",
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        self.youtube_folder.set_filename(os.getcwd())

        youtube_grid.attach(Gtk.Label(label="Type", xalign=0), 0, 0, 1, 1)
        youtube_grid.attach(self.source_mode, 1, 0, 1, 1)
        youtube_grid.attach(Gtk.Label(label="Résolution maximale", xalign=0), 0, 1, 1, 1)
        youtube_grid.attach(self.youtube_resolution, 1, 1, 1, 1)
        youtube_grid.attach(Gtk.Label(label="Conteneur final", xalign=0), 0, 2, 1, 1)
        youtube_grid.attach(self.youtube_container, 1, 2, 1, 1)
        youtube_grid.attach(Gtk.Label(label="Sous-titres", xalign=0), 0, 3, 1, 1)
        youtube_grid.attach(self.youtube_subtitles, 1, 3, 1, 1)
        youtube_grid.attach(Gtk.Label(label="Nom du fichier", xalign=0), 0, 4, 1, 1)
        youtube_grid.attach(self.youtube_filename, 1, 4, 1, 1)
        youtube_grid.attach(Gtk.Label(label="Dossier", xalign=0), 0, 5, 1, 1)
        youtube_grid.attach(self.youtube_folder, 1, 5, 1, 1)

        youtube_help = Gtk.Label(
            label=(
                "Teste d’abord le lien pour charger les langues disponibles. "
                "« Meilleure disponible » choisit la plus grande vidéo et le meilleur audio."
            ),
            xalign=0
        )
        youtube_help.set_line_wrap(True)
        youtube_grid.attach(youtube_help, 0, 6, 3, 1)

        youtube_checks = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        youtube_grid.attach(youtube_checks, 2, 0, 1, 6)

        self.youtube_auto_subs = Gtk.CheckButton(label="Inclure les sous-titres automatiques")
        self.youtube_embed_subs = Gtk.CheckButton(label="Intégrer les sous-titres à la vidéo")
        self.youtube_embed_metadata = Gtk.CheckButton(label="Intégrer les métadonnées et les tags")
        self.youtube_embed_thumbnail = Gtk.CheckButton(label="Intégrer la miniature")
        self.youtube_write_infojson = Gtk.CheckButton(label="Conserver les tags complets (.info.json)")

        self.youtube_embed_subs.set_active(True)
        self.youtube_embed_metadata.set_active(True)
        self.youtube_embed_thumbnail.set_active(True)
        self.youtube_write_infojson.set_active(True)

        for checkbox in [
            self.youtube_auto_subs,
            self.youtube_embed_subs,
            self.youtube_embed_metadata,
            self.youtube_embed_thumbnail,
            self.youtube_write_infojson,
        ]:
            youtube_checks.pack_start(checkbox, False, False, 0)

        self.notebook.append_page(youtube_page, Gtk.Label(label="YouTube"))

        # Onglet listes locales. Le navigateur détaillé reste dans sa grande fenêtre dédiée.
        playlist_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        playlist_page.set_border_width(18)

        playlist_title = Gtk.Label(xalign=0)
        playlist_title.set_markup("<b>Listes M3U, M3U8 et XSPF</b>")
        playlist_page.pack_start(playlist_title, False, False, 0)

        self.playlist_summary_label = Gtk.Label(
            label="KageStream recherche les listes placées à côté de l’AppImage ou du script.",
            xalign=0
        )
        self.playlist_summary_label.set_line_wrap(True)
        playlist_page.pack_start(self.playlist_summary_label, False, False, 0)

        playlist_path = Gtk.Label(label=external_app_dir(), xalign=0)
        playlist_path.set_selectable(True)
        playlist_path.set_line_wrap(True)
        playlist_page.pack_start(playlist_path, False, False, 0)

        self.playlist_button = Gtk.Button(label="Ouvrir les listes locales")
        self.playlist_button.connect("clicked", self.show_local_playlists)
        playlist_page.pack_start(self.playlist_button, False, False, 0)

        playlist_refresh_button = Gtk.Button(label="Actualiser la détection")
        playlist_refresh_button.connect(
            "clicked", lambda *_args: self.refresh_local_playlist_files(log_result=True)
        )
        playlist_page.pack_start(playlist_refresh_button, False, False, 0)

        self.notebook.append_page(playlist_page, Gtk.Label(label="Listes locales"))

        # Onglet outils : diagnostic et gestionnaire de dépendances.
        tools_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        tools_page.set_border_width(18)

        tools_title = Gtk.Label(xalign=0)
        tools_title.set_markup("<b>Diagnostic et dépendances</b>")
        tools_page.pack_start(tools_title, False, False, 0)

        tools_help = Gtk.Label(
            label=(
                "Contrôle les versions détectées ou installe directement yt-dlp, Deno, "
                "Streamlink, FFmpeg et FFprobe sans pacman."
            ),
            xalign=0
        )
        tools_help.set_line_wrap(True)
        tools_page.pack_start(tools_help, False, False, 0)

        self.diagnostic_button = Gtk.Button(label="Ouvrir le diagnostic")
        self.diagnostic_button.connect("clicked", self.show_diagnostic)
        tools_page.pack_start(self.diagnostic_button, False, False, 0)

        self.update_button = Gtk.Button(label="Dépendances et mises à jour")
        self.update_button.connect("clicked", self.show_update_checker)
        tools_page.pack_start(self.update_button, False, False, 0)

        self.notebook.append_page(tools_page, Gtk.Label(label="Outils"))

        self.on_stream_profile_changed(self.stream_profile)

        buttons = Gtk.Box(spacing=8)
        main.pack_start(buttons, False, False, 0)

        self.test_button = Gtk.Button(label="Tester le flux")
        self.test_button.connect("clicked", self.test_link)
        buttons.pack_start(self.test_button, True, True, 0)

        self.start_button = Gtk.Button(label="▶ Enregistrer le flux")
        self.start_button.connect("clicked", self.start_recording)
        buttons.pack_start(self.start_button, True, True, 0)

        self.stop_button = Gtk.Button(label="■ Stop")
        self.stop_button.connect("clicked", self.stop_recording)
        self.stop_button.set_sensitive(False)
        buttons.pack_start(self.stop_button, True, True, 0)

        self.open_folder_button = Gtk.Button(label="Ouvrir le dossier")
        self.open_folder_button.connect("clicked", self.open_current_folder)
        self.open_folder_button.set_sensitive(False)
        buttons.pack_start(self.open_folder_button, True, True, 0)

        self.stats = Gtk.Label(label="Durée : 00:00:00 — Taille : 0 Mo", xalign=0)
        main.pack_start(self.stats, False, False, 0)

        self.health_label = Gtk.Label(label="Santé du stream : non analysé", xalign=0)
        main.pack_start(self.health_label, False, False, 0)

        self.log = Gtk.TextView()
        self.log.set_editable(False)
        self.log.set_monospace(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(105)
        scroll.add(self.log)

        log_expander = Gtk.Expander(label="Journal technique")
        log_expander.set_expanded(True)
        log_expander.add(scroll)
        main.pack_start(log_expander, True, True, 0)

    def active_context(self):
        page = self.notebook.get_current_page()
        if page == 1:
            return "youtube"
        if page == 2:
            return "playlists"
        if page == 3:
            return "tools"
        return "stream"

    def current_url_entry(self):
        return self.youtube_url_entry if self.active_context() == "youtube" else self.url_entry

    def current_source_mode(self):
        if self.active_context() == "youtube":
            return self.source_mode.get_active_id() or "youtube_video"
        return "classic"

    def current_folder(self):
        chooser = self.youtube_folder if self.active_context() == "youtube" else self.folder
        return chooser.get_filename() or os.getcwd()

    def current_filename_entry(self):
        return self.youtube_filename if self.active_context() == "youtube" else self.filename

    def current_output_format(self):
        if self.active_context() == "youtube":
            return self.youtube_container.get_active_id() or "mkv"
        return self.output_format.get_active_id() or "ts"

    def on_tab_changed(self, notebook, page, page_num):
        if not hasattr(self, "test_button"):
            return

        if page_num == 0:
            self.test_button.set_label("Tester le flux")
            self.start_button.set_label("▶ Enregistrer le flux")
        elif page_num == 1:
            self.test_button.set_label("Analyser YouTube")
            self.start_button.set_label("▶ Télécharger / enregistrer")
        else:
            self.test_button.set_label("Test indisponible ici")
            self.start_button.set_label("Enregistrement indisponible ici")

        self.refresh_action_buttons()

    def refresh_action_buttons(self):
        if not hasattr(self, "test_button"):
            return False

        if self.process:
            self.test_button.set_sensitive(False)
            self.start_button.set_sensitive(False)
            self.stop_button.set_sensitive(True)
            return False

        context = self.active_context()
        if context == "stream":
            available = bool(self.streamlink or self.ffmpeg)
            self.test_button.set_sensitive(available)
            self.start_button.set_sensitive(available)
        elif context == "youtube":
            self.test_button.set_sensitive(bool(self.ytdlp))
            self.start_button.set_sensitive(
                bool(self.ytdlp and self.ffmpeg and self.javascript_runtime_path)
            )
        else:
            self.test_button.set_sensitive(False)
            self.start_button.set_sensitive(False)

        self.stop_button.set_sensitive(False)
        return False

    def set_recording_controls(self, recording):
        self.test_button.set_sensitive(not recording)
        self.start_button.set_sensitive(not recording)
        self.stop_button.set_sensitive(recording)
        if not recording:
            self.refresh_action_buttons()

    def is_twitch_url(self, url):
        try:
            host = (urlparse(url).hostname or "").lower()
            return host == "twitch.tv" or host.endswith(".twitch.tv")
        except Exception:
            return False

    def on_stream_url_changed(self, entry):
        version_supported = (
            not self.streamlink_version
            or version_tuple(self.streamlink_version) >= (8, 0)
        )
        enabled = self.is_twitch_url(entry.get_text().strip()) and version_supported
        self.twitch_codec_preference.set_sensitive(enabled)
        self.twitch_codec_label.set_sensitive(enabled)

    def streamlink_codec_args(self, url, preference=None):
        if not self.is_twitch_url(url):
            return []
        if self.streamlink_version and version_tuple(self.streamlink_version) < (8, 0):
            return []

        preference = preference or self.twitch_codec_preference.get_active_id() or "h264"
        codecs = {
            "h264": "h264",
            "av1": "h264,av1",
            "all": "h264,h265,av1",
        }.get(preference, "h264")
        return ["--twitch-supported-codecs", codecs]

    def on_stream_profile_changed(self, combo):
        profile = combo.get_active_id() or "copy"
        previous = self.output_format.get_active_id()
        choices = {
            "copy": [
                ("ts", "TS — capture native"),
                ("mkv", "MKV — remux sans perte"),
                ("mp4", "MP4 — remux sans perte"),
            ],
            "h264_aac": [
                ("mp4", "MP4 — recommandé"),
                ("mkv", "MKV"),
            ],
            "av1_opus": [
                ("mkv", "MKV — recommandé"),
                ("webm", "WebM"),
            ],
        }.get(profile, [])

        self.output_format.remove_all()
        for identifier, label in choices:
            self.output_format.append(identifier, label)

        available = {identifier for identifier, _label in choices}
        default = {"copy": "ts", "h264_aac": "mp4", "av1_opus": "mkv"}.get(
            profile, "ts"
        )
        self.output_format.set_active_id(previous if previous in available else default)

    def log_startup(self):
        self.log_text("========================================")
        self.log_text(APP_TITLE)
        self.log_text("Streamlink, flux directs FFmpeg et téléchargements YouTube yt-dlp")
        self.log_text("========================================")

    def log_text(self, text):
        def append():
            buffer = self.log.get_buffer()
            end = buffer.get_end_iter()
            buffer.insert(end, text + "\n")
            return False
        GLib.idle_add(append)

    def set_status(self, text):
        GLib.idle_add(self.status.set_text, text)

    def check_dependencies(self, silent=False):
        self.streamlink = find_tool("streamlink")
        if self.streamlink != self.streamlink_version_path:
            self.streamlink_version = get_streamlink_installed_version(self.streamlink)
            self.streamlink_version_path = self.streamlink
        self.ffmpeg = find_tool("ffmpeg")
        self.ffprobe = find_tool("ffprobe")
        self.ytdlp = find_tool("yt-dlp")
        self.javascript_runtime_name, self.javascript_runtime_path = find_javascript_runtime()
        self.on_stream_url_changed(self.url_entry)

        if not self.streamlink and not self.ffmpeg:
            self.set_status("Configuration incomplète : Streamlink et FFmpeg introuvables")
        else:
            if self.streamlink and self.ffmpeg:
                if self.ytdlp and self.javascript_runtime_path:
                    self.set_status("Prêt.")
                elif self.ytdlp:
                    self.set_status("Prêt — Deno/Node manquant pour YouTube HD.")
                else:
                    self.set_status("Prêt — yt-dlp manquant pour YouTube.")
            elif self.ffmpeg:
                if self.ytdlp and self.javascript_runtime_path:
                    self.set_status("Prêt — YouTube et flux directs, Streamlink absent.")
                else:
                    self.set_status("Prêt — flux directs uniquement.")
            else:
                self.set_status("Prêt — sources Streamlink uniquement.")

        self.refresh_action_buttons()

        if not silent:
            self.write_diagnostic_log()

    def streamlink_can_handle_url(self, url):
        if not self.streamlink:
            return False

        try:
            result = subprocess.run(
                [self.streamlink, "--can-handle-url", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15
            )
            return result.returncode == 0
        except Exception:
            return False

    def probe_direct_source(self, url):
        """Vérifie qu'une URL est un média directement lisible par FFmpeg."""
        if not self.ffmpeg:
            return False, "FFmpeg est nécessaire pour enregistrer un flux direct"

        if self.ffprobe:
            cmd = [
                self.ffprobe,
                "-v", "error",
                "-rw_timeout", "15000000",
                "-analyzeduration", "5000000",
                "-probesize", "5000000",
                "-show_entries",
                "format=format_name,format_long_name:"
                "stream=codec_type,codec_name,width,height,channels,sample_rate",
                "-of", "json",
                url
            ]

            self.log_text("Commande FFprobe :")
            self.log_text(" ".join(cmd))

            try:
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=35
                )

                if result.returncode == 0:
                    data = json.loads(result.stdout or "{}")
                    streams = data.get("streams", [])
                    media_streams = [
                        stream for stream in streams
                        if stream.get("codec_type") in ("video", "audio")
                    ]

                    if media_streams:
                        format_name = data.get("format", {}).get("format_name", "flux direct")
                        details = [format_name]

                        video = next(
                            (stream for stream in media_streams if stream.get("codec_type") == "video"),
                            None
                        )
                        audio = next(
                            (stream for stream in media_streams if stream.get("codec_type") == "audio"),
                            None
                        )

                        if video:
                            width = video.get("width")
                            height = video.get("height")
                            resolution = f"{width}x{height}" if width and height else "vidéo"
                            details.append(f"{resolution} {video.get('codec_name', '')}".strip())

                        if audio:
                            details.append(f"audio {audio.get('codec_name', 'détecté')}")

                        return True, " — ".join(details)

                error = (result.stderr or result.stdout or "").strip()
                if error:
                    self.log_text(error)

            except Exception as e:
                self.log_text(f"FFprobe n’a pas pu analyser le lien : {e}")

        # Repli lorsque FFprobe n'est pas disponible ou n'arrive pas à conclure.
        cmd = [
            self.ffmpeg,
            "-v", "error",
            "-nostdin",
            "-rw_timeout", "15000000",
            "-i", url,
            "-t", "0.2",
            "-map", "0:v?",
            "-map", "0:a?",
            "-c", "copy",
            "-f", "null",
            "-"
        ]

        self.log_text("Test direct avec FFmpeg :")
        self.log_text(" ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=35
            )

            if result.returncode == 0:
                return True, "média direct reconnu par FFmpeg"

            error = (result.stderr or result.stdout or "").strip()
            if error:
                self.log_text(error)

        except Exception as e:
            self.log_text(f"FFmpeg n’a pas pu analyser le lien : {e}")

        return False, "aucun flux audio ou vidéo direct détecté"

    def direct_source_filename(self, url):
        try:
            path = unquote(urlparse(url).path).rstrip("/")
            return sanitize_filename(os.path.basename(path))
        except Exception:
            return ""

    def set_direct_quality(self):
        self.quality.remove_all()
        self.quality.append_text("source")
        self.quality.set_active(0)
        return False

    def refresh_local_playlist_files(self, log_result=False):
        folder = external_app_dir()
        extensions = {".m3u", ".m3u8", ".xspf"}

        try:
            files = sorted(
                entry.path
                for entry in os.scandir(folder)
                if entry.is_file()
                and os.path.splitext(entry.name)[1].lower() in extensions
            )
        except OSError as e:
            files = []
            if log_result:
                self.log_text(f"Impossible d’analyser le dossier des listes : {e}")

        self.local_playlist_files = files
        label = f"Listes locales ({len(files)})" if files else "Listes locales"
        self.playlist_button.set_label(label)
        if files:
            self.playlist_summary_label.set_text(
                f"{len(files)} liste(s) détectée(s) à côté de l’AppImage ou du script."
            )
        else:
            self.playlist_summary_label.set_text(
                "Aucune liste .m3u, .m3u8 ou .xspf détectée à côté de l’AppImage ou du script."
            )

        if log_result:
            self.log_text(f"Dossier des listes locales : {folder}")
            self.log_text(f"Listes M3U/XSPF détectées : {len(files)}")

        return files

    def load_local_playlists(self, files):
        playlist_data = {}

        for path in files:
            try:
                entries = parse_playlist_file(path)
                playlist_data[path] = entries
                self.log_text(
                    f"Liste chargée : {os.path.basename(path)} — {len(entries)} lien(s)"
                )
            except Exception as e:
                playlist_data[path] = []
                self.log_text(f"Erreur dans {os.path.basename(path)} : {e}")

        return playlist_data

    def show_local_playlists(self, button):
        files = self.refresh_local_playlist_files(log_result=True)
        folder = external_app_dir()

        if not files:
            self.show_message(
                "Aucune liste locale",
                (
                    "Aucun fichier .m3u, .m3u8 ou .xspf n’a été trouvé à côté de l’AppImage."
                    f"\n\nDossier analysé :\n{folder}"
                ),
                Gtk.MessageType.INFO
            )
            return

        playlist_data = self.load_local_playlists(files)
        total_entries = sum(len(entries) for entries in playlist_data.values())

        if not total_entries:
            self.show_message(
                "Listes vides ou illisibles",
                (
                    f"{len(files)} liste(s) détectée(s), mais aucun lien n’a pu être lu."
                    " Consulte les logs de KageStream."
                ),
                Gtk.MessageType.WARNING
            )
            return

        dialog = Gtk.Dialog(
            title="Listes M3U / XSPF",
            transient_for=self,
            flags=0
        )
        dialog.add_button("Fermer", Gtk.ResponseType.CANCEL)
        dialog.add_button("Enregistrer la sélection", Gtk.ResponseType.OK)
        dialog.set_default_size(1000, 620)
        dialog.set_response_sensitive(Gtk.ResponseType.OK, False)

        content = dialog.get_content_area()
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(14)
        content.set_margin_end(14)
        content.set_spacing(10)

        folder_label = Gtk.Label(xalign=0)
        folder_label.set_markup("<b>Listes détectées à côté de l’AppImage</b>")
        content.pack_start(folder_label, False, False, 0)

        path_label = Gtk.Label(label=folder, xalign=0)
        path_label.set_selectable(True)
        path_label.set_ellipsize(3)
        content.pack_start(path_label, False, False, 0)

        controls = Gtk.Grid(column_spacing=10, row_spacing=8)
        content.pack_start(controls, False, False, 0)

        playlist_selector = Gtk.ComboBoxText()
        playlist_selector.append("__all__", f"Toutes les listes — {total_entries} liens")
        for path in files:
            count = len(playlist_data.get(path, []))
            playlist_selector.append(path, f"{os.path.basename(path)} — {count} liens")
        playlist_selector.set_active_id("__all__")

        search_entry = Gtk.SearchEntry()
        search_entry.set_placeholder_text("Rechercher une chaîne, un groupe ou une URL...")

        format_selector = Gtk.ComboBoxText()
        format_selector.append("ts", "TS")
        format_selector.append("mkv", "MKV")
        format_selector.append("mp4", "MP4")
        current_format = self.output_format.get_active_id() or "ts"
        format_selector.set_active_id(current_format)

        refresh_button = Gtk.Button(label="Actualiser")

        controls.attach(Gtk.Label(label="Liste", xalign=0), 0, 0, 1, 1)
        controls.attach(playlist_selector, 1, 0, 1, 1)
        controls.attach(Gtk.Label(label="Format", xalign=0), 2, 0, 1, 1)
        controls.attach(format_selector, 3, 0, 1, 1)
        controls.attach(refresh_button, 4, 0, 1, 1)
        controls.attach(search_entry, 0, 1, 5, 1)

        count_label = Gtk.Label(xalign=0)
        content.pack_start(count_label, False, False, 0)

        model = Gtk.ListStore(str, str, str, str)
        tree = Gtk.TreeView(model=model)
        tree.set_headers_visible(True)
        tree.set_enable_search(True)
        tree.set_search_column(0)

        for title, column_index, expand in [
            ("Nom", 0, True),
            ("Groupe", 1, False),
            ("Liste", 2, False),
            ("URL / source", 3, True),
        ]:
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", 3)
            column = Gtk.TreeViewColumn(title, renderer, text=column_index)
            column.set_resizable(True)
            column.set_expand(expand)
            tree.append_column(column)

        scroll = Gtk.ScrolledWindow()
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        scroll.add(tree)
        content.pack_start(scroll, True, True, 0)

        selection = tree.get_selection()

        def populate_model(*_args):
            model.clear()
            selected_playlist = playlist_selector.get_active_id() or "__all__"
            query = search_entry.get_text().strip().lower()
            displayed = 0

            selected_paths = files if selected_playlist == "__all__" else [selected_playlist]

            for path in selected_paths:
                source_name = os.path.basename(path)
                for entry in playlist_data.get(path, []):
                    title = entry.get("title") or playlist_title_from_location(entry.get("url", ""))
                    group = entry.get("group", "")
                    url = entry.get("url", "")
                    searchable = f"{title} {group} {source_name} {url}".lower()

                    if query and query not in searchable:
                        continue

                    model.append([title, group, source_name, url])
                    displayed += 1

            count_label.set_text(f"{displayed} lien(s) affiché(s)")
            dialog.set_response_sensitive(Gtk.ResponseType.OK, False)

        def selection_changed(*_args):
            _model, tree_iter = selection.get_selected()
            dialog.set_response_sensitive(
                Gtk.ResponseType.OK,
                tree_iter is not None and not bool(self.process)
            )

        def refresh_dialog(*_args):
            nonlocal files, playlist_data
            files = self.refresh_local_playlist_files(log_result=True)
            playlist_data = self.load_local_playlists(files)

            playlist_selector.remove_all()
            refreshed_total = sum(len(entries) for entries in playlist_data.values())
            playlist_selector.append("__all__", f"Toutes les listes — {refreshed_total} liens")
            for path in files:
                count = len(playlist_data.get(path, []))
                playlist_selector.append(path, f"{os.path.basename(path)} — {count} liens")
            playlist_selector.set_active_id("__all__")
            populate_model()

        playlist_selector.connect("changed", populate_model)
        search_entry.connect("search-changed", populate_model)
        selection.connect("changed", selection_changed)
        refresh_button.connect("clicked", refresh_dialog)
        tree.connect("row-activated", lambda *_args: dialog.response(Gtk.ResponseType.OK))

        populate_model()
        content.show_all()
        response = dialog.run()

        selected_item = None
        selected_format = format_selector.get_active_id() or "ts"

        if response == Gtk.ResponseType.OK:
            selected_model, tree_iter = selection.get_selected()
            if tree_iter is not None:
                selected_item = {
                    "title": selected_model[tree_iter][0],
                    "url": selected_model[tree_iter][3],
                }

        dialog.destroy()

        if not selected_item:
            return

        if self.process:
            self.show_message(
                "Enregistrement déjà en cours",
                "Arrête l’enregistrement actuel avant d’en lancer un autre.",
                Gtk.MessageType.WARNING
            )
            return

        self.notebook.set_current_page(0)
        self.url_entry.set_text(selected_item["url"])
        self.filename.set_text(sanitize_filename(selected_item["title"]))
        self.stream_profile.set_active_id("copy")
        self.output_format.set_active_id(selected_format)
        self.start_recording(None)

    def is_youtube_url(self, url):
        try:
            host = (urlparse(url).hostname or "").lower()
            return (
                host == "youtu.be"
                or host.endswith(".youtu.be")
                or host == "youtube.com"
                or host.endswith(".youtube.com")
                or host == "youtube-nocookie.com"
                or host.endswith(".youtube-nocookie.com")
            )
        except Exception:
            return False

    def should_use_ytdlp(self, url, source_mode):
        if source_mode == "classic":
            return False
        if source_mode in ("youtube_video", "youtube_live", "youtube_live_start"):
            return True
        return self.is_youtube_url(url)

    def analyze_youtube(self, url):
        if not self.ytdlp:
            return None, "yt-dlp est introuvable"

        cmd = [
            self.ytdlp,
            "--ignore-config",
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            "--no-warnings",
        ]

        if self.javascript_runtime_name and self.javascript_runtime_path:
            cmd.extend([
                "--js-runtimes",
                f"{self.javascript_runtime_name}:{self.javascript_runtime_path}"
            ])

        cmd.extend(["--", url])

        self.log_text("Commande d’analyse yt-dlp :")
        self.log_text(" ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=90
            )

            if result.returncode != 0:
                error = (result.stderr or result.stdout or "Erreur yt-dlp").strip()
                return None, error

            return json.loads(result.stdout), ""

        except subprocess.TimeoutExpired:
            return None, "L’analyse YouTube a dépassé 90 secondes."
        except Exception as e:
            return None, str(e)

    def subtitle_display_name(self, code, tracks):
        for track in tracks or []:
            name = track.get("name")
            if name:
                return name
        return code

    def update_youtube_analysis(self, data):
        current_subtitle = self.youtube_subtitles.get_active_id() or "none"
        manual = data.get("subtitles") or {}
        automatic = data.get("automatic_captions") or {}

        self.youtube_auto_only_codes = set(automatic) - set(manual)
        self.youtube_subtitles.remove_all()
        self.youtube_subtitles.append("none", "Aucun sous-titre")
        self.youtube_subtitles.append("all", "Tous les sous-titres — sauf chat")

        codes = sorted(
            (set(manual) | set(automatic)) - {"live_chat"},
            key=lambda code: (
                0 if code == "fr" or code.startswith("fr-") else
                1 if code == "en" or code.startswith("en-") else
                2,
                code.lower()
            )
        )

        for code in codes:
            if code in manual:
                name = self.subtitle_display_name(code, manual.get(code))
                kind = "manuel"
            else:
                name = self.subtitle_display_name(code, automatic.get(code))
                kind = "automatique"

            label = f"{name} ({code}) — {kind}"
            self.youtube_subtitles.append(code, label)

        available_ids = {"none", "all"} | set(codes)
        self.youtube_subtitles.set_active_id(
            current_subtitle if current_subtitle in available_ids else "none"
        )
        return False

    def test_youtube_link(self, url):
        if not self.ytdlp:
            self.set_status("yt-dlp est introuvable.")
            GLib.idle_add(
                self.show_message,
                "yt-dlp introuvable",
                "Ouvre « Outils → Dépendances et mises à jour », puis installe yt-dlp directement. "
                "Aucun paquet Arch n’est nécessaire.",
                Gtk.MessageType.ERROR
            )
            return

        data, error = self.analyze_youtube(url)

        if not data:
            self.log_text(error)
            self.set_status("Lien YouTube non reconnu.")
            GLib.idle_add(
                self.show_message,
                "Lien YouTube non reconnu",
                error or "yt-dlp n’a pas réussi à analyser ce lien.",
                Gtk.MessageType.ERROR
            )
            return

        GLib.idle_add(self.update_youtube_analysis, data)

        title = sanitize_filename(data.get("title") or "")
        if title:
            GLib.idle_add(self.set_auto_filename, title, "youtube")

        formats = data.get("formats") or []
        heights = sorted({
            int(item["height"])
            for item in formats
            if isinstance(item.get("height"), (int, float))
        }, reverse=True)
        max_height = heights[0] if heights else None

        manual_count = len(data.get("subtitles") or {})
        automatic_count = len(data.get("automatic_captions") or {})
        tags = data.get("tags") or []
        live_status = data.get("live_status") or ("is_live" if data.get("is_live") else "not_live")
        uploader = data.get("uploader") or data.get("channel") or "Inconnu"

        self.log_text(f"Titre : {data.get('title', 'Inconnu')}")
        self.log_text(f"Chaîne : {uploader}")
        self.log_text(f"État : {live_status}")
        self.log_text(f"Résolution maximale détectée : {max_height or 'inconnue'}p")
        self.log_text(f"Sous-titres : {manual_count} manuel(s), {automatic_count} automatique(s)")
        self.log_text(f"Tags YouTube : {', '.join(str(tag) for tag in tags) if tags else 'aucun'}")

        if not self.javascript_runtime_path:
            self.log_text(
                "⚠️ Aucun moteur JavaScript détecté : certaines qualités YouTube peuvent manquer."
            )

        kind = "Live YouTube" if live_status in ("is_live", "is_upcoming") else "Vidéo YouTube"
        summary = (
            f"{kind} reconnu.\n\n"
            f"Titre : {data.get('title', 'Inconnu')}\n"
            f"Chaîne : {uploader}\n"
            f"Meilleure résolution : {str(max_height) + 'p' if max_height else 'inconnue'}\n"
            f"Sous-titres manuels : {manual_count}\n"
            f"Sous-titres automatiques : {automatic_count}\n"
            f"Tags : {len(tags)}"
        )

        if not self.javascript_runtime_path:
            summary += (
                "\n\nAttention : Deno ou Node n’est pas détecté. "
                "KageStream bloquera le téléchargement pour éviter une qualité limitée."
            )

        self.set_status(f"{kind} reconnu.")
        GLib.idle_add(
            self.show_message,
            f"{kind} reconnu",
            summary,
            Gtk.MessageType.INFO
        )

    def test_link(self, button):
        context = self.active_context()
        if context not in ("stream", "youtube"):
            return

        url = self.current_url_entry().get_text().strip()

        if not url:
            self.show_message("Lien manquant", "Colle un lien avant de le tester.", Gtk.MessageType.WARNING)
            return

        self.test_button.set_sensitive(False)
        self.set_status("Test du lien en cours...")
        source_mode = self.current_source_mode()
        twitch_preference = self.twitch_codec_preference.get_active_id() or "h264"

        threading.Thread(
            target=self.test_link_worker,
            args=(url, source_mode, context, twitch_preference),
            daemon=True
        ).start()

    def test_link_worker(self, url, source_mode="classic", context="stream",
                         twitch_preference="h264"):
        self.log_text("")
        self.log_text("Test du lien :")

        try:
            if self.should_use_ytdlp(url, source_mode):
                self.test_youtube_link(url)
                return

            if self.streamlink_can_handle_url(url):
                cmd = [self.streamlink]
                cmd.extend(self.streamlink_codec_args(url, twitch_preference))
                cmd.extend(["--json", url])
                self.log_text("Commande Streamlink :")
                self.log_text(" ".join(cmd))

                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=30
                )

                output = result.stdout
                self.log_text(output.strip())

                qualities = sorted(set(re.findall(r'"([^"]+)":\s*\{', output)))
                ignored = {"streams", "metadata"}
                qualities = [q for q in qualities if q not in ignored]

                if not qualities:
                    qualities = re.findall(r"Available streams:\s*(.*)", output)
                    if qualities:
                        qualities = [x.strip().split(" ")[0] for x in qualities[0].split(",")]

                if qualities:
                    GLib.idle_add(self.update_quality_list, qualities)

                title = self.extract_title(output)
                if title:
                    GLib.idle_add(self.set_auto_filename, title, context)

                if result.returncode == 0:
                    self.set_status("Lien Streamlink valide.")
                    GLib.idle_add(
                        self.show_message,
                        "Lien valide",
                        "Les qualités disponibles ont été chargées.",
                        Gtk.MessageType.INFO
                    )
                else:
                    self.set_status("Lien non reconnu.")
                    GLib.idle_add(
                        self.show_message,
                        "Lien non reconnu",
                        "Streamlink n’a pas réussi à lire ce lien.",
                        Gtk.MessageType.WARNING
                    )

                return

            self.log_text("Streamlink ne gère pas ce lien. Recherche d’un flux direct...")
            valid, details = self.probe_direct_source(url)

            if valid:
                GLib.idle_add(self.set_direct_quality)

                title = self.direct_source_filename(url)
                if title:
                    GLib.idle_add(self.set_auto_filename, title, context)

                self.log_text(f"Flux direct détecté : {details}")
                self.set_status("Flux direct valide.")
                GLib.idle_add(
                    self.show_message,
                    "Flux direct valide",
                    f"Le lien sera enregistré directement avec FFmpeg.\n\n{details}",
                    Gtk.MessageType.INFO
                )
            else:
                self.set_status("Lien non reconnu.")
                GLib.idle_add(
                    self.show_message,
                    "Lien non reconnu",
                    "Le lien n’est reconnu ni par Streamlink ni comme flux direct FFmpeg.",
                    Gtk.MessageType.WARNING
                )

        except Exception as e:
            self.log_text(f"Erreur test : {e}")
            self.set_status("Erreur pendant le test.")

        finally:
            GLib.idle_add(self.refresh_action_buttons)

    def extract_title(self, output):
        match = re.search(r'"title":\s*"([^"]+)"', output)
        if match:
            return sanitize_filename(match.group(1))

        match = re.search(r'"author":\s*"([^"]+)"', output)
        if match:
            return sanitize_filename(match.group(1))

        return ""

    def update_quality_list(self, qualities):
        self.quality.remove_all()

        preferred = ["best"] + [q for q in qualities if q != "best"]

        for q in preferred:
            self.quality.append_text(q)

        self.quality.set_active(0)
        return False

    def set_auto_filename(self, title, context="stream"):
        entry = self.youtube_filename if context == "youtube" else self.filename
        if not entry.get_text().strip():
            entry.set_text(title)
        return False

    def safe_filename(self, context="stream"):
        entry = self.youtube_filename if context == "youtube" else self.filename
        name = sanitize_filename(entry.get_text().strip())
        if not name:
            name = "record_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return name

    def get_youtube_config(self, source_mode):
        return {
            "source_mode": source_mode,
            "resolution": self.youtube_resolution.get_active_id() or "best",
            "container": self.youtube_container.get_active_id() or "mkv",
            "subtitles": self.youtube_subtitles.get_active_id() or "none",
            "auto_subs": self.youtube_auto_subs.get_active(),
            "embed_subs": self.youtube_embed_subs.get_active(),
            "embed_metadata": self.youtube_embed_metadata.get_active(),
            "embed_thumbnail": self.youtube_embed_thumbnail.get_active(),
            "write_infojson": self.youtube_write_infojson.get_active(),
            "filename": sanitize_filename(self.youtube_filename.get_text().strip()),
        }

    def youtube_output_template(self, folder, filename):
        if filename:
            # Dans un modèle yt-dlp, un pourcentage littéral doit être doublé.
            safe_name = filename.replace("%", "%%")
            return os.path.join(folder, safe_name + ".%(ext)s")

        return os.path.join(folder, "%(title).120s [%(id)s].%(ext)s")

    def build_ytdlp_command(self, url, folder, config):
        resolution = config["resolution"]
        container = config["container"]

        if resolution == "best":
            format_selector = "bestvideo*+bestaudio/best"
        else:
            format_selector = (
                f"bestvideo*[height<={resolution}]+bestaudio/"
                f"best[height<={resolution}]/best"
            )

        cmd = [
            self.ytdlp,
            "--ignore-config",
            "--newline",
            "--progress",
            "--no-playlist",
            "--no-overwrites",
            "--continue",
            "--concurrent-fragments", "4",
            "--trim-filenames", "180",
            "--format", format_selector,
            "--merge-output-format", container,
            "--remux-video", container,
            "--output", self.youtube_output_template(folder, config["filename"]),
            "--print", "after_move:KAGESTREAM_FINAL:%(filepath)s",
        ]

        if self.javascript_runtime_name and self.javascript_runtime_path:
            cmd.extend([
                "--js-runtimes",
                f"{self.javascript_runtime_name}:{self.javascript_runtime_path}"
            ])

        if self.ffmpeg:
            cmd.extend(["--ffmpeg-location", os.path.dirname(self.ffmpeg)])

        if config["source_mode"] == "youtube_live_start":
            cmd.append("--live-from-start")

        selected_subtitles = config["subtitles"]
        if selected_subtitles != "none":
            cmd.extend(["--write-subs", "--sub-format", "srt/vtt/best"])

            if selected_subtitles == "all":
                cmd.extend(["--sub-langs", "all,-live_chat"])
            else:
                cmd.extend(["--sub-langs", selected_subtitles])

            if (
                config["auto_subs"]
                or selected_subtitles == "all"
                or selected_subtitles in self.youtube_auto_only_codes
            ):
                cmd.append("--write-auto-subs")

            if config["embed_subs"]:
                cmd.append("--embed-subs")

        if config["embed_metadata"]:
            cmd.extend(["--embed-metadata", "--embed-chapters"])

        if config["embed_thumbnail"]:
            cmd.append("--embed-thumbnail")

        if config["write_infojson"]:
            cmd.append("--write-info-json")
            if container == "mkv":
                cmd.append("--embed-info-json")

        cmd.extend(["--", url])
        return cmd

    def inspect_ytdlp_line(self, line):
        marker = "KAGESTREAM_FINAL:"
        if marker in line:
            final_path = line.split(marker, 1)[1].strip()
            if final_path:
                self.final_file = final_path
                self.log_text(f"Fichier final détecté : {final_path}")
            return

        progress = re.search(r"\[download\]\s+([0-9]+(?:\.[0-9]+)?%)\s*(.*)", line)
        if progress:
            percent = progress.group(1)
            rest = progress.group(2).strip()
            self.youtube_progress = f"{percent} {rest}".strip()
            self.set_status(f"YouTube — téléchargement : {percent}")

    def find_recent_youtube_file(self, folder, started_at):
        media_extensions = {".mkv", ".mp4", ".webm", ".mov", ".ts", ".m4v"}
        candidates = []

        try:
            for entry in os.scandir(folder):
                if not entry.is_file():
                    continue

                extension = os.path.splitext(entry.name)[1].lower()
                if extension not in media_extensions:
                    continue

                stat = entry.stat()
                if stat.st_mtime >= started_at - 3:
                    candidates.append((stat.st_mtime, entry.path))
        except OSError:
            return ""

        return max(candidates)[1] if candidates else ""

    def find_recent_partial_file(self, folder, started_at):
        candidates = []

        try:
            for entry in os.scandir(folder):
                if not entry.is_file() or not entry.name.endswith(".part"):
                    continue

                stat = entry.stat()
                if stat.st_mtime >= started_at - 3:
                    candidates.append((stat.st_mtime, entry.path))
        except OSError:
            return ""

        return max(candidates)[1] if candidates else ""

    def youtube_worker(self, url, folder, config):
        started_at = time.time()
        cmd = self.build_ytdlp_command(url, folder, config)

        self.log_text("")
        self.log_text("Commande yt-dlp :")
        self.log_text(" ".join(cmd))
        self.recording_start = started_at
        self.set_status("YouTube — préparation du téléchargement...")

        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creationflags
            )

            for line in self.process.stdout:
                clean = line.rstrip()
                if not clean:
                    continue
                self.log_text(clean)
                self.inspect_ytdlp_line(clean)

            self.process.wait()
            returncode = self.process.returncode

            if not self.final_file or not os.path.isfile(self.final_file):
                detected = self.find_recent_youtube_file(folder, started_at)
                if detected:
                    self.final_file = detected

            has_final_file = bool(self.final_file and os.path.isfile(self.final_file))

            if self.user_stopped:
                if has_final_file:
                    self.log_text(f"Live YouTube arrêté et conservé : {self.final_file}")
                    self.last_health_report = "Live YouTube arrêté proprement et conservé."
                    self.set_health("partiel conservé", "arrêt demandé par l’utilisateur")
                    GLib.idle_add(
                        self.show_message,
                        "Enregistrement YouTube arrêté",
                        f"Le fichier a été finalisé et conservé :\n{self.final_file}",
                        Gtk.MessageType.INFO
                    )
                else:
                    partial = self.find_recent_partial_file(folder, started_at)
                    message = "Le téléchargement a été arrêté avant sa finalisation."
                    if partial:
                        message += f"\n\nFichier partiel conservé :\n{partial}"
                    self.log_text(message)
                    self.last_health_report = message
                    self.set_health("incomplet", "fichier partiel")
                    GLib.idle_add(
                        self.show_message,
                        "Téléchargement interrompu",
                        message,
                        Gtk.MessageType.WARNING
                    )

            elif returncode == 0 and has_final_file:
                self.log_text(f"Téléchargement YouTube terminé : {self.final_file}")
                self.last_health_report = "Téléchargement YouTube terminé."
                self.set_health("OK", "vidéo et métadonnées finalisées")
                GLib.idle_add(
                    self.show_message,
                    "Téléchargement terminé",
                    f"Fichier final :\n{self.final_file}",
                    Gtk.MessageType.INFO
                )

            elif returncode == 0:
                self.log_text("yt-dlp a terminé, mais le fichier final n’a pas pu être localisé.")
                self.set_health("à vérifier", "fichier final non localisé")

            else:
                self.log_text(f"yt-dlp s’est arrêté avec le code {returncode}.")
                self.last_health_report = f"Échec yt-dlp — code {returncode}."
                self.set_health("problème détecté", f"yt-dlp : code {returncode}")
                GLib.idle_add(
                    self.show_message,
                    "Téléchargement YouTube impossible",
                    "yt-dlp a rencontré une erreur. Consulte les logs de KageStream.",
                    Gtk.MessageType.ERROR
                )

        except Exception as e:
            self.log_text(f"Erreur yt-dlp : {e}")
            self.last_health_report = f"Erreur yt-dlp : {e}"
            self.set_health("problème détecté", "erreur yt-dlp")
            GLib.idle_add(
                self.show_message,
                "Erreur YouTube",
                str(e),
                Gtk.MessageType.ERROR
            )

        finally:
            self.process = None
            self.active_backend = None
            GLib.idle_add(self.set_recording_controls, False)
            GLib.idle_add(self.open_folder_button.set_sensitive, True)
            self.set_status("Prêt.")

    def start_recording(self, button):
        context = self.active_context()
        if context not in ("stream", "youtube"):
            return

        url = self.current_url_entry().get_text().strip()

        if not url:
            self.show_message("Lien manquant", "Colle un lien avant de lancer l’enregistrement.", Gtk.MessageType.WARNING)
            return

        self.check_dependencies(silent=True)

        source_mode = self.current_source_mode()
        use_ytdlp = context == "youtube"
        fmt = self.current_output_format()
        profile = self.stream_profile.get_active_id() or "copy"

        if use_ytdlp:
            if not self.ytdlp:
                self.show_message(
                    "yt-dlp introuvable",
                    "Ouvre « Outils → Dépendances et mises à jour », puis installe yt-dlp directement. "
                    "Aucun paquet Arch n’est nécessaire.",
                    Gtk.MessageType.ERROR
                )
                return

            if not self.ffmpeg:
                self.show_message(
                    "FFmpeg introuvable",
                    "FFmpeg est nécessaire pour réunir la vidéo et l’audio YouTube en haute qualité. "
                    "Tu peux l’installer depuis « Outils » sans passer par pacman.",
                    Gtk.MessageType.ERROR
                )
                return

            if not self.javascript_runtime_path:
                self.show_message(
                    "Moteur JavaScript introuvable",
                    "Deno ou Node est nécessaire pour obtenir toutes les qualités YouTube. "
                    "KageStream bloque le téléchargement afin d’éviter une vidéo limitée à 360p. "
                    "Utilise l’onglet « Outils » pour installer Deno directement.",
                    Gtk.MessageType.ERROR
                )
                return

        elif not self.streamlink and not self.ffmpeg:
            self.show_message(
                "Moteur d’enregistrement introuvable",
                "Ouvre l’onglet « Outils » puis installe Streamlink ou FFmpeg directement.",
                Gtk.MessageType.ERROR
            )
            return

        if not use_ytdlp and (fmt != "ts" or profile != "copy") and not self.ffmpeg:
            self.show_message(
                "FFmpeg introuvable",
                "FFmpeg est nécessaire pour le remux ou la conversion. "
                "Tu peux l’installer depuis l’onglet « Outils ».",
                Gtk.MessageType.ERROR
            )
            return

        self.user_stopped = False
        self.recording_start = time.time()
        self.stream_warning_count = 0
        self.youtube_progress = ""
        self.last_health_report = "Enregistrement en cours."
        self.set_health("en cours", "surveillance active")

        folder = self.current_folder()
        self.open_folder_button.set_sensitive(False)

        self.set_recording_controls(True)
        self.set_status("Analyse de la source...")

        if self.stats_timer_id:
            try:
                GLib.source_remove(self.stats_timer_id)
            except Exception:
                pass

        self.stats_timer_id = GLib.timeout_add(1000, self.update_stats)

        if use_ytdlp:
            config = self.get_youtube_config(source_mode)
            self.current_ts_file = None
            self.final_file = folder
            self.active_backend = "yt-dlp"
            self.set_status("YouTube — analyse et préparation...")

            threading.Thread(
                target=self.youtube_worker,
                args=(url, folder, config),
                daemon=True
            ).start()
            return

        quality = self.quality.get_active_text() or "best"
        ts_file = os.path.join(folder, self.safe_filename("stream")) + ".ts"
        twitch_preference = self.twitch_codec_preference.get_active_id() or "h264"

        self.current_ts_file = ts_file
        self.final_file = ts_file
        self.active_backend = "record"

        threading.Thread(
            target=self.record_worker,
            args=(url, quality, fmt, ts_file, profile, twitch_preference),
            daemon=True
        ).start()


    def set_health(self, state, message=None):
        self.stream_health = state
        text = f"Santé du stream : {state}"
        if message:
            text += f" — {message}"
        GLib.idle_add(self.health_label.set_text, text)

    def inspect_streamlink_line(self, line):
        lower = (line or "").lower()
        if any(pattern in lower for pattern in BAD_STREAM_PATTERNS):
            self.stream_warning_count += 1
            self.log_text(f"⚠️ Signal suspect #{self.stream_warning_count} : {line}")

            if self.stream_warning_count >= 5:
                self.set_status("Attention : stream instable détecté.")
                self.set_health("instable", f"{self.stream_warning_count} signaux suspects")
            else:
                self.set_health("à surveiller", f"{self.stream_warning_count} signal suspect")

    def check_recording_health(self, file_path):
        if not self.ffmpeg or not os.path.exists(file_path):
            self.last_health_report = "Analyse impossible : FFmpeg ou fichier introuvable."
            self.log_text(self.last_health_report)
            return False

        self.log_text("")
        self.log_text("===== Analyse santé du fichier =====")
        self.log_text(f"Fichier analysé : {file_path}")

        cmd = [self.ffmpeg, "-v", "warning", "-i", file_path, "-f", "null", "-"]
        self.log_text("Commande analyse :")
        self.log_text(" ".join(cmd))

        issues = []
        serious_issues = []

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            for line in proc.stdout:
                clean = line.rstrip()
                if not clean:
                    continue

                self.log_text(clean)
                issues.append(clean)

                lower = clean.lower()
                if any(pattern in lower for pattern in FFMPEG_HEALTH_PATTERNS):
                    serious_issues.append(clean)

            proc.wait()

            if proc.returncode not in (0, None):
                serious_issues.append(f"FFmpeg a terminé avec le code {proc.returncode}")

            if serious_issues:
                self.last_health_report = (
                    f"Problème probable : {len(serious_issues)} alerte(s) sérieuse(s), "
                    f"{len(issues)} avertissement(s) total."
                )
                self.log_text("⚠️ " + self.last_health_report)
                self.set_status("Attention : fichier possiblement instable.")
                self.set_health("problème détecté", f"{len(serious_issues)} alerte(s)")
                return False

            if issues:
                self.last_health_report = f"À surveiller : {len(issues)} avertissement(s)."
                self.log_text("⚠️ " + self.last_health_report)
                self.set_health("à surveiller", f"{len(issues)} avertissement(s)")
                return True

            self.last_health_report = "OK : aucun problème évident détecté par FFmpeg."
            self.log_text("✅ " + self.last_health_report)
            self.set_health("OK", "aucune alerte")
            return True

        except Exception as e:
            self.last_health_report = f"Analyse impossible : {e}"
            self.log_text(self.last_health_report)
            self.set_health("analyse impossible")
            return False

    def record_worker(self, url, quality, fmt, ts_file, profile="copy",
                      twitch_preference="h264"):
        try:
            self.log_text("")

            if self.streamlink_can_handle_url(url):
                backend = "Streamlink"
                cmd = [self.streamlink]
                cmd.extend(self.streamlink_codec_args(url, twitch_preference))
                cmd.extend([url, quality, "-o", ts_file])
            else:
                self.log_text("Streamlink ne gère pas ce lien. Recherche d’un flux direct...")
                valid, details = self.probe_direct_source(url)

                if not valid:
                    self.log_text(f"Source refusée : {details}")
                    self.set_health("problème détecté", "source non reconnue")
                    GLib.idle_add(
                        self.show_message,
                        "Source non reconnue",
                        "Le lien n’est reconnu ni par Streamlink ni comme flux direct FFmpeg.",
                        Gtk.MessageType.ERROR
                    )
                    return

                backend = "FFmpeg direct"
                self.log_text(f"Flux direct détecté : {details}")

                cmd = [
                    self.ffmpeg,
                    "-y",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel", "warning",
                    "-rw_timeout", "15000000"
                ]

                if url.lower().startswith(("http://", "https://")):
                    cmd.extend([
                        "-reconnect", "1",
                        "-reconnect_streamed", "1",
                        "-reconnect_delay_max", "5"
                    ])

                cmd.extend([
                    "-i", url,
                    "-map", "0",
                    "-c", "copy",
                    "-f", "mpegts",
                    ts_file
                ])

            self.active_backend = backend
            self.log_text(f"Commande {backend} :")
            self.log_text(" ".join(cmd))
            self.recording_start = time.time()
            self.set_status(f"Enregistrement en cours — {backend}...")

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            for line in self.process.stdout:
                clean = line.rstrip()
                self.log_text(clean)
                self.inspect_streamlink_line(clean)

            self.process.wait()
            returncode = self.process.returncode
            has_data = os.path.exists(ts_file) and os.path.getsize(ts_file) > 0

            if self.user_stopped:
                self.log_text("Enregistrement arrêté par l’utilisateur.")
                if has_data:
                    self.log_text(f"Fichier conservé : {ts_file}")
                    self.finalize_capture(ts_file, fmt, profile)
                else:
                    self.log_text("Aucune donnée vidéo n’a été enregistrée.")

            elif returncode == 0:
                self.log_text("Enregistrement terminé.")
                if has_data:
                    self.finalize_capture(ts_file, fmt, profile)
                else:
                    self.log_text("L’enregistrement est vide.")
                    self.set_health("problème détecté", "fichier vide")

            elif has_data:
                self.log_text(
                    f"{backend} s’est arrêté avec le code {returncode}, "
                    "mais la partie déjà enregistrée est conservée."
                )
                self.finalize_capture(ts_file, fmt, profile)
            else:
                self.log_text(f"{backend} s’est arrêté avec une erreur.")
                self.set_health("problème détecté", f"{backend} a quitté avec une erreur")

        except Exception as e:
            if self.user_stopped:
                self.log_text("Enregistrement arrêté par l’utilisateur.")
                if os.path.exists(ts_file) and os.path.getsize(ts_file) > 0:
                    self.finalize_capture(ts_file, fmt, profile)
            else:
                self.log_text(f"Erreur : {e}")

        finally:
            self.process = None
            self.active_backend = None
            GLib.idle_add(self.set_recording_controls, False)
            GLib.idle_add(self.open_folder_button.set_sensitive, True)
            self.set_status("Prêt.")

    def finalize_capture(self, ts_file, fmt, profile="copy"):
        self.check_recording_health(ts_file)

        if profile != "copy":
            self.transcode_capture(ts_file, fmt, profile)
        elif fmt == "ts":
            self.final_file = ts_file
            self.log_text(f"Fichier final : {ts_file}")
        else:
            self.remux(ts_file, fmt)

    def ffmpeg_encoder_available(self, encoder):
        if not self.ffmpeg:
            return False
        try:
            result = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-encoders"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=20
            )
            return bool(re.search(rf"\b{re.escape(encoder)}\b", result.stdout or ""))
        except Exception:
            return False

    def transcode_capture(self, ts_file, fmt, profile):
        if not self.ffmpeg or not os.path.exists(ts_file):
            self.log_text("Conversion impossible : FFmpeg ou fichier TS introuvable.")
            return

        profiles = {
            "h264_aac": {
                "label": "H.264 + AAC",
                "encoders": ("libx264", "aac"),
                "args": [
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                ],
            },
            "av1_opus": {
                "label": "AV1 + Opus",
                "encoders": ("libsvtav1", "libopus"),
                "args": [
                    "-c:v", "libsvtav1", "-preset", "10", "-crf", "32",
                    "-pix_fmt", "yuv420p", "-c:a", "libopus", "-b:a", "160k",
                ],
            },
        }
        settings = profiles.get(profile)
        if not settings:
            self.log_text(f"Profil de conversion inconnu : {profile}")
            return

        missing = [
            encoder for encoder in settings["encoders"]
            if not self.ffmpeg_encoder_available(encoder)
        ]
        if missing:
            message = (
                "Ce build de FFmpeg ne contient pas les encodeurs nécessaires : "
                + ", ".join(missing)
                + f".\n\nLe fichier TS original est conservé :\n{ts_file}"
            )
            self.log_text(message)
            GLib.idle_add(
                self.show_message,
                "Conversion indisponible",
                message,
                Gtk.MessageType.ERROR
            )
            return

        output = os.path.splitext(ts_file)[0] + "." + fmt
        cmd = [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-i", ts_file,
            "-map", "0:v:0",
            "-map", "0:a?",
            "-map_metadata", "0",
        ]
        cmd.extend(settings["args"])
        if fmt == "mp4":
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(output)

        GLib.idle_add(
            self.show_remux_dialog,
            "Conversion en cours…",
            f"Profil {settings['label']}. Le TS original sera conservé."
        )
        self.log_text("")
        self.log_text(f"Conversion {settings['label']} après capture :")
        self.log_text(" ".join(cmd))
        self.set_status(f"Conversion {settings['label']} en cours...")
        self.active_backend = "conversion"

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            for line in self.process.stdout:
                self.log_text(line.rstrip())
            self.process.wait()

            if self.process.returncode == 0 and os.path.isfile(output):
                self.final_file = output
                self.log_text(f"Conversion terminée : {output}")
                GLib.idle_add(
                    self.close_remux_dialog,
                    "Conversion terminée",
                    f"Fichier final : {output}\n\nLe TS original est conservé.",
                    Gtk.MessageType.INFO
                )
            else:
                self.final_file = ts_file
                GLib.idle_add(
                    self.close_remux_dialog,
                    "Conversion interrompue",
                    f"La conversion a échoué ou a été arrêtée. Le TS est conservé :\n{ts_file}",
                    Gtk.MessageType.ERROR
                )
        except Exception as e:
            self.final_file = ts_file
            self.log_text(f"Erreur de conversion : {e}")
            GLib.idle_add(
                self.close_remux_dialog,
                "Conversion impossible",
                f"Le TS est conservé :\n{ts_file}",
                Gtk.MessageType.ERROR
            )

    def update_stats(self):
        if not self.process and not self.recording_start:
            self.stats_timer_id = None
            return False

        elapsed = int(time.time() - self.recording_start) if self.recording_start else 0
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60

        size_mb = 0
        if self.current_ts_file and os.path.exists(self.current_ts_file):
            size_mb = os.path.getsize(self.current_ts_file) / 1024 / 1024

        if self.active_backend == "yt-dlp":
            progress = self.youtube_progress or "préparation..."
            self.stats.set_text(f"Durée : {h:02d}:{m:02d}:{s:02d} — YouTube : {progress}")
        else:
            self.stats.set_text(f"Durée : {h:02d}:{m:02d}:{s:02d} — Taille : {size_mb:.1f} Mo")

        if self.process:
            return True

        self.recording_start = None
        self.stats_timer_id = None
        return False

    def remux(self, ts_file, fmt):
        if not self.ffmpeg:
            self.log_text("Remux impossible : FFmpeg introuvable.")
            return

        if not os.path.exists(ts_file):
            self.log_text("Remux impossible : fichier TS introuvable.")
            return

        output = os.path.splitext(ts_file)[0] + "." + fmt
        cmd = [self.ffmpeg, "-y", "-i", ts_file, "-c", "copy", output]

        GLib.idle_add(self.show_remux_dialog)

        self.log_text("")
        self.log_text("Commande FFmpeg :")
        self.log_text(" ".join(cmd))

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            for line in proc.stdout:
                self.log_text(line.rstrip())

            proc.wait()

            if proc.returncode == 0:
                self.final_file = output
                self.log_text(f"Remux terminé : {output}")
                GLib.idle_add(
                    self.close_remux_dialog,
                    "Remux : fait",
                    f"Fichier final : {output}",
                    Gtk.MessageType.INFO
                )

            elif fmt == "mp4":
                self.log_text("MP4 impossible. Proposition de remux en MKV.")
                GLib.idle_add(self.ask_mkv_fallback, ts_file)

            else:
                GLib.idle_add(
                    self.close_remux_dialog,
                    "Remux impossible",
                    "FFmpeg n’a pas réussi à remuxer ce fichier. Le TS est conservé.",
                    Gtk.MessageType.ERROR
                )

        except Exception:
            GLib.idle_add(
                self.close_remux_dialog,
                "Remux impossible",
                "Une erreur est survenue pendant le remux. Le TS est conservé.",
                Gtk.MessageType.ERROR
            )

    def ask_mkv_fallback(self, ts_file):
        if self.remux_dialog:
            self.remux_dialog.destroy()
            self.remux_dialog = None

        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Le MP4 a échoué"
        )
        dialog.format_secondary_text("Voulez-vous tenter un remux en MKV à la place ?")

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            threading.Thread(target=self.remux, args=(ts_file, "mkv"), daemon=True).start()
        else:
            self.show_message("Fichier TS conservé", f"Fichier conservé : {ts_file}", Gtk.MessageType.INFO)

        return False

    def show_remux_dialog(self, title="Remux en cours...",
                          detail="Ne ferme pas KageStream pendant cette étape."):
        self.remux_dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text=title
        )
        self.remux_dialog.format_secondary_text(detail)
        self.remux_dialog.show_all()
        return False

    def close_remux_dialog(self, title, message, message_type):
        if self.remux_dialog:
            self.remux_dialog.destroy()
            self.remux_dialog = None

        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=message_type,
            buttons=Gtk.ButtonsType.OK,
            text=title
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()
        return False

    def stop_recording(self, button):
        if not self.process:
            return

        question = (
            "Arrêter la conversion ?"
            if self.active_backend == "conversion"
            else "Arrêter l’enregistrement ?"
        )
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=question
        )
        if self.active_backend == "yt-dlp":
            dialog.format_secondary_text(
                "KageStream demandera à yt-dlp de finaliser proprement le fichier déjà téléchargé."
            )
        elif self.active_backend == "conversion":
            dialog.format_secondary_text(
                "La conversion sera interrompue. La capture TS originale restera conservée."
            )
        else:
            dialog.format_secondary_text(
                "Le fichier déjà enregistré sera conservé puis remuxé si nécessaire."
            )

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            self.user_stopped = True
            self.log_text("Arrêt demandé par l’utilisateur.")

            if self.active_backend == "yt-dlp":
                try:
                    if sys.platform == "win32" and hasattr(signal, "CTRL_BREAK_EVENT"):
                        self.process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        self.process.send_signal(signal.SIGINT)
                except Exception:
                    self.process.terminate()
            else:
                self.process.terminate()

    def open_current_folder(self, button):
        target = self.final_file or self.current_ts_file or self.current_folder()
        open_folder(target)

    def show_message(self, title, message, message_type):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=message_type,
            buttons=Gtk.ButtonsType.OK,
            text=title
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def show_update_checker(self, button):
        self.check_dependencies(silent=True)

        dialog = Gtk.Dialog(
            title="Mises à jour",
            transient_for=self,
            flags=0
        )

        dialog.add_button("Fermer", Gtk.ResponseType.CLOSE)
        dialog.set_default_size(760, 560)

        content = dialog.get_content_area()
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_spacing(12)

        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>Mises à jour — {APP_TITLE}</b>")
        content.pack_start(title, False, False, 0)

        info = Gtk.Label(
            label="Vérification des dépendances en ligne...",
            xalign=0
        )
        info.set_line_wrap(True)
        content.pack_start(info, False, False, 0)

        grid = Gtk.Grid(column_spacing=16, row_spacing=10)
        content.pack_start(grid, False, False, 0)

        install_title = Gtk.Label(xalign=0)
        install_title.set_markup("<b>Installation directe — sans gestionnaire de paquets</b>")
        content.pack_start(install_title, False, False, 0)

        install_grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        content.pack_start(install_grid, False, False, 0)

        install_missing_button = Gtk.Button(label="Installer tous les éléments manquants")
        install_missing_button.set_sensitive(not self.dependency_installing)
        install_missing_button.connect("clicked", self.install_dependencies)
        install_grid.attach(install_missing_button, 0, 0, 2, 1)

        ytdlp_install_button = Gtk.Button(
            label=(
                "Mettre à jour yt-dlp directement"
                if self.ytdlp
                else "Installer yt-dlp directement"
            )
        )
        ytdlp_install_button.set_sensitive(
            not self.ytdlp_installing and not self.dependency_installing
        )
        ytdlp_install_button.connect("clicked", self.install_ytdlp)
        install_grid.attach(ytdlp_install_button, 0, 1, 1, 1)

        deno_install_button = Gtk.Button(
            label=(
                "Mettre à jour Deno directement"
                if self.javascript_runtime_name == "deno"
                else "Installer Deno directement"
            )
        )
        deno_install_button.set_sensitive(not self.dependency_installing)
        deno_install_button.connect("clicked", self.install_dependencies, ["deno"])
        install_grid.attach(deno_install_button, 1, 1, 1, 1)

        ffmpeg_install_button = Gtk.Button(
            label=(
                "Mettre à jour FFmpeg + FFprobe"
                if self.ffmpeg and self.ffprobe
                else "Installer FFmpeg + FFprobe"
            )
        )
        ffmpeg_install_button.set_sensitive(not self.dependency_installing)
        ffmpeg_install_button.connect("clicked", self.install_dependencies, ["ffmpeg"])
        install_grid.attach(ffmpeg_install_button, 0, 2, 1, 1)

        streamlink_install_button = Gtk.Button(
            label=(
                "Mettre à jour l’AppImage Streamlink"
                if self.streamlink
                else "Installer l’AppImage Streamlink"
            )
        )
        streamlink_install_button.set_sensitive(not self.dependency_installing)
        streamlink_install_button.connect("clicked", self.install_dependencies, ["streamlink"])
        install_grid.attach(streamlink_install_button, 1, 2, 1, 1)

        update_streamlink_button = Gtk.Button(label="Mettre à jour Streamlink via pip — avancé")
        update_streamlink_button.set_sensitive(False)
        update_streamlink_button.connect("clicked", self.update_streamlink)
        content.pack_start(update_streamlink_button, False, False, 0)

        content.show_all()

        def set_rows(rows, streamlink_update_available=False, message=""):
            for child in grid.get_children():
                grid.remove(child)

            for index, (name, current, latest, state) in enumerate(rows):
                grid.attach(Gtk.Label(label=name, xalign=0), 0, index, 1, 1)

                current_label = Gtk.Label(label=current, xalign=0)
                current_label.set_selectable(True)
                grid.attach(current_label, 1, index, 1, 1)

                latest_label = Gtk.Label(label=latest, xalign=0)
                latest_label.set_selectable(True)
                grid.attach(latest_label, 2, index, 1, 1)

                grid.attach(Gtk.Label(label=state, xalign=0), 3, index, 1, 1)

            update_streamlink_button.set_sensitive(streamlink_update_available)
            info.set_text(message or "Vérification terminée.")
            grid.show_all()
            return False

        def worker():
            rows = []
            streamlink_update_available = False

            current_streamlink = get_streamlink_installed_version(self.streamlink)
            current_ffmpeg = get_ffmpeg_installed_version(self.ffmpeg)
            current_ytdlp = get_ytdlp_installed_version(self.ytdlp)

            try:
                latest_streamlink = get_latest_streamlink_version()

                if current_streamlink and latest_streamlink:
                    if is_newer_version(latest_streamlink, current_streamlink):
                        streamlink_state = "Mise à jour disponible"
                        streamlink_update_available = True
                    else:
                        streamlink_state = "À jour"
                elif not current_streamlink:
                    streamlink_state = "Non détecté"
                    latest_streamlink = latest_streamlink or "Inconnu"
                else:
                    streamlink_state = "Impossible de vérifier"

            except Exception as e:
                latest_streamlink = "Erreur réseau"
                streamlink_state = "Vérification impossible"
                self.log_text(f"Erreur vérification Streamlink : {e}")

            rows.append((
                "Streamlink",
                current_streamlink or "Non détecté",
                latest_streamlink or "Inconnu",
                streamlink_state
            ))

            try:
                latest_ytdlp = get_latest_ytdlp_version()

                if current_ytdlp and latest_ytdlp:
                    ytdlp_state = (
                        "Mise à jour disponible"
                        if is_newer_version(latest_ytdlp, current_ytdlp)
                        else "À jour"
                    )
                elif not current_ytdlp:
                    ytdlp_state = "Non détecté"
                    latest_ytdlp = latest_ytdlp or "Inconnu"
                else:
                    ytdlp_state = "Impossible de vérifier"

            except Exception as e:
                latest_ytdlp = "Erreur réseau"
                ytdlp_state = "Vérification impossible"
                self.log_text(f"Erreur vérification yt-dlp : {e}")

            rows.append((
                "yt-dlp",
                current_ytdlp or "Non détecté",
                latest_ytdlp or "Inconnu",
                ytdlp_state
            ))

            rows.append((
                "FFmpeg",
                current_ffmpeg or "Non détecté",
                "Build Linux BtbN vérifié",
                "Installation directe disponible avec FFprobe"
            ))

            rows.append((
                "JavaScript YouTube",
                (
                    f"{self.javascript_runtime_name} — {self.javascript_runtime_path}"
                    if self.javascript_runtime_path
                    else "Non détecté"
                ),
                "Deno recommandé, Node accepté",
                "Nécessaire pour toutes les qualités YouTube"
            ))

            rows.append((
                "GTK",
                f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}",
                "Fourni par le système",
                "Géré par Linux"
            ))

            message = (
                "KageStream peut installer yt-dlp, Deno, Streamlink et FFmpeg/FFprobe "
                "dans son dossier utilisateur, sans pacman ni sudo. Chaque téléchargement "
                "est contrôlé avec une somme SHA-256 publiée par sa source. GTK reste fourni "
                "par le système ou par l’AppImage KageStream."
            )

            GLib.idle_add(set_rows, rows, streamlink_update_available, message)

        threading.Thread(target=worker, daemon=True).start()

        dialog.run()
        dialog.destroy()

    def missing_dependency_ids(self):
        missing = []
        if not self.ytdlp:
            missing.append("yt-dlp")
        if not self.javascript_runtime_path:
            missing.append("deno")
        if not self.ffmpeg or not self.ffprobe:
            missing.append("ffmpeg")
        if not self.streamlink:
            missing.append("streamlink")
        return missing

    def install_dependencies(self, button, requested=None):
        if self.dependency_installing or self.ytdlp_installing:
            self.show_message(
                "Installation déjà en cours",
                "Attends la fin du téléchargement en cours.",
                Gtk.MessageType.INFO
            )
            return

        if self.process:
            self.show_message(
                "Enregistrement en cours",
                "Arrête l’enregistrement avant de modifier les dépendances.",
                Gtk.MessageType.WARNING
            )
            return

        dependency_ids = list(requested) if requested else self.missing_dependency_ids()
        if not dependency_ids:
            self.show_message(
                "Aucun élément indispensable ne manque",
                "yt-dlp, un moteur JavaScript, FFmpeg/FFprobe et Streamlink sont déjà détectés.",
                Gtk.MessageType.INFO
            )
            return

        labels = {
            "yt-dlp": "yt-dlp — binaire autonome officiel",
            "deno": "Deno — moteur JavaScript officiel",
            "ffmpeg": "FFmpeg + FFprobe — build Linux BtbN référencé par ffmpeg.org",
            "streamlink": "Streamlink — AppImage officielle avec ses dépendances",
        }
        selected_text = "\n".join(f"• {labels[item]}" for item in dependency_ids)

        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Télécharger les dépendances sélectionnées ?"
        )
        dialog.format_secondary_text(
            f"{selected_text}\n\n"
            f"Installation dans :\n{user_bin_dir()}\n\n"
            "Chaque fichier sera vérifié par SHA-256 avant activation. "
            "Aucun sudo, pacman ou miroir Arch ne sera utilisé. "
            "Si tout manque, le téléchargement peut dépasser 200 Mio."
        )
        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.YES:
            return

        self.dependency_installing = True
        if "yt-dlp" in dependency_ids:
            self.ytdlp_installing = True
        button.set_sensitive(False)
        self.log_text("")
        self.log_text("===== Installation directe des dépendances =====")
        self.log_text(f"Destination : {user_bin_dir()}")

        threading.Thread(
            target=self.install_dependencies_worker,
            args=(button, dependency_ids),
            daemon=True
        ).start()

    def install_dependencies_worker(self, button, dependency_ids):
        installers = {
            "yt-dlp": download_ytdlp_binary,
            "deno": download_deno_binary,
            "ffmpeg": download_ffmpeg_binaries,
            "streamlink": download_streamlink_appimage,
        }
        labels = {
            "yt-dlp": "yt-dlp",
            "deno": "Deno",
            "ffmpeg": "FFmpeg + FFprobe",
            "streamlink": "Streamlink",
        }
        successes = []
        failures = []

        for dependency_id in dependency_ids:
            label = labels[dependency_id]
            self.log_text(f"\nInstallation de {label}…")

            def progress(message, label=label):
                self.set_status(f"{label} — {message}")

            try:
                path, version, checksum = installers[dependency_id](progress)
                successes.append((label, version, path))
                self.log_text(f"SHA-256 vérifié : {checksum}")
                self.log_text(f"{version} installé : {path}")
            except Exception as e:
                error_message = str(e)
                failures.append((label, error_message))
                self.log_text(f"Échec de {label} : {error_message}")

        def finish():
            self.dependency_installing = False
            self.ytdlp_installing = False
            try:
                if button.get_parent() is not None:
                    button.set_sensitive(True)
            except RuntimeError:
                pass

            self.check_dependencies(silent=True)
            sections = []
            if successes:
                sections.append(
                    "Installés et vérifiés :\n"
                    + "\n".join(f"• {label} — {version}" for label, version, _path in successes)
                )
            if failures:
                sections.append(
                    "Échecs :\n"
                    + "\n".join(f"• {label} — {error}" for label, error in failures)
                )

            self.show_message(
                "Installation terminée" if successes else "Installation impossible",
                "\n\n".join(sections),
                Gtk.MessageType.WARNING if failures else Gtk.MessageType.INFO
            )
            return False

        GLib.idle_add(finish)

    def install_ytdlp(self, button):
        if self.ytdlp_installing or self.dependency_installing:
            return

        if self.process:
            self.show_message(
                "Enregistrement en cours",
                "Arrête l’enregistrement avant d’installer ou de mettre à jour yt-dlp.",
                Gtk.MessageType.WARNING
            )
            return

        try:
            asset_name, _installed_name = ytdlp_release_asset()
        except Exception as e:
            self.show_message(
                "Plateforme non prise en charge",
                str(e),
                Gtk.MessageType.ERROR
            )
            return

        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Installer yt-dlp directement ?"
        )
        dialog.format_secondary_text(
            f"KageStream va télécharger le binaire officiel {asset_name} depuis GitHub, "
            "vérifier sa somme SHA-256, puis l’installer ici :\n\n"
            f"{user_bin_dir()}\n\n"
            "Aucun paquet ni miroir Arch ne sera utilisé."
        )

        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.YES:
            return

        self.ytdlp_installing = True
        self.dependency_installing = True
        button.set_sensitive(False)
        self.log_text("")
        self.log_text(f"Installation directe de yt-dlp ({asset_name})…")
        self.log_text(f"Destination : {user_bin_dir()}")

        threading.Thread(
            target=self.install_ytdlp_worker,
            args=(button,),
            daemon=True
        ).start()

    def install_ytdlp_worker(self, button):
        try:
            path, version, checksum = download_ytdlp_binary(self.set_status)
            self.log_text(f"SHA-256 vérifié : {checksum}")
            self.log_text(f"yt-dlp {version} installé : {path}")

            def success():
                self.ytdlp_installing = False
                self.dependency_installing = False
                try:
                    if button.get_parent() is not None:
                        button.set_label("Mettre à jour yt-dlp directement")
                        button.set_sensitive(True)
                except RuntimeError:
                    pass
                self.check_dependencies(silent=True)
                self.show_message(
                    "yt-dlp est prêt",
                    f"La version {version} a été installée et vérifiée.\n\n{path}",
                    Gtk.MessageType.INFO
                )
                return False

            GLib.idle_add(success)

        except Exception as e:
            error_message = str(e)
            self.log_text(f"Échec de l’installation directe de yt-dlp : {error_message}")

            def failure(error_message=error_message):
                self.ytdlp_installing = False
                self.dependency_installing = False
                try:
                    if button.get_parent() is not None:
                        button.set_sensitive(True)
                except RuntimeError:
                    pass
                self.check_dependencies(silent=True)
                self.show_message(
                    "Installation de yt-dlp impossible",
                    f"{error_message}\n\nAucun fichier non vérifié n’a été conservé.",
                    Gtk.MessageType.ERROR
                )
                return False

            GLib.idle_add(failure)

    def update_streamlink(self, button):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Mettre à jour Streamlink ?"
        )
        dialog.format_secondary_text(
            "KageStream va lancer : python -m pip install --upgrade streamlink\n\n"
            "Dans une AppImage, la mise à jour peut ne pas modifier le Streamlink embarqué. "
            "Dans ce cas, il faudra reconstruire l’AppImage."
        )

        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.YES:
            return

        self.set_status("Mise à jour de Streamlink...")
        self.log_text("")
        self.log_text("Mise à jour Streamlink :")
        self.log_text(f"{sys.executable} -m pip install --upgrade streamlink")

        threading.Thread(target=self.update_streamlink_worker, daemon=True).start()

    def update_streamlink_worker(self):
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "--upgrade", "streamlink"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            for line in proc.stdout:
                self.log_text(line.rstrip())

            proc.wait()

            if proc.returncode == 0:
                self.log_text("Mise à jour Streamlink terminée.")
                GLib.idle_add(
                    self.show_message,
                    "Mise à jour terminée",
                    "Streamlink a été mis à jour. Redémarre KageStream si nécessaire.",
                    Gtk.MessageType.INFO
                )
            else:
                self.log_text("La mise à jour de Streamlink a échoué.")
                GLib.idle_add(
                    self.show_message,
                    "Mise à jour impossible",
                    "La mise à jour de Streamlink a échoué. Regarde les logs.",
                    Gtk.MessageType.ERROR
                )

        except Exception as e:
            self.log_text(f"Erreur mise à jour Streamlink : {e}")
            GLib.idle_add(
                self.show_message,
                "Mise à jour impossible",
                "Une erreur est survenue pendant la mise à jour.",
                Gtk.MessageType.ERROR
            )

        finally:
            self.check_dependencies(silent=True)
            self.set_status("Prêt.")

    def write_diagnostic_log(self):
        self.log_text("")
        self.log_text("===== Diagnostic =====")
        self.log_text(APP_TITLE)
        self.log_text(f"Système : {platform.platform()}")
        self.log_text(f"Mode : {'exécutable' if is_frozen() else 'script Python'}")
        self.log_text(f"Dossier application : {app_dir()}")
        self.log_text(f"Dépendances utilisateur : {user_bin_dir()}")
        self.log_text(f"GTK : OK — {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}")
        self.log_text(f"Streamlink : {'OK — ' + self.streamlink if self.streamlink else 'MANQUANT'}")
        self.log_text(f"yt-dlp : {'OK — ' + self.ytdlp if self.ytdlp else 'MANQUANT — YouTube indisponible'}")
        self.log_text(
            "JavaScript YouTube : "
            + (
                f"OK — {self.javascript_runtime_name} — {self.javascript_runtime_path}"
                if self.javascript_runtime_path
                else "MANQUANT — Deno ou Node requis pour toutes les qualités"
            )
        )
        self.log_text(f"FFmpeg : {'OK — ' + self.ffmpeg if self.ffmpeg else 'MANQUANT'}")
        self.log_text(f"FFprobe : {'OK — ' + self.ffprobe if self.ffprobe else 'optionnel, non détecté'}")
        self.log_text("======================")

    def show_diagnostic(self, button):
        self.check_dependencies(silent=True)

        dialog = Gtk.Dialog(title="Diagnostic", transient_for=self, flags=0)
        dialog.add_button("Actualiser", Gtk.ResponseType.APPLY)
        dialog.add_button("Fermer", Gtk.ResponseType.CLOSE)
        dialog.set_default_size(560, 360)

        content = dialog.get_content_area()
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_spacing(12)

        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{APP_TITLE}</b>")
        content.pack_start(title, False, False, 0)

        status = Gtk.Label(xalign=0)
        content.pack_start(status, False, False, 0)

        grid = Gtk.Grid(column_spacing=16, row_spacing=10)
        content.pack_start(grid, False, False, 0)

        def refresh():
            self.check_dependencies(silent=True)
            if (
                self.streamlink
                and self.ffmpeg
                and self.ytdlp
                and self.javascript_runtime_path
            ):
                status.set_markup("🟢 <b>Tout est prêt, y compris YouTube.</b>")
            elif self.streamlink or self.ffmpeg:
                status.set_markup("🟡 <b>Fonctionnement partiel — consulte les dépendances.</b>")
            else:
                status.set_markup("🔴 <b>Configuration incomplète.</b>")

            rows = [
                ("GTK", "🟢", f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"),
                ("Streamlink", "🟢" if self.streamlink else "🔴", get_tool_version(self.streamlink, ["--version"])),
                ("yt-dlp", "🟢" if self.ytdlp else "🔴", get_tool_version(self.ytdlp, ["--version"])),
                (
                    "JavaScript YouTube",
                    "🟢" if self.javascript_runtime_path else "🔴",
                    (
                        f"{self.javascript_runtime_name} — {self.javascript_runtime_path}"
                        if self.javascript_runtime_path
                        else "Deno ou Node non détecté"
                    )
                ),
                ("FFmpeg", "🟢" if self.ffmpeg else "🔴", get_tool_version(self.ffmpeg, ["-version"])),
                ("FFprobe", "🟢" if self.ffprobe else "🟡", get_tool_version(self.ffprobe, ["-version"])),
                ("Python", "🟢", sys.version.split()[0]),
                ("Santé dernier enregistrement", "🟢" if self.stream_health == "OK" else "🟡", self.last_health_report),
                ("Mode", "🟢", "Exécutable" if is_frozen() else "Script Python"),
            ]

            for child in grid.get_children():
                grid.remove(child)

            for index, (name, icon, value) in enumerate(rows):
                grid.attach(Gtk.Label(label=f"{icon} {name}", xalign=0), 0, index, 1, 1)

                value_label = Gtk.Label(label=value, xalign=0)
                value_label.set_selectable(True)
                value_label.set_line_wrap(True)
                value_label.set_max_width_chars(42)

                grid.attach(value_label, 1, index, 1, 1)

            grid.show_all()

        refresh()
        content.show_all()

        while True:
            response = dialog.run()

            if response == Gtk.ResponseType.APPLY:
                refresh()
                self.write_diagnostic_log()
            else:
                break

        dialog.destroy()


if __name__ == "__main__":
    win = KageStream()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()

