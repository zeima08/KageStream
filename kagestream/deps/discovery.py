import json
import os
import re
import shutil
import subprocess
import urllib.request

from kagestream.constants import APP_NAME
from kagestream.utils.paths import app_dir, user_bin_dir


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
