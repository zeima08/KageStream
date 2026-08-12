import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

from kagestream.constants import (
    APP_NAME,
    DENO_RELEASE_BASE,
    GITHUB_API_BASE,
    YTDLP_RELEASE_BASE,
)
from kagestream.deps.discovery import fetch_json, version_tuple
from kagestream.utils.paths import user_bin_dir


def ytdlp_release_asset():
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
