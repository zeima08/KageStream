"""Analyse et test des liens, routage Streamlink / FFmpeg direct / yt-dlp."""

import os
import sys
import re
import subprocess
import threading
import time
import platform
import json
from urllib.parse import unquote, urlparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from kagestream.constants import (
    APP_TITLE,
    ICON_PATH,
    DIRECT_STREAM_USER_AGENT,
    DIRECT_STREAM_HEADERS,
    MAX_LOG_LINES,
)
from kagestream.utils.paths import app_dir, external_app_dir, user_bin_dir, is_frozen, open_folder
from kagestream.utils.filenames import sanitize_filename
from kagestream.utils.playlists import parse_playlist_file, playlist_title_from_location
from kagestream.deps.discovery import (
    find_tool,
    find_javascript_runtime,
    get_tool_version,
    version_tuple,
    is_newer_version,
    get_latest_streamlink_version,
    get_latest_ytdlp_version,
    get_streamlink_installed_version,
    get_ffmpeg_installed_version,
    get_ytdlp_installed_version,
)
from kagestream.deps.installer import (
    download_ytdlp_binary,
    download_deno_binary,
    download_streamlink_appimage,
    download_ffmpeg_binaries,
    ytdlp_release_asset,
)
from kagestream.media.sources import (
    direct_source_filename,
    is_twitch_url,
    probe_direct_source,
    streamlink_can_handle_url,
    streamlink_codec_args,
    streamlink_header_args,
)
from kagestream.media.ytdlp import analyze_url as ytdlp_analyze_url
from kagestream.media.ytdlp import (
    analysis_error_message,
    cookie_retry_candidates,
    is_bot_check_error,
    is_replay_site_url,
    replay_site_label,
    youtube_cookie_args,
)
from kagestream.media.process import (
    escalate_process_stop as escalate_process_stop_impl,
    wait_file_closed as wait_file_closed_impl,
)
from kagestream.download.manager import DownloadManager
from kagestream.capture.manager import CaptureManager
from kagestream.ui.music_page import build_music_page
from kagestream.ui.downloads_page import build_downloads_page
from kagestream.ui.captures_page import build_captures_page




class LinkLogicMixin:
    def is_twitch_url(self, url):
        return is_twitch_url(url)

    def on_stream_url_changed(self, entry):
        version_supported = (
            not self.streamlink_version
            or version_tuple(self.streamlink_version) >= (8, 0)
        )
        enabled = self.is_twitch_url(entry.get_text().strip()) and version_supported
        self.twitch_codec_preference.set_sensitive(enabled)
        self.twitch_codec_label.set_sensitive(enabled)

    def streamlink_codec_args(self, url, preference=None):
        preference = preference or self.twitch_codec_preference.get_active_id() or "h264"
        return streamlink_codec_args(url, preference, self.streamlink_version)

    def streamlink_header_args(self, url):
        return streamlink_header_args(url)

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

    def streamlink_can_handle_url(self, url):
        return streamlink_can_handle_url(self.streamlink, url)

    def probe_direct_source(self, url):
        return probe_direct_source(
            self.ffmpeg, self.ffprobe, url, log_callback=self.log_text
        )

    def direct_source_filename(self, url):
        return direct_source_filename(url)

    def set_direct_quality(self):
        self.quality.remove_all()
        self.quality.append_text("source")
        self.quality.set_active(0)
        return False

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

    def is_dailymotion_url(self, url):
        try:
            host = (urlparse(url).hostname or "").lower()
            return (
                host == "dailymotion.com"
                or host.endswith(".dailymotion.com")
                or host == "dai.ly"
                or host.endswith(".dai.ly")
            )
        except Exception:
            return False

    def source_site_label(self, url):
        if self.is_youtube_url(url):
            return "YouTube"
        if self.is_dailymotion_url(url):
            return "Dailymotion"
        replay = replay_site_label(url)
        if replay:
            return replay
        return "média"

    def should_use_ytdlp(self, url, source_mode):
        # Les sites de replay (Arte, france.tv, RTS…) passent par yt-dlp même
        # depuis la page de capture : c'est le seul moteur qui sait les
        # télécharger proprement.
        if is_replay_site_url(url):
            return True
        if source_mode == "classic":
            return False
        if source_mode in ("youtube_video", "youtube_playlist", "youtube_live", "youtube_live_start"):
            return True
        return self.is_youtube_url(url) or self.is_dailymotion_url(url)

    def adopt_url_on_youtube_page(self, url):
        """Reprend une URL collée sur la page de capture dans la page YouTube,
        qui exécute le téléchargement yt-dlp (sites de replay). Appelable
        depuis le thread GTK ou via GLib.idle_add."""
        if not self.youtube_url_entry.get_text().strip():
            self.youtube_url_entry.set_text(url)
        self.stack.set_visible_child_name("youtube")
        return False

    def analyze_youtube(self, url):
        return ytdlp_analyze_url(
            self.ytdlp,
            url,
            self.javascript_runtime_name,
            self.javascript_runtime_path,
            log_callback=self.log_text,
            cookies_browser=self.youtube_cookies_browser,
            browser_callback=self.force_youtube_browser,
        )

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
            title, message = analysis_error_message(error)
            self.set_status(title + ".")
            GLib.idle_add(
                self.show_message,
                title,
                message,
                Gtk.MessageType.ERROR
            )
            return

        is_youtube = self.is_youtube_url(url)
        site = self.source_site_label(url)

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
        self.log_text(f"Tags : {', '.join(str(tag) for tag in tags) if tags else 'aucun'}")

        if is_youtube and not self.javascript_runtime_path:
            self.log_text(
                "⚠️ Aucun moteur JavaScript détecté : certaines qualités YouTube peuvent manquer."
            )

        kind = f"Live {site}" if live_status in ("is_live", "is_upcoming") else f"Vidéo {site}"
        summary = (
            f"{kind} reconnue.\n\n"
            f"Titre : {data.get('title', 'Inconnu')}\n"
            f"Chaîne : {uploader}\n"
            f"Meilleure résolution : {str(max_height) + 'p' if max_height else 'inconnue'}\n"
            f"Sous-titres manuels : {manual_count}\n"
            f"Sous-titres automatiques : {automatic_count}\n"
            f"Tags : {len(tags)}"
        )

        if is_youtube and not self.javascript_runtime_path:
            summary += (
                "\n\nAttention : Deno ou Node n’est pas détecté. "
                "KageStream bloquera le téléchargement pour éviter une qualité limitée."
            )

        self.set_status(f"{kind} reconnue.")
        GLib.idle_add(
            self.show_message,
            f"{kind} reconnue",
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

        # Chaque page a son propre bouton de test : désactiver le bon.
        if context == "stream" and hasattr(self, "capture_test_button"):
            self.capture_test_button.set_sensitive(False)
        else:
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
                if context == "stream":
                    # Site de replay collé sur la page de capture : l'analyse
                    # et le téléchargement yt-dlp vivent sur la page YouTube.
                    GLib.idle_add(self.adopt_url_on_youtube_page, url)
                self.test_youtube_link(url)
                return

            if self.streamlink_can_handle_url(url):
                cmd = [self.streamlink]
                cmd.extend(self.streamlink_header_args(url))
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
