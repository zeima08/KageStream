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
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, GLib, Gdk

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
from kagestream.download.manager import DownloadManager
from kagestream.capture.manager import CaptureManager
from kagestream.ui.sidebar import Sidebar
from kagestream.ui.theme import load_theme
from kagestream.ui.music_page import build_music_page
from kagestream.ui.downloads_page import build_downloads_page
from kagestream.ui.captures_page import build_captures_page
from kagestream.ui.page_capture import CapturePageMixin
from kagestream.ui.page_youtube import YoutubePageMixin
from kagestream.ui.page_tools import ToolsPageMixin
from kagestream.ui.page_playlists import PlaylistsPageMixin
from kagestream.ui.logic_links import LinkLogicMixin
from kagestream.ui.logic_youtube import YoutubeJobMixin
from kagestream.ui.logic_capture import CaptureLogicMixin
from kagestream.ui.logic_dependencies import DependenciesLogicMixin


class KageStreamWindow(
    CapturePageMixin,
    YoutubePageMixin,
    ToolsPageMixin,
    PlaylistsPageMixin,
    LinkLogicMixin,
    YoutubeJobMixin,
    CaptureLogicMixin,
    DependenciesLogicMixin,
    Gtk.Window,
):
    def __init__(self):
        super().__init__(title=APP_TITLE)

        load_theme()

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
        self.youtube_cookies_browser = None

        self.download_manager = DownloadManager(self.download_tools)
        self.capture_manager = CaptureManager(self.capture_tools, self.log_text)

        self.build_ui()
        self.check_dependencies(silent=True)
        self.log_startup()
        self.refresh_local_playlist_files(log_result=True)
        self.update_clocks()
        GLib.timeout_add(1000, self.update_clocks)
        self.connect("destroy", self._on_destroy)

    def _on_destroy(self, *_args):
        self.shutdown()
        Gtk.main_quit()

    def shutdown(self):
        """Arrête tous les sous-processus restants avant de quitter : les
        enregistrements, téléchargements et finalisations tournent dans des
        groupes de processus dédiés qui survivraient à la fenêtre fermée et
        continueraient d'écrire leurs fichiers en arrière-plan."""
        try:
            self.capture_manager.shutdown()
        except Exception as e:
            self.log_text(f"[INFO] Erreur à l’arrêt des captures : {e}")

        try:
            self.download_manager.shutdown()
        except Exception as e:
            self.log_text(f"[INFO] Erreur à l’arrêt des téléchargements : {e}")

        if self.process is not None:
            try:
                self.user_stopped = True
                escalate_process_stop_impl(self.process, log_callback=self.log_text)
            except Exception:
                pass
            self.process = None

    def build_ui(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add(outer)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)

        self.setup_header_bar()

        self.sidebar = Sidebar(self, self.stack)
        outer.pack_start(self.sidebar.widget, False, False, 0)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.pack_start(main, True, True, 0)
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

        self.on_stream_profile_changed(self.stream_profile)
        self.install_shortcuts()
        self.stack.connect("notify::visible-child-name", self.on_page_changed)
        self.stack.set_visible_child_name("capture")
        self.on_page_changed(self.stack, None)

    def setup_header_bar(self):
        """Barre de titre native : identité et statut à gauche, horloges
        compactes à droite. Remplace les trois lignes d'en-tête permanentes
        (titre, statut, deux horloges) qui amputevaient le stack."""
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title(APP_TITLE)

        identity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        name = Gtk.Label(xalign=0.5)
        name.set_markup(f"<b>{APP_TITLE}</b>")
        self.status = Gtk.Label(label="Prêt.", xalign=0.5)
        self.status.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self.status.set_max_width_chars(60)
        self.status.get_style_context().add_class("muted")
        identity.pack_start(name, False, False, 0)
        identity.pack_start(self.status, False, False, 0)
        header.set_custom_title(identity)

        clocks = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.clock_local_label = Gtk.Label(label="--:--:--")
        self.clock_tokyo_label = Gtk.Label(label="Tokyo --:--:--")
        self.clock_local_label.get_style_context().add_class("muted")
        self.clock_tokyo_label.get_style_context().add_class("muted")
        self.clock_local_label.set_tooltip_text("Heure locale")
        self.clock_tokyo_label.set_tooltip_text("Heure de Tokyo")
        clocks.pack_start(self.clock_local_label, False, False, 0)
        clocks.pack_start(self.clock_tokyo_label, False, False, 0)
        header.pack_end(clocks)

        self.set_titlebar(header)

    def install_shortcuts(self):
        """Ctrl+1 à Ctrl+6 pour atteindre les sections sans la souris."""
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)
        self.accel_group = accel

        for index, page_name in enumerate(
            ("capture", "captures", "music", "youtube", "downloads", "tools_deps"),
            start=1,
        ):
            keyval = getattr(Gdk, f"KEY_{index}")
            accel.connect(
                keyval, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE,
                lambda _group, _accel, _keyval, _mods, name=page_name:
                    self.switch_page(name),
            )

    def switch_page(self, page_name):
        """Affiche une page du stack — cible des raccourcis clavier."""
        if self.stack.get_child_by_name(page_name) is not None:
            self.stack.set_visible_child_name(page_name)
        return False

    def on_page_changed(self, stack, _param):
        # Les actions vivent désormais dans chaque page : il ne reste ici que
        # l'état des boutons selon la page affichée.
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
        # Deux jeux de boutons distincts : la page Capturer démarre une
        # capture, la page YouTube lance un téléchargement.
        capture_buttons = ("capture_test_button", "capture_start_button")
        youtube_buttons = ("test_button", "start_button")
        existing = [name for name in capture_buttons + youtube_buttons + ("stop_button",)
                    if hasattr(self, name)]
        if not existing:
            return False

        if self.process:
            for name in existing:
                widget = getattr(self, name)
                widget.set_sensitive(name == "stop_button")
            return False

        available = bool(self.streamlink or self.ffmpeg)
        for name in capture_buttons:
            if hasattr(self, name):
                getattr(self, name).set_sensitive(available)

        url = self.youtube_url_entry.get_text().strip()
        js_runtime_needed = self.is_youtube_url(url) or not url
        if hasattr(self, "test_button"):
            self.test_button.set_sensitive(bool(self.ytdlp))
        if hasattr(self, "start_button"):
            self.start_button.set_sensitive(
                bool(self.ytdlp and self.ffmpeg)
                and (self.javascript_runtime_path or not js_runtime_needed)
            )

        if hasattr(self, "stop_button"):
            self.stop_button.set_sensitive(False)
        return False

    def set_recording_controls(self, recording):
        for name in ("test_button", "start_button", "capture_test_button",
                     "capture_start_button"):
            if hasattr(self, name):
                getattr(self, name).set_sensitive(not recording)
        if hasattr(self, "stop_button"):
            self.stop_button.set_sensitive(recording)
        if not recording:
            self.refresh_action_buttons()

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
            self._trim_log_buffer(buffer)
            return False
        GLib.idle_add(append)

    def _trim_log_buffer(self, buffer):
        """Garde le journal borné : un téléchargement de plusieurs heures en
        mode --newline produit des milliers de lignes, et un Gtk.TextBuffer
        sans limite ralentit l'interface au fil de la session."""
        line_count = buffer.get_line_count()
        if line_count <= MAX_LOG_LINES:
            return
        start = buffer.get_start_iter()
        cut = buffer.get_iter_at_line(line_count - MAX_LOG_LINES)
        buffer.delete(start, cut)

    def set_status(self, text):
        GLib.idle_add(self.status.set_text, text)

    def update_clocks(self):
        now_local = datetime.now().astimezone()
        self.clock_local_label.set_text(now_local.strftime("%H:%M:%S"))
        try:
            now_tokyo = datetime.now(ZoneInfo("Asia/Tokyo"))
            self.clock_tokyo_label.set_text(f"Tokyo {now_tokyo.strftime('%H:%M:%S')}")
        except Exception as e:
            self.clock_tokyo_label.set_text("Heure Tokyo : indisponible")
            self.log_text(f"[INFO] Horloge Tokyo indisponible : {e}")
        return True

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
