"""Exécution des téléchargements yt-dlp (commande, sortie, relance cookies)."""

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
from kagestream.media.ytdlp import analyze_url as ytdlp_analyze_url
from kagestream.media.ytdlp_command import (
    YtdlpTools,
    build_ytdlp_command,
    youtube_output_template,
)
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




class YoutubeJobMixin:
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

    def youtube_output_template(self, folder, filename, is_playlist=False):
        return youtube_output_template(folder, filename, is_playlist)

    def build_ytdlp_command(self, url, folder, config, cookies_browser=None):
        return build_ytdlp_command(url, folder, config, self._ytdlp_tools(), cookies_browser)

    def _ytdlp_tools(self):
        return YtdlpTools(
            ytdlp=self.ytdlp,
            ffmpeg=self.ffmpeg,
            aria2c=self.aria2c,
            javascript_runtime_name=self.javascript_runtime_name,
            javascript_runtime_path=self.javascript_runtime_path,
            cookies_browser=self.youtube_cookies_browser,
            auto_only_codes=self.youtube_auto_only_codes,
        )

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
            self.set_status(f"{self.active_source_label} — téléchargement : {percent}")

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

    def _run_ytdlp_with_output(self, cmd):
        """Lance une commande yt-dlp, journalise sa sortie en continu et
        retourne (code de retour, lignes capturées)."""
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
            start_new_session=(sys.platform != "win32"),
        )

        captured = []
        for line in self.process.stdout:
            clean = line.rstrip()
            if not clean:
                continue
            captured.append(clean)
            self.log_text(clean)
            self.inspect_ytdlp_line(clean)

        self.process.wait()
        return self.process.returncode, captured

    def _retry_with_forced_cookies(self, url, captured):
        """Après un blocage anti-robot YouTube, choisit un navigateur détecté
        pour relancer la commande avec ses cookies. Retourne le navigateur
        retenu, ou None s'il n'y a rien à tenter (pas de blocage, cookies déjà
        utilisés, ou aucun navigateur compatible installé)."""
        if not is_bot_check_error("\n".join(captured)):
            return None
        candidates = cookie_retry_candidates(limit=1)
        if not candidates:
            self.log_text(
                "[Cookies] Blocage anti-robot YouTube — aucun navigateur "
                "compatible (Firefox, Chrome, Edge…) n’a été détecté : "
                "effectue la vérification dans ton navigateur puis "
                "sélectionne-le dans « Outils → Dépendances → Session YouTube »."
            )
            return None
        browser = candidates[0]
        if not youtube_cookie_args(url, browser):
            return None
        self.log_text(
            f"[Cookies] Blocage anti-robot YouTube — relance avec les "
            f"cookies de {browser}."
        )
        self.force_youtube_browser(browser)
        return browser

    def youtube_worker(self, url, folder, config):
        started_at = time.time()
        cookies_used = bool(youtube_cookie_args(url, self.youtube_cookies_browser))
        cmd = self.build_ytdlp_command(url, folder, config)

        self.log_text("")
        self.log_text("Commande yt-dlp :")
        self.log_text(" ".join(cmd))
        self.recording_start = started_at
        self.set_status(f"{self.active_source_label} — préparation du téléchargement...")

        try:
            returncode, captured = self._run_ytdlp_with_output(cmd)

            # Blocage anti-robot : forcer les cookies d'un navigateur détecté
            # puis relancer, même si aucune session n'a été choisie dans Outils.
            if (returncode != 0 and not self.user_stopped and not cookies_used):
                forced_browser = self._retry_with_forced_cookies(url, captured)
                if forced_browser:
                    cmd = self.build_ytdlp_command(
                        url, folder, config, cookies_browser=forced_browser
                    )
                    self.log_text("Commande yt-dlp (avec cookies forcés) :")
                    self.log_text(" ".join(cmd))
                    returncode, captured = self._run_ytdlp_with_output(cmd)

            if not self.final_file or not os.path.isfile(self.final_file):
                detected = self.find_recent_youtube_file(folder, started_at)
                if detected:
                    self.final_file = detected

            has_final_file = bool(self.final_file and os.path.isfile(self.final_file))

            if self.user_stopped:
                if has_final_file:
                    self.log_text(f"Live {self.active_source_label} arrêté et conservé : {self.final_file}")
                    self.last_health_report = f"Live {self.active_source_label} arrêté proprement et conservé."
                    self.set_health("partiel conservé", "arrêt demandé par l’utilisateur")
                    GLib.idle_add(
                        self.show_message,
                        f"Enregistrement {self.active_source_label} arrêté",
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
                self.log_text(f"Téléchargement {self.active_source_label} terminé : {self.final_file}")
                self.last_health_report = f"Téléchargement {self.active_source_label} terminé."
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
                    f"Téléchargement {self.active_source_label} impossible",
                    "yt-dlp a rencontré une erreur. Consulte les logs de KageStream.",
                    Gtk.MessageType.ERROR
                )

        except Exception as e:
            self.log_text(f"Erreur yt-dlp : {e}")
            self.last_health_report = f"Erreur yt-dlp : {e}"
            self.set_health("problème détecté", "erreur yt-dlp")
            GLib.idle_add(
                self.show_message,
                f"Erreur {self.active_source_label}",
                str(e),
                Gtk.MessageType.ERROR
            )

        finally:
            self.process = None
            self.active_backend = None
            GLib.idle_add(self.set_recording_controls, False)
            GLib.idle_add(self.open_folder_button.set_sensitive, True)
            self.set_status("Prêt.")
