import json
import re
import subprocess

KAGESTREAM_FINAL_MARKER = "KAGESTREAM_FINAL:"
DOWNLOAD_PROGRESS_RE = re.compile(r"\[download\]\s+([0-9]+(?:\.[0-9]+)?%)\s*(.*)")


def analyze_url(ytdlp_path, url, js_runtime_name=None, js_runtime_path=None,
                 allow_playlist=False, timeout=90, log_callback=None):
    """Exécute `yt-dlp --dump-single-json` sur une URL — vidéo YouTube, playlist,
    ou tout site pris en charge par yt-dlp (music.youtube.com, SoundCloud, Bandcamp...).
    Retourne (data, error) comme l'ancien KageStream.analyze_youtube."""
    if not ytdlp_path:
        return None, "yt-dlp est introuvable"

    def log(text):
        if log_callback:
            log_callback(text)

    cmd = [
        ytdlp_path,
        "--ignore-config",
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
    ]
    cmd.append("--yes-playlist" if allow_playlist else "--no-playlist")

    if js_runtime_name and js_runtime_path:
        cmd.extend([
            "--js-runtimes",
            f"{js_runtime_name}:{js_runtime_path}"
        ])

    cmd.extend(["--", url])

    log("Commande d’analyse yt-dlp :")
    log(" ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )

        if result.returncode != 0:
            error = (result.stderr or result.stdout or "Erreur yt-dlp").strip()
            return None, error

        return json.loads(result.stdout), ""

    except subprocess.TimeoutExpired:
        return None, f"L’analyse a dépassé {timeout} secondes."
    except Exception as e:
        return None, str(e)


def extract_final_path(line):
    if KAGESTREAM_FINAL_MARKER not in line:
        return None
    final_path = line.split(KAGESTREAM_FINAL_MARKER, 1)[1].strip()
    return final_path or None


def parse_download_progress(line):
    match = DOWNLOAD_PROGRESS_RE.search(line)
    if not match:
        return None
    percent = match.group(1)
    rest = match.group(2).strip()
    return percent, rest
