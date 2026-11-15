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


def extract_zip_safely(archive_path, destination):
    """Extrait une archive zip en refusant toute sortie du dossier cible.

    `ZipFile.extractall` suit les chemins relatifs contenus dans l'archive :
    un membre « ../../x » écrirait hors de la destination. Chaque membre est
    donc résolu puis vérifié avant écriture."""
    destination_root = os.path.abspath(destination)
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = os.path.abspath(os.path.join(destination_root, member.filename))
            if target != destination_root and not target.startswith(destination_root + os.sep):
                raise RuntimeError(f"Archive Streamlink suspecte : {member.filename}")
            if member.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(member) as source, open(target, "wb") as output:
                shutil.copyfileobj(source, output)


def download_streamlink_portable(progress_callback=None, timeout=300):
    """Installe Streamlink sous Windows depuis le build portable officiel.

    Il n'existe ni paquet PyPI utilisable (cffi, lxml et pycryptodome n'ont pas
    de wheels pour le Python embarqué) ni installateur intégré : le dépôt
    streamlink/windows-builds publie une archive autonome dont l'empreinte
    SHA-256 accompagne la release."""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        architecture = "x86_64"
    elif machine in ("arm64", "aarch64"):
        architecture = "arm64"
    else:
        raise RuntimeError(f"Architecture Streamlink Windows non prise en charge : {machine}.")

    if progress_callback:
        progress_callback("Recherche du build portable Streamlink…")
    release = github_latest_release("streamlink/windows-builds", timeout)
    candidates = [
        asset for asset in release.get("assets", [])
        if asset.get("name", "").startswith("streamlink-")
        and asset.get("name", "").endswith(f"-{architecture}.zip")
    ]
    if not candidates:
        raise RuntimeError("Build portable Streamlink introuvable pour cette architecture.")

    asset = candidates[0]
    expected_checksum = (asset.get("digest") or "").removeprefix("sha256:")
    target_dir = user_bin_dir()
    os.makedirs(target_dir, exist_ok=True)
    archive_path = os.path.join(target_dir, ".streamlink.download.zip")
    staging_dir = os.path.join(target_dir, ".streamlink.download")

    try:
        checksum = download_verified_file(
            asset.get("browser_download_url", ""),
            archive_path,
            expected_checksum,
            "Streamlink",
            progress_callback,
            timeout
        )

        shutil.rmtree(staging_dir, ignore_errors=True)
        os.makedirs(staging_dir)
        extract_zip_safely(archive_path, staging_dir)

        executable = None
        for root, _dirs, files in os.walk(staging_dir):
            if "streamlink.exe" in files:
                executable = os.path.join(root, "streamlink.exe")
                break
        if executable is None:
            raise RuntimeError("streamlink.exe est absent de l'archive téléchargée.")

        validation = subprocess.run(
            [executable, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=90
        )
        if validation.returncode != 0:
            raise RuntimeError("Le Streamlink téléchargé ne démarre pas correctement.")
        version = (
            validation.stdout.strip().splitlines()[0]
            if validation.stdout.strip() else "Streamlink"
        )

        # Le build portable est un ensemble de fichiers solidaires : on copie
        # l'arborescence entière dans le dossier d'outils de KageStream.
        portable_root = os.path.dirname(executable)
        for entry in os.listdir(portable_root):
            source = os.path.join(portable_root, entry)
            destination = os.path.join(target_dir, entry)
            if os.path.isdir(source):
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination)

        return os.path.join(target_dir, "streamlink.exe"), version, checksum

    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        try:
            if os.path.exists(archive_path):
                os.remove(archive_path)
        except OSError:
            pass


def download_streamlink_appimage(progress_callback=None, timeout=90):
    if sys.platform == "win32":
        return download_streamlink_portable(progress_callback, timeout)
    if not sys.platform.startswith("linux"):
        raise RuntimeError(
            "L’installation directe de Streamlink est disponible sous Linux et Windows."
        )

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


def ffmpeg_build_platform():
    """Suffixe de plateforme des assets BtbN et extension d'archive.

    BtbN publie les mêmes archives pour Linux et Windows, avec des noms
    symétriques (ffmpeg-nX.Y-latest-<plateforme>-gpl-X.Y.{tar.xz,zip})."""
    machine = platform.machine().lower()

    if sys.platform == "win32":
        if machine in ("x86_64", "amd64"):
            return "win64", ".zip", ".exe"
        if machine in ("arm64", "aarch64"):
            return "winarm64", ".zip", ".exe"
        raise RuntimeError(f"Architecture FFmpeg Windows non prise en charge : {machine}.")

    if sys.platform.startswith("linux"):
        if machine in ("x86_64", "amd64"):
            return "linux64", ".tar.xz", ""
        if machine in ("arm64", "aarch64"):
            return "linuxarm64", ".tar.xz", ""
        raise RuntimeError(f"Architecture FFmpeg non prise en charge : {machine}.")

    raise RuntimeError(
        "L’installation directe de FFmpeg est disponible sous Linux et Windows."
    )


def extract_named_binaries(archive_path, destination_paths):
    """Extrait des exécutables nommés depuis une archive .zip ou .tar.xz.

    Seuls les fichiers situés dans un dossier « bin » sont retenus ; les noms
    attendus viennent des clés de `destination_paths` (par exemple
    `ffmpeg` sous Linux, `ffmpeg.exe` sous Windows).
    Retourne l'ensemble des noms trouvés."""
    found = set()
    path_marker = "/bin/"

    if archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                name = member.filename.replace("\\", "/")
                base = os.path.basename(name)
                if member.is_dir() or path_marker not in f"/{name}":
                    continue
                for wanted, destination in destination_paths.items():
                    if base == wanted:
                        with archive.open(member) as source, open(destination, "wb") as target:
                            shutil.copyfileobj(source, target)
                        found.add(wanted)
    else:
        with tarfile.open(archive_path, mode="r:xz") as archive:
            for member in archive.getmembers():
                base = os.path.basename(member.name)
                if not member.isfile() or path_marker not in f"/{member.name.replace(chr(92), '/')}":
                    continue
                for wanted, destination in destination_paths.items():
                    if base == wanted:
                        source = archive.extractfile(member)
                        if source is None:
                            continue
                        with source, open(destination, "wb") as target:
                            shutil.copyfileobj(source, target)
                        found.add(wanted)

    return found


def download_ffmpeg_binaries(progress_callback=None, timeout=120):
    platform_name, extension, binary_suffix = ffmpeg_build_platform()
    is_windows = sys.platform == "win32"

    if progress_callback:
        progress_callback("Recherche du dernier build FFmpeg recommandé…")
    release = github_latest_release("BtbN/FFmpeg-Builds", timeout)
    pattern = re.compile(
        rf"^ffmpeg-n(\d+(?:\.\d+)+)-latest-{platform_name}-gpl-\1{re.escape(extension)}$"
    )
    candidates = []
    for asset in release.get("assets", []):
        match = pattern.match(asset.get("name", ""))
        if match:
            candidates.append((version_tuple(match.group(1)), asset))
    if not candidates:
        raise RuntimeError(
            "Build FFmpeg vérifiable introuvable pour cette architecture."
        )

    _version_key, asset = max(candidates, key=lambda item: item[0])
    expected_checksum = (asset.get("digest") or "").removeprefix("sha256:")
    target_dir = user_bin_dir()
    archive_path = os.path.join(target_dir, f".ffmpeg.download{extension}")

    # Sous Windows, les exécutables gardent leur extension .exe.
    binary_names = {
        "ffmpeg": f"ffmpeg{binary_suffix}",
        "ffprobe": f"ffprobe{binary_suffix}",
    }
    temporary_paths = {
        name: os.path.join(target_dir, f".{name}.download{binary_suffix}")
        for name in binary_names
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

        # Clé : nom du fichier dans l'archive ; valeur : chemin temporaire.
        destinations = {
            binary_names[logical]: temporary_paths[logical]
            for logical in binary_names
        }
        found = extract_named_binaries(archive_path, destinations)

        if found != set(binary_names.values()):
            raise RuntimeError("FFmpeg ou FFprobe est absent de l’archive téléchargée.")

        versions = {}
        for logical, temporary_path in temporary_paths.items():
            if not is_windows:
                os.chmod(temporary_path, 0o755)
            validation = subprocess.run(
                [temporary_path, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=20
            )
            if validation.returncode != 0:
                raise RuntimeError(f"Le binaire {logical} téléchargé ne démarre pas.")
            versions[logical] = (
                validation.stdout.strip().splitlines()[0]
                if validation.stdout.strip()
                else logical
            )

        installed_ffmpeg = os.path.join(target_dir, binary_names["ffmpeg"])
        for logical, temporary_path in temporary_paths.items():
            os.replace(temporary_path, os.path.join(target_dir, binary_names[logical]))

        return installed_ffmpeg, versions["ffmpeg"], checksum

    finally:
        for path in [archive_path] + list(temporary_paths.values()):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
