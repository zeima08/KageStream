"""Détection et description des sources, indépendante de GTK.

Ces fonctions étaient des méthodes de la fenêtre (et appelées depuis les
threads de capture via `window.*`). Les extraire permet d'injecter un contexte
d'outils dans les managers au lieu d'une fenêtre GTK, et de les tester
directement.
"""

import json
import os
import subprocess
from urllib.parse import unquote, urlparse

from kagestream.constants import DIRECT_STREAM_HEADERS, DIRECT_STREAM_USER_AGENT
from kagestream.deps.discovery import version_tuple
from kagestream.utils.filenames import sanitize_filename


class SourceTools:
    """Chemins des outils et callbacks nécessaires à la détection."""

    def __init__(self, streamlink=None, ffmpeg=None, ffprobe=None,
                 streamlink_version="", log_callback=None):
        self.streamlink = streamlink
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.streamlink_version = streamlink_version
        self.log_callback = log_callback

    def log(self, text):
        if self.log_callback:
            self.log_callback(text)


def is_twitch_url(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "twitch.tv" or host.endswith(".twitch.tv")


def streamlink_header_args(url):
    """Certains fournisseurs IPTV (flux DASH/HLS génériques) filtrent le
    user-agent par défaut de Streamlink et répondent 403. Twitch reste
    inchangé : son propre user-agent est celui qui marche pour récupérer les
    jetons d'accès."""
    if is_twitch_url(url):
        return []
    return [
        "--http-header", f"User-Agent={DIRECT_STREAM_USER_AGENT}",
        "--http-header", "Accept=*/*",
    ]


def streamlink_codec_args(url, preference=None, streamlink_version=""):
    if not is_twitch_url(url):
        return []
    if streamlink_version and version_tuple(streamlink_version) < (8, 0):
        return []

    codecs = {
        "h264": "h264",
        "av1": "h264,av1",
        "all": "h264,h265,av1",
    }.get(preference or "h264", "h264")
    return ["--twitch-supported-codecs", codecs]


def streamlink_can_handle_url(streamlink_path, url, timeout=15):
    if not streamlink_path:
        return False

    try:
        result = subprocess.run(
            [streamlink_path, "--can-handle-url", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return result.returncode == 0
    except Exception:
        return False


def direct_source_filename(url):
    try:
        path = unquote(urlparse(url).path).rstrip("/")
        return sanitize_filename(os.path.basename(path))
    except Exception:
        return ""


def probe_direct_source(ffmpeg_path, ffprobe_path, url, log_callback=None, timeout=35):
    """Vérifie qu'une URL est un média directement lisible par FFmpeg :
    FFprobe d'abord (plus rapide et plus verbeux), FFmpeg en repli."""
    def log(text):
        if log_callback:
            log_callback(text)

    if not ffmpeg_path:
        return False, "FFmpeg est nécessaire pour enregistrer un flux direct"

    is_http_url = url.lower().startswith(("http://", "https://"))

    if ffprobe_path:
        cmd = [
            ffprobe_path,
            "-v", "error",
            "-extension_picky", "0",
            "-rw_timeout", "15000000",
            "-analyzeduration", "5000000",
            "-probesize", "5000000",
        ]
        if is_http_url:
            cmd.extend(["-user_agent", DIRECT_STREAM_USER_AGENT, "-headers", DIRECT_STREAM_HEADERS])
        cmd.extend([
            "-show_entries",
            "format=format_name,format_long_name:"
            "stream=codec_type,codec_name,width,height,channels,sample_rate",
            "-of", "json",
            url,
        ])

        log("Commande FFprobe :")
        log(" ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )

            if result.returncode == 0:
                data = json.loads(result.stdout or "{}")
                media_streams = [
                    stream for stream in data.get("streams", [])
                    if stream.get("codec_type") in ("video", "audio")
                ]

                if media_streams:
                    format_name = data.get("format", {}).get("format_name", "flux direct")
                    details = [format_name]

                    video = next(
                        (s for s in media_streams if s.get("codec_type") == "video"), None
                    )
                    audio = next(
                        (s for s in media_streams if s.get("codec_type") == "audio"), None
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
                log(error)

        except Exception as e:
            log(f"FFprobe n’a pas pu analyser le lien : {e}")

    cmd = [
        ffmpeg_path,
        "-v", "error",
        "-nostdin",
        "-extension_picky", "0",
        "-rw_timeout", "15000000",
    ]
    if is_http_url:
        cmd.extend(["-user_agent", DIRECT_STREAM_USER_AGENT, "-headers", DIRECT_STREAM_HEADERS])
    cmd.extend([
        "-i", url,
        "-t", "0.2",
        "-map", "0:v?",
        "-map", "0:a?",
        "-c", "copy",
        "-f", "null",
        "-",
    ])

    log("Test direct avec FFmpeg :")
    log(" ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )

        if result.returncode == 0:
            return True, "média direct reconnu par FFmpeg"

        error = (result.stderr or result.stdout or "").strip()
        if error:
            log(error)

    except Exception as e:
        log(f"FFmpeg n’a pas pu analyser le lien : {e}")

    return False, "aucun flux audio ou vidéo direct détecté"
