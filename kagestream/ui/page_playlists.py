"""Fenêtre des listes M3U, M3U8 et XSPF locales."""

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




class PlaylistsPageMixin:
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
