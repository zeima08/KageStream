"""Pages Outils : Dépendances (dont la session YouTube), Diagnostic, Logs."""

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
from kagestream.download.manager import DownloadManager
from kagestream.capture.manager import CaptureManager
from kagestream.ui.music_page import build_music_page
from kagestream.ui.downloads_page import build_downloads_page
from kagestream.ui.captures_page import build_captures_page
from kagestream.ui.widgets import (
    button,
    muted_label,
    page_container,
    section,
)




class ToolsPageMixin:
    def build_tools_pages(self):
        # --- Dépendances -------------------------------------------------
        outer, content = page_container(
            "Dépendances",
            "Contrôle les versions détectées ou installe directement yt-dlp, Deno, "
            "Streamlink, FFmpeg et FFprobe, sans gestionnaire de paquets.",
        )

        install_card = section("Installation et mises à jour")
        self.update_button = button(
            "Ouvrir les mises à jour", self.show_update_checker, primary=True,
            tooltip="Vérifie les versions disponibles et propose les installations.",
        )
        install_card.pack_start(self.update_button, False, False, 0)
        content.pack_start(install_card, False, False, 0)

        session_card = section("Session YouTube")
        session_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        session_label = Gtk.Label(label="_Navigateur", xalign=0)
        session_label.set_use_underline(True)

        self.youtube_browser_combo = Gtk.ComboBoxText()
        self.youtube_browser_combo.append("none", "Sans cookies (par défaut)")
        for browser, label in (
            ("firefox", "Firefox"), ("chrome", "Chrome"),
            ("chromium", "Chromium"), ("brave", "Brave"),
            ("edge", "Edge"), ("vivaldi", "Vivaldi"), ("opera", "Opera"),
        ):
            self.youtube_browser_combo.append(browser, label)
        self.youtube_browser_combo.set_active_id("none")
        self.youtube_browser_combo.connect("changed", self.on_youtube_browser_changed)
        session_label.set_mnemonic_widget(self.youtube_browser_combo)

        session_row.pack_start(session_label, False, False, 0)
        session_row.pack_start(self.youtube_browser_combo, False, False, 0)
        session_card.pack_start(session_row, False, False, 0)
        session_card.pack_start(
            muted_label(
                "Si YouTube demande une vérification, ouvre la vidéo dans ton navigateur, "
                "effectue la vérification puis sélectionne ce navigateur ici. KageStream lit "
                "ses cookies pour les vidéos, lives et YouTube Music. Ce choix reste actif "
                "jusqu’à la fermeture — et les cookies sont aussi tentés automatiquement "
                "quand YouTube bloque un téléchargement."
            ),
            False, False, 0,
        )
        content.pack_start(session_card, False, False, 0)
        self.stack.add_titled(outer, "tools_deps", "Dépendances")

        # --- Diagnostic --------------------------------------------------
        outer, content = page_container(
            "Diagnostic",
            "Résumé des outils détectés : Streamlink, FFmpeg, FFprobe, yt-dlp et moteur JavaScript.",
        )
        diag_card = section("État de l’installation")
        self.diagnostic_button = button(
            "Ouvrir le diagnostic", self.show_diagnostic, primary=True,
            tooltip="Affiche les versions et le dernier rapport de santé enregistré.",
        )
        diag_card.pack_start(self.diagnostic_button, False, False, 0)
        content.pack_start(diag_card, False, False, 0)
        self.stack.add_titled(outer, "tools_diag", "Diagnostic")

        # --- Journal -----------------------------------------------------
        outer, content = page_container(
            "Journal technique",
            "Commandes exécutées et erreurs détaillées. Limité aux 5 000 dernières lignes.",
            scrollable=False,
        )
        self.log = Gtk.TextView()
        self.log.set_editable(False)
        self.log.set_monospace(True)
        self.log.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)

        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scroll.set_hexpand(True)
        log_scroll.set_vexpand(True)
        log_scroll.add(self.log)
        content.pack_start(log_scroll, True, True, 0)
        self.stack.add_titled(outer, "tools_logs", "Journal")

    def on_youtube_browser_changed(self, combo):
        browser = combo.get_active_id()
        self.youtube_cookies_browser = None if browser == "none" else browser

    def force_youtube_browser(self, browser):
        """Active les cookies YouTube pour les prochaines commandes yt-dlp.
        Appelable depuis un thread d'arrière-plan : l'attribut est posé
        immédiatement, le combo de Outils est mis à jour via idle_add."""
        self.youtube_cookies_browser = browser or None

        def apply_combo():
            combo = getattr(self, "youtube_browser_combo", None)
            if combo is not None:
                combo.set_active_id(browser or "none")
            return False

        GLib.idle_add(apply_combo)
