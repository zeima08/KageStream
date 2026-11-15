"""Détection, installation et mise à jour des dépendances, diagnostic."""

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




class DependenciesLogicMixin:
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
