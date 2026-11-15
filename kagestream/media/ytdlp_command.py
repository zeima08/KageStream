"""Construction de la commande yt-dlp, indépendante de GTK.

Ces fonctions étaient des méthodes de KageStreamWindow : les extraire rend la
construction de commande testable sans fenêtre, et permet de vérifier
directement les arguments produits (format, cookies, sous-titres, métadonnées).
"""

import os

from kagestream.media.ytdlp import youtube_cookie_args


class YtdlpTools:
    """Outils et réglages dont dépend la commande yt-dlp."""

    def __init__(self, ytdlp=None, ffmpeg=None, aria2c=None,
                 javascript_runtime_name=None, javascript_runtime_path=None,
                 cookies_browser=None, auto_only_codes=None):
        self.ytdlp = ytdlp
        self.ffmpeg = ffmpeg
        self.aria2c = aria2c
        self.javascript_runtime_name = javascript_runtime_name
        self.javascript_runtime_path = javascript_runtime_path
        self.cookies_browser = cookies_browser
        self.auto_only_codes = set(auto_only_codes or ())


def youtube_output_template(folder, filename, is_playlist=False):
    if is_playlist:
        # Un nom fixe écraserait chaque piste de la playlist : on préfixe
        # toujours par l'index pour garder un fichier par vidéo.
        return os.path.join(folder, "%(playlist_index)03d - %(title).120s [%(id)s].%(ext)s")

    if filename:
        # Dans un modèle yt-dlp, un pourcentage littéral doit être doublé.
        safe_name = filename.replace("%", "%%")
        return os.path.join(folder, safe_name + ".%(ext)s")

    return os.path.join(folder, "%(title).120s [%(id)s].%(ext)s")


def build_ytdlp_command(url, folder, config, tools, cookies_browser=None):
    resolution = config["resolution"]
    container = config["container"]

    if resolution == "best":
        format_selector = "bestvideo*+bestaudio/best"
    else:
        format_selector = (
            f"bestvideo*[height<={resolution}]+bestaudio/"
            f"best[height<={resolution}]/best"
        )

    is_playlist = config["source_mode"] == "youtube_playlist"

    cmd = [
        tools.ytdlp,
        "--ignore-config",
        "--newline",
        "--progress",
        "--yes-playlist" if is_playlist else "--no-playlist",
        "--no-overwrites",
        "--continue",
        "--concurrent-fragments", "4",
        "--trim-filenames", "180",
        "--format", format_selector,
        "--merge-output-format", container,
        "--remux-video", container,
        "--output", youtube_output_template(folder, config["filename"], is_playlist),
        "--print", "after_move:KAGESTREAM_FINAL:%(filepath)s",
    ]

    cmd.extend(youtube_cookie_args(url, cookies_browser or tools.cookies_browser))

    if tools.javascript_runtime_name and tools.javascript_runtime_path:
        cmd.extend([
            "--js-runtimes",
            f"{tools.javascript_runtime_name}:{tools.javascript_runtime_path}"
        ])

    if tools.ffmpeg:
        cmd.extend(["--ffmpeg-location", os.path.dirname(tools.ffmpeg)])

    if tools.aria2c:
        cmd.extend([
            "--external-downloader", tools.aria2c,
            "--external-downloader-args", "aria2c:-x16 -s16 -k1M",
        ])

    if config["source_mode"] == "youtube_live_start":
        cmd.append("--live-from-start")

    selected_subtitles = config["subtitles"]
    if selected_subtitles != "none":
        cmd.extend(["--write-subs", "--sub-format", "srt/vtt/best"])

        if selected_subtitles == "all":
            cmd.extend(["--sub-langs", "all,-live_chat"])
        else:
            cmd.extend(["--sub-langs", selected_subtitles])

        if config.get("auto_subs") or selected_subtitles == "all" or selected_subtitles in tools.auto_only_codes:
            cmd.append("--write-auto-subs")

        if config.get("embed_subs"):
            cmd.append("--embed-subs")

    if config.get("embed_metadata"):
        cmd.extend(["--embed-metadata", "--embed-chapters"])

    if config.get("embed_thumbnail"):
        cmd.append("--embed-thumbnail")

    if config.get("write_infojson"):
        cmd.append("--write-info-json")
        if container == "mkv":
            cmd.append("--embed-info-json")

    cmd.extend(["--", url])
    return cmd
