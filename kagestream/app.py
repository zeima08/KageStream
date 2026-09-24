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
from kagestream.media.process import (
    escalate_process_stop as escalate_process_stop_impl,
    wait_file_closed as wait_file_closed_impl,
)
from kagestream.download.manager import DownloadManager
from kagestream.capture.manager import CaptureManager
from kagestream.ui.sidebar import build_sidebar
from kagestream.ui.music_page import build_music_page
from kagestream.ui.downloads_page import build_downloads_page
from kagestream.ui.captures_page import build_captures_page


class KageStreamWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_TITLE)

        self.set_default_size(1200, 860)
        if os.path.isfile(ICON_PATH):
            self.set_icon_from_file(ICON_PATH)

        self.process = None
        self.user_stopped = False
        self.recording_start = None
        self.current_ts_file = None
        self.final_file = None
        self.stats_timer_id = None
        self.active_backend = None
        self.active_source_label = "YouTube"
        self.youtube_progress = ""
        self.youtube_auto_only_codes = set()
        self.javascript_runtime_name = None
        self.javascript_runtime_path = None
        self.local_playlist_files = []
        self.ytdlp_installing = False
        self.dependency_installing = False

        self.stream_health = "Non analysé"
        self.last_health_report = "Aucun enregistrement analysé."

        self.streamlink = None
        self.streamlink_version = ""
        self.streamlink_version_path = None
        self.ffmpeg = None
        self.ffprobe = None
        self.ytdlp = None
        self.aria2c = None

        self.download_manager = DownloadManager(self)
        self.capture_manager = CaptureManager(self)

        self.build_ui()
        self.check_dependencies(silent=True)
        self.log_startup()
        self.refresh_local_playlist_files(log_result=True)
        self.update_clocks()
        GLib.timeout_add(1000, self.update_clocks)

    # ------------------------------------------------------------------
    # Construction de l'interface : barre latérale + Gtk.Stack
    # ------------------------------------------------------------------
    def build_ui(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add(outer)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)

        sidebar = build_sidebar(self.stack)
        outer.pack_start(sidebar, False, False, 0)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main.set_margin_top(14)
        main.set_margin_bottom(14)
        main.set_margin_start(14)
        main.set_margin_end(14)
        outer.pack_start(main, True, True, 0)

        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{APP_TITLE}</b>")
        main.pack_start(title, False, False, 0)

        self.status = Gtk.Label(label="Prêt.", xalign=0)
        main.pack_start(self.status, False, False, 0)

        clocks_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.clock_local_label = Gtk.Label(label="Heure locale : --:--:--", xalign=0)
        self.clock_tokyo_label = Gtk.Label(label="Heure Tokyo : --:--:--", xalign=0)
        clocks_box.pack_start(self.clock_local_label, False, False, 0)
        clocks_box.pack_start(self.clock_tokyo_label, False, False, 0)
        main.pack_start(clocks_box, False, False, 0)

        main.pack_start(self.stack, True, True, 0)

        self.build_capture_page()
        self.stack.add_titled(
            build_captures_page(self),
            "captures",
            "Captures"
        )
        self.build_youtube_page()
        self.stack.add_titled(
            build_music_page(self),
            "music",
            "Musique"
        )
        self.stack.add_titled(
            build_downloads_page(self),
            "downloads",
            "Téléchargements"
        )
        self.build_tools_pages()

        # Barre d'action contextuelle (Capturer / YouTube uniquement)
        self.action_bar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        main.pack_start(self.action_bar_box, False, False, 0)

        buttons = Gtk.Box(spacing=8)
        self.action_bar_box.pack_start(buttons, False, False, 0)

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
        self.action_bar_box.pack_start(self.stats, False, False, 0)

        self.health_label = Gtk.Label(label="Santé du stream : non analysé", xalign=0)
        self.action_bar_box.pack_start(self.health_label, False, False, 0)

        self.on_stream_profile_changed(self.stream_profile)
        self.stack.connect("notify::visible-child-name", self.on_page_changed)
        self.stack.set_visible_child_name("capture")
        self.on_page_changed(self.stack, None)

    def build_capture_page(self):
        stream_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        stream_page.set_border_width(12)

        stream_intro = Gtk.Label(
            label=(
                "Twitch, IPTV, HLS, MPEG-TS et autres sources compatibles Streamlink ou FFmpeg. "
                "Chaque clic sur « Enregistrer » démarre une nouvelle capture sans arrêter les "
                "autres — suis-les toutes dans l’onglet « Captures »."
            ),
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

        schedule_frame = Gtk.Frame(label="Programmation d’un enregistrement")
        schedule_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        schedule_box.set_border_width(10)
        schedule_frame.add(schedule_box)

        schedule_grid = Gtk.Grid(column_spacing=14, row_spacing=8)
        schedule_box.pack_start(schedule_grid, False, False, 0)

        self.schedule_start_entry = Gtk.Entry()
        self.schedule_start_entry.set_placeholder_text("HH:MM ou HH:MM:SS")

        self.schedule_end_entry = Gtk.Entry()
        self.schedule_end_entry.set_placeholder_text("HH:MM ou HH:MM:SS")

        schedule_grid.attach(Gtk.Label(label="Heure de début", xalign=0), 0, 0, 1, 1)
        schedule_grid.attach(self.schedule_start_entry, 1, 0, 1, 1)
        schedule_grid.attach(Gtk.Label(label="Heure de fin", xalign=0), 0, 1, 1, 1)
        schedule_grid.attach(self.schedule_end_entry, 1, 1, 1, 1)

        self.schedule_button = Gtk.Button(label="Programmer")
        self.schedule_button.connect("clicked", self.schedule_button_clicked)
        schedule_box.pack_start(self.schedule_button, False, False, 0)

        self.schedule_status_label = Gtk.Label(
            label="Chaque programmation apparaît dans l’onglet « Captures » — plusieurs "
                  "programmations et captures peuvent tourner en même temps.",
            xalign=0
        )
        self.schedule_status_label.set_line_wrap(True)
        schedule_box.pack_start(self.schedule_status_label, False, False, 0)

        stream_page.pack_start(schedule_frame, False, False, 0)

        playlists_frame = Gtk.Frame(label="Listes M3U, M3U8 et XSPF locales")
        playlists_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        playlists_box.set_border_width(10)
        playlists_frame.add(playlists_box)

        self.playlist_summary_label = Gtk.Label(
            label="KageStream recherche les listes placées à côté de l’AppImage ou du script.",
            xalign=0
        )
        self.playlist_summary_label.set_line_wrap(True)
        playlists_box.pack_start(self.playlist_summary_label, False, False, 0)

        playlists_buttons = Gtk.Box(spacing=8)
        playlists_box.pack_start(playlists_buttons, False, False, 0)

        self.playlist_button = Gtk.Button(label="Ouvrir les listes locales")
        self.playlist_button.connect("clicked", self.show_local_playlists)
        playlists_buttons.pack_start(self.playlist_button, True, True, 0)

        playlist_refresh_button = Gtk.Button(label="Actualiser la détection")
        playlist_refresh_button.connect(
            "clicked", lambda *_args: self.refresh_local_playlist_files(log_result=True)
        )
        playlists_buttons.pack_start(playlist_refresh_button, True, True, 0)

        stream_page.pack_start(playlists_frame, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(stream_page)
        self.stack.add_titled(scroller, "capture", "Capturer")

    def build_youtube_page(self):
        youtube_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        youtube_page.set_border_width(12)

        youtube_intro = Gtk.Label(
            label="Vidéos, playlists, premières et lives YouTube et Dailymotion avec yt-dlp.",
            xalign=0
        )
        youtube_page.pack_start(youtube_intro, False, False, 0)

        self.youtube_url_entry = Gtk.Entry()
        self.youtube_url_entry.set_placeholder_text("Colle un lien YouTube ou Dailymotion...")
        self.youtube_url_entry.connect("changed", lambda _entry: self.refresh_action_buttons())
        youtube_page.pack_start(self.youtube_url_entry, False, False, 0)

        youtube_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        youtube_grid.set_margin_top(8)
        youtube_grid.set_margin_bottom(4)
        youtube_grid.set_margin_start(8)
        youtube_grid.set_margin_end(8)
        youtube_page.pack_start(youtube_grid, False, False, 0)

        self.source_mode = Gtk.ComboBoxText()
        self.source_mode.append("youtube_video", "Télécharger une vidéo (YouTube / Dailymotion)")
        self.source_mode.append("youtube_playlist", "Télécharger une playlist complète (YouTube / Dailymotion)")
        self.source_mode.append("youtube_live", "Live YouTube ou Dailymotion — à partir de maintenant")
        self.source_mode.append("youtube_live_start", "Live YouTube ou Dailymotion — depuis le début (expérimental)")
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
            title="Choisir le dossier de téléchargement",
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
                "« Meilleure disponible » choisit la plus grande vidéo et le meilleur audio. "
                "Le mode playlist télécharge toutes les vidéos de la playlist collée."
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

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(youtube_page)
        self.stack.add_titled(scroller, "youtube", "YouTube / Dailymotion")

    def build_tools_pages(self):
        deps_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        deps_page.set_border_width(18)

        deps_title = Gtk.Label(xalign=0)
        deps_title.set_markup("<b>Dépendances</b>")
        deps_page.pack_start(deps_title, False, False, 0)

        deps_help = Gtk.Label(
            label=(
                "Contrôle les versions détectées ou installe directement yt-dlp, Deno, "
                "Streamlink, FFmpeg et FFprobe sans pacman."
            ),
            xalign=0
        )
        deps_help.set_line_wrap(True)
        deps_page.pack_start(deps_help, False, False, 0)

        self.update_button = Gtk.Button(label="Dépendances et mises à jour")
        self.update_button.connect("clicked", self.show_update_checker)
        deps_page.pack_start(self.update_button, False, False, 0)

        self.stack.add_titled(deps_page, "tools_deps", "Dépendances")

        diag_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        diag_page.set_border_width(18)

        diag_title = Gtk.Label(xalign=0)
        diag_title.set_markup("<b>Diagnostic</b>")
        diag_page.pack_start(diag_title, False, False, 0)

        diag_help = Gtk.Label(
            label="Résumé des outils détectés (Streamlink, FFmpeg, FFprobe, yt-dlp, moteur JavaScript).",
            xalign=0
        )
        diag_help.set_line_wrap(True)
        diag_page.pack_start(diag_help, False, False, 0)

        self.diagnostic_button = Gtk.Button(label="Ouvrir le diagnostic")
        self.diagnostic_button.connect("clicked", self.show_diagnostic)
        diag_page.pack_start(self.diagnostic_button, False, False, 0)

        self.stack.add_titled(diag_page, "tools_diag", "Diagnostic")

        logs_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        logs_page.set_border_width(18)

        logs_title = Gtk.Label(xalign=0)
        logs_title.set_markup("<b>Journal technique</b>")
        logs_page.pack_start(logs_title, False, False, 0)

        self.log = Gtk.TextView()
        self.log.set_editable(False)
        self.log.set_monospace(True)

        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_hexpand(True)
        log_scroll.set_vexpand(True)
        log_scroll.add(self.log)
        logs_page.pack_start(log_scroll, True, True, 0)

        self.stack.add_titled(logs_page, "tools_logs", "Logs")

    def on_page_changed(self, stack, _param):
        page_name = stack.get_visible_child_name()

        if not hasattr(self, "test_button"):
            return

        if page_name == "capture":
            self.action_bar_box.set_visible(True)
            self.test_button.set_label("Tester le flux")
            self.start_button.set_label("▶ Enregistrer le flux")
            # Plusieurs captures peuvent tourner en même temps : leur statut,
            # santé et arrêt individuel vivent désormais dans l'onglet
            # Captures, pas dans cette barre d'action partagée.
            self.stop_button.hide()
            self.open_folder_button.hide()
            self.stats.hide()
            self.health_label.hide()
        elif page_name == "youtube":
            self.action_bar_box.set_visible(True)
            self.test_button.set_label("Analyser le lien")
            self.start_button.set_label("▶ Télécharger / enregistrer")
            self.stop_button.show()
            self.open_folder_button.show()
            self.stats.show()
            self.health_label.show()
        else:
            self.action_bar_box.set_visible(False)

        self.refresh_action_buttons()

    def active_context(self):
        page_name = self.stack.get_visible_child_name() if hasattr(self, "stack") else None
        if page_name == "youtube":
            return "youtube"
        if page_name == "capture":
            return "stream"
        return "other"

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
            url = self.youtube_url_entry.get_text().strip()
            js_runtime_needed = self.is_youtube_url(url) or not url
            self.test_button.set_sensitive(bool(self.ytdlp))
            self.start_button.set_sensitive(
                bool(self.ytdlp and self.ffmpeg)
                and (self.javascript_runtime_path or not js_runtime_needed)
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

    def streamlink_header_args(self, url):
        # Certains fournisseurs IPTV (flux DASH/HLS génériques) filtrent le
        # user-agent par défaut de Streamlink et répondent 403. On laisse
        # Twitch inchangé : son propre user-agent est déjà celui qui marche
        # pour récupérer les jetons d’accès.
        if self.is_twitch_url(url):
            return []
        return [
            "--http-header", f"User-Agent={DIRECT_STREAM_USER_AGENT}",
            "--http-header", "Accept=*/*",
        ]

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
        self.aria2c = find_tool("aria2c")
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

        is_http_url = url.lower().startswith(("http://", "https://"))

        if self.ffprobe:
            cmd = [
                self.ffprobe,
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
                url
            ])

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

        cmd = [
            self.ffmpeg,
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
            "-"
        ])

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
        dialog.add_button("Programmer", Gtk.ResponseType.APPLY)
        dialog.add_button("Enregistrer maintenant", Gtk.ResponseType.OK)
        dialog.set_default_size(1000, 660)
        dialog.set_response_sensitive(Gtk.ResponseType.OK, False)
        dialog.set_response_sensitive(Gtk.ResponseType.APPLY, False)

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

        schedule_start_entry = Gtk.Entry()
        schedule_start_entry.set_placeholder_text("HH:MM ou HH:MM:SS — pour Programmer")

        schedule_end_entry = Gtk.Entry()
        schedule_end_entry.set_placeholder_text("HH:MM ou HH:MM:SS — pour Programmer")

        controls.attach(Gtk.Label(label="Liste", xalign=0), 0, 0, 1, 1)
        controls.attach(playlist_selector, 1, 0, 1, 1)
        controls.attach(Gtk.Label(label="Format", xalign=0), 2, 0, 1, 1)
        controls.attach(format_selector, 3, 0, 1, 1)
        controls.attach(refresh_button, 4, 0, 1, 1)
        controls.attach(search_entry, 0, 1, 5, 1)
        controls.attach(Gtk.Label(label="Début programmé", xalign=0), 0, 2, 1, 1)
        controls.attach(schedule_start_entry, 1, 2, 1, 1)
        controls.attach(Gtk.Label(label="Fin programmée", xalign=0), 2, 2, 1, 1)
        controls.attach(schedule_end_entry, 3, 2, 1, 1)

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
            has_selection = tree_iter is not None and not bool(self.process)
            dialog.set_response_sensitive(Gtk.ResponseType.OK, has_selection)
            dialog.set_response_sensitive(Gtk.ResponseType.APPLY, has_selection)

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
        schedule_start_text = schedule_start_entry.get_text().strip()
        schedule_end_text = schedule_end_entry.get_text().strip()

        if response in (Gtk.ResponseType.OK, Gtk.ResponseType.APPLY):
            selected_model, tree_iter = selection.get_selected()
            if tree_iter is not None:
                selected_item = {
                    "title": selected_model[tree_iter][0],
                    "url": selected_model[tree_iter][3],
                }

        dialog.destroy()

        if not selected_item:
            return

        self.stack.set_visible_child_name("capture")
        self.url_entry.set_text(selected_item["url"])
        self.filename.set_text(sanitize_filename(selected_item["title"]))
        self.stream_profile.set_active_id("copy")
        self.output_format.set_active_id(selected_format)

        if response == Gtk.ResponseType.APPLY:
            self.schedule_start_entry.set_text(schedule_start_text)
            self.schedule_end_entry.set_text(schedule_end_text)
            self.schedule_button_clicked(self.schedule_button)
        else:
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
        return "média"

    def should_use_ytdlp(self, url, source_mode):
        if source_mode == "classic":
            return False
        if source_mode in ("youtube_video", "youtube_playlist", "youtube_live", "youtube_live_start"):
            return True
        return self.is_youtube_url(url) or self.is_dailymotion_url(url)

    def analyze_youtube(self, url):
        return ytdlp_analyze_url(
            self.ytdlp,
            url,
            self.javascript_runtime_name,
            self.javascript_runtime_path,
            log_callback=self.log_text,
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
            self.set_status("Lien non reconnu.")
            GLib.idle_add(
                self.show_message,
                "Lien non reconnu",
                error or "yt-dlp n’a pas réussi à analyser ce lien.",
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
        if is_playlist:
            # Un nom fixe écraserait chaque piste de la playlist : on préfixe
            # toujours par l'index pour garder un fichier par vidéo.
            return os.path.join(folder, "%(playlist_index)03d - %(title).120s [%(id)s].%(ext)s")

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

        is_playlist = config["source_mode"] == "youtube_playlist"

        cmd = [
            self.ytdlp,
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
            "--output", self.youtube_output_template(folder, config["filename"], is_playlist),
            "--print", "after_move:KAGESTREAM_FINAL:%(filepath)s",
        ]

        if self.javascript_runtime_name and self.javascript_runtime_path:
            cmd.extend([
                "--js-runtimes",
                f"{self.javascript_runtime_name}:{self.javascript_runtime_path}"
            ])

        if self.ffmpeg:
            cmd.extend(["--ffmpeg-location", os.path.dirname(self.ffmpeg)])

        if self.aria2c:
            cmd.extend([
                "--external-downloader", self.aria2c,
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

    def youtube_worker(self, url, folder, config):
        started_at = time.time()
        cmd = self.build_ytdlp_command(url, folder, config)

        self.log_text("")
        self.log_text("Commande yt-dlp :")
        self.log_text(" ".join(cmd))
        self.recording_start = started_at
        self.set_status(f"{self.active_source_label} — préparation du téléchargement...")

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
                creationflags=creationflags,
                start_new_session=(sys.platform != "win32"),
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

    def update_clocks(self):
        now_local = datetime.now().astimezone()
        self.clock_local_label.set_text(f"Heure locale : {now_local.strftime('%H:%M:%S')}")
        try:
            now_tokyo = datetime.now(ZoneInfo("Asia/Tokyo"))
            self.clock_tokyo_label.set_text(f"Heure Tokyo : {now_tokyo.strftime('%H:%M:%S')}")
        except Exception as e:
            self.clock_tokyo_label.set_text("Heure Tokyo : indisponible")
            self.log_text(f"[INFO] Horloge Tokyo indisponible : {e}")
        return True

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
        text = f"Santé du stream : {state}"
        if message:
            text += f" — {message}"
        GLib.idle_add(self.health_label.set_text, text)

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
            self.stats.set_text(f"Durée : {h:02d}:{m:02d}:{s:02d} — {self.active_source_label} : {progress}")
        else:
            self.stats.set_text(f"Durée : {h:02d}:{m:02d}:{s:02d} — Taille : {size_mb:.1f} Mo")

        if self.process:
            return True

        self.recording_start = None
        self.stats_timer_id = None
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
                "aria2c (optionnel)",
                self.aria2c or "Non détecté",
                "Paquet officiel de la distribution",
                "Accélère les téléchargements yt-dlp s’il est présent dans le PATH"
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
                "par le système ou par l’AppImage KageStream. aria2c est optionnel : aucun binaire "
                "autonome officiel n’étant publié pour Linux, installe-le via le gestionnaire de "
                "paquets de ta distribution — par exemple « sudo pacman -S aria2 » sous Arch, "
                "« sudo apt install aria2 » sous Debian/Ubuntu ou « sudo dnf install aria2 » sous "
                "Fedora — KageStream le détectera automatiquement une fois installé."
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
        self.log_text(f"aria2c : {'OK — ' + self.aria2c if self.aria2c else 'optionnel, non détecté'}")
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
                (
                    "aria2c (optionnel)",
                    "🟢" if self.aria2c else "🟡",
                    get_tool_version(self.aria2c, ["--version"]) if self.aria2c else "Non détecté — installable via pacman/apt/dnf"
                ),
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
