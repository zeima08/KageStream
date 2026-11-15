"""Page « Capturer » : flux Streamlink, IPTV, HLS et programmation."""

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
    action_bar,
    add_row,
    bind_enter,
    button,
    form_grid,
    muted_label,
    page_container,
    section,
)




class CapturePageMixin:
    def build_capture_page(self):
        outer, content = page_container(
            "Capturer",
            "Twitch, IPTV, HLS, MPEG-TS et autres sources compatibles Streamlink ou FFmpeg.",
        )

        # --- Lien -------------------------------------------------------
        link_card = section("Source")
        self.url_entry = Gtk.Entry()
        self.url_entry.set_placeholder_text("Colle un lien Twitch, IPTV, HLS ou MPEG-TS…")
        self.url_entry.connect("changed", self.on_stream_url_changed)
        bind_enter(self.url_entry, self._capture_enter_pressed)
        link_card.pack_start(self.url_entry, False, False, 0)

        hint = muted_label(
            "Chaque clic sur « Enregistrer » démarre une nouvelle capture sans arrêter "
            "les autres — toutes sont suivies dans Captures."
        )
        link_card.pack_start(hint, False, False, 0)
        content.pack_start(link_card, False, False, 0)

        # --- Format -----------------------------------------------------
        format_card = section("Format")
        stream_grid = form_grid()

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
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        self.folder.set_filename(os.getcwd())

        add_row(stream_grid, 0, "Qualité", self.quality,
                tooltip="Qualité demandée à Streamlink (best par défaut).")
        self.twitch_codec_label = add_row(
            stream_grid, 1, "Codecs Twitch", self.twitch_codec_preference,
            tooltip="Préférence de codec pour Twitch uniquement (Streamlink 8+).",
        )
        add_row(stream_grid, 2, "Traitement final", self.stream_profile)
        add_row(stream_grid, 3, "Conteneur", self.output_format)
        add_row(stream_grid, 4, "Nom du fichier", self.filename)
        add_row(stream_grid, 5, "Dossier", self.folder)

        format_card.pack_start(stream_grid, False, False, 0)
        format_card.pack_start(
            muted_label(
                "La préférence de codec ne concerne que Twitch ; l’IPTV conserve le codec reçu. "
                "Les profils H.264/AAC et AV1/Opus sont convertis après la capture pour protéger "
                "l’enregistrement en direct."
            ),
            False, False, 0,
        )
        content.pack_start(format_card, False, False, 0)

        # --- Programmation ----------------------------------------------
        schedule_card = section("Programmation")
        schedule_grid = form_grid()

        self.schedule_start_entry = Gtk.Entry()
        self.schedule_start_entry.set_placeholder_text("HH:MM ou HH:MM:SS")
        self.schedule_end_entry = Gtk.Entry()
        self.schedule_end_entry.set_placeholder_text("HH:MM ou HH:MM:SS")
        bind_enter(self.schedule_start_entry, self._schedule_enter_pressed)
        bind_enter(self.schedule_end_entry, self._schedule_enter_pressed)

        add_row(schedule_grid, 0, "Heure de début", self.schedule_start_entry)
        add_row(schedule_grid, 1, "Heure de fin", self.schedule_end_entry)
        schedule_card.pack_start(schedule_grid, False, False, 0)

        self.schedule_button = button(
            "Programmer", self.schedule_button_clicked,
            tooltip="Enregistre la programmation ; elle apparaît dans Captures.",
        )
        schedule_card.pack_start(self.schedule_button, False, False, 0)

        self.schedule_status_label = muted_label(
            "Chaque programmation apparaît dans Captures — plusieurs programmations et "
            "captures peuvent tourner en même temps."
        )
        schedule_card.pack_start(self.schedule_status_label, False, False, 0)
        content.pack_start(schedule_card, False, False, 0)

        # --- Listes locales ---------------------------------------------
        playlists_card = section("Listes locales")
        self.playlist_summary_label = muted_label(
            "KageStream recherche les listes M3U, M3U8 et XSPF placées à côté de "
            "l’AppImage ou du script."
        )
        playlists_card.pack_start(self.playlist_summary_label, False, False, 0)

        playlists_buttons = Gtk.Box(spacing=8)
        self.playlist_button = button(
            "Ouvrir les listes…", self.show_local_playlists,
            tooltip="Parcourt les chaînes des listes détectées.",
        )
        playlists_buttons.pack_start(self.playlist_button, False, False, 0)
        playlists_buttons.pack_start(
            button(
                "Actualiser",
                lambda: self.refresh_local_playlist_files(log_result=True),
                tooltip="Relit les fichiers de listes sans redémarrer KageStream.",
            ),
            False, False, 0,
        )
        playlists_card.pack_start(playlists_buttons, False, False, 0)
        content.pack_start(playlists_card, False, False, 0)

        # --- Barre d'action de la page ----------------------------------
        bar = action_bar()
        self.capture_test_button = button(
            "Tester le lien", self.test_link,
            tooltip="Vérifie que Streamlink ou FFmpeg sait lire ce lien (Ctrl+Entrée).",
        )
        self.capture_start_button = button(
            "Enregistrer", self.start_recording, primary=True,
            tooltip="Démarre une nouvelle capture sans arrêter les autres.",
        )
        bar.pack_end(self.capture_start_button, False, False, 0)
        bar.pack_end(self.capture_test_button, False, False, 0)
        outer.pack_start(bar, False, False, 0)

        self.stack.add_titled(outer, "capture", "Capturer")

    def _capture_enter_pressed(self):
        """Entrée dans le champ de lien : teste le lien, geste le plus courant."""
        if self.url_entry.get_text().strip():
            self.test_link(None)

    def _schedule_enter_pressed(self):
        self.schedule_button_clicked(None)
