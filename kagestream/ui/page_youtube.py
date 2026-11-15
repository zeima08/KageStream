"""Page YouTube / Dailymotion."""

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




class YoutubePageMixin:
    def build_youtube_page(self):
        outer, content = page_container(
            "YouTube / Dailymotion",
            "Vidéos, playlists, premières et lives téléchargés avec yt-dlp.",
        )

        # --- Lien -------------------------------------------------------
        link_card = section("Source")
        self.youtube_url_entry = Gtk.Entry()
        self.youtube_url_entry.set_placeholder_text("Colle un lien YouTube ou Dailymotion…")
        self.youtube_url_entry.connect("changed", lambda _entry: self.refresh_action_buttons())
        bind_enter(self.youtube_url_entry, self._youtube_enter_pressed)
        link_card.pack_start(self.youtube_url_entry, False, False, 0)
        link_card.pack_start(
            muted_label(
                "Analyse d’abord le lien pour charger les langues de sous-titres disponibles."
            ),
            False, False, 0,
        )
        content.pack_start(link_card, False, False, 0)

        # --- Format -----------------------------------------------------
        format_card = section("Format")
        youtube_grid = form_grid()

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
        self.youtube_filename.set_placeholder_text(
            "Nom du fichier sans extension — titre automatique si vide"
        )

        self.youtube_folder = Gtk.FileChooserButton(
            title="Choisir le dossier de téléchargement",
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        self.youtube_folder.set_filename(os.getcwd())

        add_row(youtube_grid, 0, "Type", self.source_mode)
        add_row(youtube_grid, 1, "Résolution", self.youtube_resolution,
                tooltip="« Meilleure disponible » prend la plus grande vidéo et le meilleur audio.")
        add_row(youtube_grid, 2, "Conteneur", self.youtube_container)
        add_row(youtube_grid, 3, "Sous-titres", self.youtube_subtitles)
        add_row(youtube_grid, 4, "Nom du fichier", self.youtube_filename)
        add_row(youtube_grid, 5, "Dossier", self.youtube_folder)

        format_card.pack_start(youtube_grid, False, False, 0)
        format_card.pack_start(
            muted_label(
                "« Meilleure disponible » choisit la plus grande vidéo et le meilleur audio. "
                "Le mode playlist télécharge toutes les vidéos de la playlist collée."
            ),
            False, False, 0,
        )
        content.pack_start(format_card, False, False, 0)

        # --- Options ----------------------------------------------------
        options_card = section("Options")
        self.youtube_auto_subs = Gtk.CheckButton(label="Inclure les sous-titres automatiques")
        self.youtube_embed_subs = Gtk.CheckButton(label="Intégrer les sous-titres à la vidéo")
        self.youtube_embed_metadata = Gtk.CheckButton(label="Intégrer les métadonnées et les tags")
        self.youtube_embed_thumbnail = Gtk.CheckButton(label="Intégrer la miniature")
        self.youtube_write_infojson = Gtk.CheckButton(label="Conserver les tags complets (.info.json)")

        self.youtube_embed_subs.set_active(True)
        self.youtube_embed_metadata.set_active(True)
        self.youtube_embed_thumbnail.set_active(True)
        self.youtube_write_infojson.set_active(True)

        for checkbox in (
            self.youtube_auto_subs,
            self.youtube_embed_subs,
            self.youtube_embed_metadata,
            self.youtube_embed_thumbnail,
            self.youtube_write_infojson,
        ):
            options_card.pack_start(checkbox, False, False, 0)
        content.pack_start(options_card, False, False, 0)

        # --- Barre d'action de la page ----------------------------------
        bar = action_bar()
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self.test_button = button(
            "Analyser le lien", self.test_link,
            tooltip="Charge le titre, les résolutions et les langues de sous-titres.",
        )
        self.start_button = button(
            "Télécharger", self.start_recording, primary=True,
            tooltip="Lance le téléchargement ou l’enregistrement du live.",
        )
        self.stop_button = button("Stop", self.stop_recording,
                                  tooltip="Arrête le téléchargement et conserve ce qui est déjà récupéré.")
        self.open_folder_button = button("Ouvrir le dossier", self.open_current_folder)
        self.stop_button.set_sensitive(False)
        self.open_folder_button.set_sensitive(False)

        for widget in (self.test_button, self.start_button,
                       self.stop_button, self.open_folder_button):
            buttons.pack_start(widget, False, False, 0)

        self.stats = muted_label("Durée : 00:00:00")
        self.health_label = muted_label("")
        self.stats.set_no_show_all(True)
        self.health_label.set_no_show_all(True)
        self.stats.hide()
        self.health_label.hide()

        status_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        status_line.pack_start(self.stats, False, False, 0)
        status_line.pack_start(self.health_label, False, False, 0)

        text_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        text_column.pack_start(buttons, False, False, 0)
        text_column.pack_start(status_line, False, False, 0)

        bar.pack_start(text_column, False, False, 0)
        outer.pack_start(bar, False, False, 0)

        self.stack.add_titled(outer, "youtube", "YouTube")

    def _youtube_enter_pressed(self):
        if self.youtube_url_entry.get_text().strip():
            self.test_link(None)
