"""Lancement, suivi et arrêt des captures, programmation horaire."""

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
from kagestream.media.sources import SourceTools
from kagestream.download.manager import DownloadManager, DownloadTools
from kagestream.capture.manager import CaptureManager
from kagestream.ui.music_page import build_music_page
from kagestream.ui.downloads_page import build_downloads_page
from kagestream.ui.captures_page import build_captures_page




class CaptureLogicMixin:
    def capture_tools(self):
        """Contexte d'outils fourni au CaptureManager — aucun widget GTK n'y
        transite, et les chemins sont relus à chaque appel après une
        installation de dépendance."""
        return SourceTools(
            streamlink=self.streamlink,
            ffmpeg=self.ffmpeg,
            ffprobe=self.ffprobe,
            streamlink_version=self.streamlink_version,
            log_callback=self.log_text,
        )

    def download_tools(self):
        return DownloadTools(
            ytdlp=self.ytdlp,
            ffmpeg=self.ffmpeg,
            aria2c=self.aria2c,
            javascript_runtime_name=self.javascript_runtime_name,
            javascript_runtime_path=self.javascript_runtime_path,
            cookies_browser=self.youtube_cookies_browser,
            log_callback=self.log_text,
            browser_forcer=self.force_youtube_browser,
        )

    def schedule_button_clicked(self, button):
        url = self.url_entry.get_text().strip()
        if not url:
            self.show_message(
                "Lien manquant",
                "Colle un lien Streamlink, IPTV ou FFmpeg avant de programmer l’enregistrement.",
                Gtk.MessageType.WARNING
            )
            return

        start_time = self.parse_time_of_day(self.schedule_start_entry.get_text())
        end_time = self.parse_time_of_day(self.schedule_end_entry.get_text())

        if not start_time or not end_time:
            self.show_message(
                "Heures invalides",
                "Utilise le format HH:MM ou HH:MM:SS pour l’heure de début et l’heure de fin.",
                Gtk.MessageType.ERROR
            )
            return

        now = datetime.now()
        start_at = self.next_occurrence(start_time, now)
        end_at = self.next_occurrence(end_time, start_at)

        quality = self.quality.get_active_text() or "best"
        twitch_preference = self.twitch_codec_preference.get_active_id() or "h264"
        profile = self.stream_profile.get_active_id() or "copy"
        fmt = self.current_output_format()
        filename = self.safe_filename("stream")
        folder = self.current_folder()

        self.capture_manager.schedule_capture(
            start_at, end_at, url, quality, twitch_preference, profile, fmt, filename, folder
        )

        self.log_text(f"[INFO] Programmation enregistrée — début {start_at}, fin {end_at}")
        self.show_message(
            "Programmation enregistrée",
            f"Début : {start_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Fin : {end_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "Suis-la depuis l’onglet « Captures » — d’autres captures ou "
            "programmations peuvent être ajoutées sans attendre celle-ci.",
            Gtk.MessageType.INFO
        )

    def start_recording(self, button):
        context = self.active_context()
        if context not in ("stream", "youtube"):
            return

        if context == "stream":
            url = self.url_entry.get_text().strip()
            if is_replay_site_url(url):
                # Les replays ne s'enregistrent pas comme un flux : basculer
                # vers la page YouTube, qui les télécharge avec yt-dlp.
                self.adopt_url_on_youtube_page(url)
                self.show_message(
                    "Replay détecté",
                    "Ce lien se télécharge avec yt-dlp depuis la page YouTube — "
                    "KageStream y a basculé. Relance le test ou le téléchargement "
                    "depuis cette page.",
                    Gtk.MessageType.INFO
                )
                return
            self.start_new_capture()
            return

        url = self.current_url_entry().get_text().strip()

        if not url:
            self.show_message("Lien manquant", "Colle un lien avant de lancer l’enregistrement.", Gtk.MessageType.WARNING)
            return

        self.check_dependencies(silent=True)

        source_mode = self.current_source_mode()

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

        if self.is_youtube_url(url) and not self.javascript_runtime_path:
            self.show_message(
                "Moteur JavaScript introuvable",
                "Deno ou Node est nécessaire pour obtenir toutes les qualités YouTube. "
                "KageStream bloque le téléchargement afin d’éviter une vidéo limitée à 360p. "
                "Utilise l’onglet « Outils » pour installer Deno directement.",
                Gtk.MessageType.ERROR
            )
            return

        self.user_stopped = False
        self.recording_start = time.time()
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

        config = self.get_youtube_config(source_mode)
        self.current_ts_file = None
        self.final_file = folder
        self.active_backend = "yt-dlp"
        self.active_source_label = self.source_site_label(url)
        self.set_status(f"{self.active_source_label} — analyse et préparation...")

        threading.Thread(
            target=self.youtube_worker,
            args=(url, folder, config),
            daemon=True
        ).start()

    def start_new_capture(self):
        url = self.url_entry.get_text().strip()
        if not url:
            self.show_message("Lien manquant", "Colle un lien avant de lancer l’enregistrement.", Gtk.MessageType.WARNING)
            return

        self.check_dependencies(silent=True)

        fmt = self.current_output_format()
        profile = self.stream_profile.get_active_id() or "copy"

        if not self.streamlink and not self.ffmpeg:
            self.show_message(
                "Moteur d’enregistrement introuvable",
                "Ouvre l’onglet « Outils » puis installe Streamlink ou FFmpeg directement.",
                Gtk.MessageType.ERROR
            )
            return

        if (fmt != "ts" or profile != "copy") and not self.ffmpeg:
            self.show_message(
                "FFmpeg introuvable",
                "FFmpeg est nécessaire pour le remux ou la conversion. "
                "Tu peux l’installer depuis l’onglet « Outils ».",
                Gtk.MessageType.ERROR
            )
            return

        quality = self.quality.get_active_text() or "best"
        twitch_preference = self.twitch_codec_preference.get_active_id() or "h264"
        filename = self.safe_filename("stream")
        folder = self.current_folder()

        self.capture_manager.start_capture(
            url, quality, twitch_preference, profile, fmt, filename, folder
        )

        self.url_entry.set_text("")
        self.filename.set_text("")
        self.stack.set_visible_child_name("captures")

    def set_health(self, state, message=None):
        self.stream_health = state
        text = f"Santé : {state}"
        if message:
            text += f" — {message}"
        self._show_transfer_status(True)
        GLib.idle_add(self.health_label.set_text, text)

    def _show_transfer_status(self, visible):
        """Affiche ou masque la ligne durée/taille/santé de la page YouTube —
        elle n'a de sens que pendant un téléchargement."""
        for name in ("stats", "health_label"):
            widget = getattr(self, name, None)
            if widget is None:
                continue
            if visible:
                widget.show()
            else:
                widget.hide()

    def update_stats(self):
        if not self.process and not self.recording_start:
            self.stats_timer_id = None
            self._show_transfer_status(False)
            return False

        elapsed = int(time.time() - self.recording_start) if self.recording_start else 0
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60

        size_mb = 0
        if self.current_ts_file and os.path.exists(self.current_ts_file):
            size_mb = os.path.getsize(self.current_ts_file) / 1024 / 1024

        self._show_transfer_status(True)
        if self.active_backend == "yt-dlp":
            progress = self.youtube_progress or "préparation…"
            self.stats.set_text(f"{h:02d}:{m:02d}:{s:02d} · {progress}")
        else:
            self.stats.set_text(f"{h:02d}:{m:02d}:{s:02d} · {size_mb:.1f} Mo")

        if self.process:
            return True

        self.recording_start = None
        self.stats_timer_id = None
        self._show_transfer_status(False)
        return False

    def stop_recording(self, button):
        if not self.process:
            return

        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Arrêter l’enregistrement ?"
        )
        dialog.format_secondary_text(
            "KageStream demandera à yt-dlp de finaliser proprement le fichier déjà téléchargé."
        )

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            self.log_text("Arrêt demandé par l’utilisateur.")
            self.perform_stop()

    def perform_stop(self):
        if not self.process:
            return

        self.user_stopped = True
        proc = self.process
        ts_file = self.current_ts_file

        threading.Thread(
            target=self._stop_worker,
            args=(proc, ts_file),
            daemon=True
        ).start()

    def _stop_worker(self, proc, ts_file):
        try:
            self.escalate_process_stop(proc)

            if ts_file and os.path.exists(ts_file):
                self.log_text("Vérification de la fermeture du fichier TS...")
                if self.wait_file_closed(ts_file):
                    self.log_text("[INFO] Fichier TS fermé correctement.")
                else:
                    self.log_text("[INFO] Impossible de confirmer la fermeture complète du fichier TS.")
        except Exception as e:
            self.log_text(f"Erreur pendant l’arrêt : {e}")

    def escalate_process_stop(self, proc):
        escalate_process_stop_impl(proc, log_callback=self.log_text)

    def wait_file_closed(self, path):
        return wait_file_closed_impl(path)

    def open_current_folder(self, button):
        target = self.final_file or self.current_ts_file or self.current_folder()
        open_folder(target)

    def parse_time_of_day(self, text):
        text = (text or "").strip()
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(text, fmt).time()
            except ValueError:
                continue
        return None

    def next_occurrence(self, time_of_day, reference):
        candidate = reference.replace(
            hour=time_of_day.hour,
            minute=time_of_day.minute,
            second=time_of_day.second,
            microsecond=0
        )
        if candidate <= reference:
            candidate += timedelta(days=1)
        return candidate
