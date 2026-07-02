#!/usr/bin/env python3
import os
import sys
import gi
import re
import shutil
import subprocess
import threading
import time
import platform
import json
import urllib.request
import urllib.error
from datetime import datetime

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

APP_NAME = "GUIStream"
APP_AUTHOR = "Zeima"
APP_TITLE = f"{APP_NAME} by {APP_AUTHOR}"


def is_frozen():
    return getattr(sys, "frozen", False)


def app_dir():
    return os.path.dirname(sys.executable) if is_frozen() else os.path.dirname(os.path.abspath(__file__))


def find_tool(name):
    for path in [
        os.path.join(app_dir(), "bin", name),
        os.path.join(app_dir(), "bin", name + ".exe"),
    ]:
        if os.path.exists(path):
            return path

    return shutil.which(name)


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120] if name else ""


def open_folder(path):
    folder = os.path.dirname(path) if os.path.isfile(path) else path

    try:
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", folder])
        elif sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
    except Exception:
        pass


def get_tool_version(path, args):
    if not path:
        return "Non détecté"

    try:
        result = subprocess.run(
            [path] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5
        )
        return result.stdout.splitlines()[0].strip() if result.stdout.splitlines() else "Détecté"
    except Exception:
        return "Détecté"


def extract_version_number(text):
    match = re.search(r"(\d+(?:\.\d+)+)", text or "")
    return match.group(1) if match else ""


def version_tuple(version):
    parts = re.findall(r"\d+", version or "")
    return tuple(int(p) for p in parts[:4]) if parts else tuple()


def is_newer_version(latest, current):
    latest_tuple = version_tuple(latest)
    current_tuple = version_tuple(current)

    if not latest_tuple or not current_tuple:
        return False

    return latest_tuple > current_tuple


def fetch_json(url, timeout=12):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"{APP_NAME} Update Checker"
        }
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_latest_streamlink_version():
    data = fetch_json("https://pypi.org/pypi/streamlink/json")
    return data.get("info", {}).get("version", "")


def get_latest_gui_version():
    """
    Fonction prête pour plus tard.
    Si tu publies GUIStream sur GitHub, remplace l'URL par :
    https://api.github.com/repos/TON_COMPTE/GUIStream/releases/latest
    """
    return ""


def get_streamlink_installed_version(streamlink_path):
    if not streamlink_path:
        return ""

    output = get_tool_version(streamlink_path, ["--version"])
    return extract_version_number(output)


def get_ffmpeg_installed_version(ffmpeg_path):
    if not ffmpeg_path:
        return ""

    output = get_tool_version(ffmpeg_path, ["-version"])
    return extract_version_number(output)



class GUIStream(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_TITLE)

        self.set_default_size(900, 680)

        self.process = None
        self.user_stopped = False
        self.remux_dialog = None
        self.recording_start = None
        self.current_ts_file = None
        self.final_file = None
        self.stats_timer_id = None

        self.streamlink = None
        self.ffmpeg = None
        self.ffprobe = None

        self.build_ui()
        self.check_dependencies(silent=True)
        self.log_startup()

    def build_ui(self):
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main.set_margin_top(14)
        main.set_margin_bottom(14)
        main.set_margin_start(14)
        main.set_margin_end(14)
        self.add(main)

        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{APP_TITLE}</b>")
        main.pack_start(title, False, False, 0)

        self.status = Gtk.Label(label="Prêt.", xalign=0)
        main.pack_start(self.status, False, False, 0)

        self.url_entry = Gtk.Entry()
        self.url_entry.set_placeholder_text("Colle ton lien ici...")
        main.pack_start(self.url_entry, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        main.pack_start(grid, False, False, 0)

        self.quality = Gtk.ComboBoxText()
        self.quality.append_text("best")
        self.quality.set_active(0)

        self.output_format = Gtk.ComboBoxText()
        for fmt in ["ts", "mkv", "mp4"]:
            self.output_format.append_text(fmt)
        self.output_format.set_active(0)

        self.filename = Gtk.Entry()
        self.filename.set_placeholder_text("Nom du fichier sans extension — optionnel")

        self.folder = Gtk.FileChooserButton(
            title="Choisir le dossier de sortie",
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        self.folder.set_filename(os.getcwd())

        grid.attach(Gtk.Label(label="Qualité", xalign=0), 0, 0, 1, 1)
        grid.attach(self.quality, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Format final", xalign=0), 0, 1, 1, 1)
        grid.attach(self.output_format, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="Nom du fichier", xalign=0), 0, 2, 1, 1)
        grid.attach(self.filename, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label="Dossier", xalign=0), 0, 3, 1, 1)
        grid.attach(self.folder, 1, 3, 1, 1)

        buttons = Gtk.Box(spacing=8)
        main.pack_start(buttons, False, False, 0)

        self.test_button = Gtk.Button(label="Tester le lien")
        self.test_button.connect("clicked", self.test_link)
        buttons.pack_start(self.test_button, True, True, 0)

        self.diagnostic_button = Gtk.Button(label="Diagnostic")
        self.diagnostic_button.connect("clicked", self.show_diagnostic)
        buttons.pack_start(self.diagnostic_button, True, True, 0)

        self.update_button = Gtk.Button(label="Mises à jour")
        self.update_button.connect("clicked", self.show_update_checker)
        buttons.pack_start(self.update_button, True, True, 0)

        self.start_button = Gtk.Button(label="▶ Enregistrer")
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
        main.pack_start(self.stats, False, False, 0)

        self.log = Gtk.TextView()
        self.log.set_editable(False)
        self.log.set_monospace(True)

        scroll = Gtk.ScrolledWindow()
        scroll.add(self.log)
        main.pack_start(scroll, True, True, 0)

    def log_startup(self):
        self.log_text("========================================")
        self.log_text(APP_TITLE)
        self.log_text("Interface graphique pour Streamlink")
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
        self.ffmpeg = find_tool("ffmpeg")
        self.ffprobe = find_tool("ffprobe")

        missing = []
        if not self.streamlink:
            missing.append("Streamlink")
        if not self.ffmpeg:
            missing.append("FFmpeg")

        if missing:
            self.start_button.set_sensitive(False)
            self.test_button.set_sensitive(False)
            self.set_status("Configuration incomplète : " + ", ".join(missing))
        else:
            self.start_button.set_sensitive(True)
            self.test_button.set_sensitive(True)
            self.set_status("Prêt.")

        if not silent:
            self.write_diagnostic_log()

    def test_link(self, button):
        url = self.url_entry.get_text().strip()

        if not url:
            self.show_message("Lien manquant", "Colle un lien avant de le tester.", Gtk.MessageType.WARNING)
            return

        self.test_button.set_sensitive(False)
        self.set_status("Test du lien en cours...")

        threading.Thread(target=self.test_link_worker, args=(url,), daemon=True).start()

    def test_link_worker(self, url):
        cmd = [self.streamlink, "--json", url]

        self.log_text("")
        self.log_text("Test du lien :")
        self.log_text(" ".join(cmd))

        try:
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
                GLib.idle_add(self.set_auto_filename, title)

            if result.returncode == 0:
                self.set_status("Lien valide.")
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

        except Exception as e:
            self.log_text(f"Erreur test : {e}")
            self.set_status("Erreur pendant le test.")

        finally:
            GLib.idle_add(self.test_button.set_sensitive, True)

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

    def set_auto_filename(self, title):
        if not self.filename.get_text().strip():
            self.filename.set_text(title)
        return False

    def safe_filename(self):
        name = sanitize_filename(self.filename.get_text().strip())
        if not name:
            name = "record_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return name

    def start_recording(self, button):
        url = self.url_entry.get_text().strip()

        if not url:
            self.show_message("Lien manquant", "Colle un lien avant de lancer l’enregistrement.", Gtk.MessageType.WARNING)
            return

        self.check_dependencies(silent=True)

        fmt = self.output_format.get_active_text()

        if not self.streamlink:
            self.show_message("Streamlink introuvable", "Streamlink est nécessaire pour enregistrer.", Gtk.MessageType.ERROR)
            return

        if fmt != "ts" and not self.ffmpeg:
            self.show_message("FFmpeg introuvable", "FFmpeg est nécessaire pour MKV ou MP4.", Gtk.MessageType.ERROR)
            return

        self.user_stopped = False
        self.recording_start = time.time()

        folder = self.folder.get_filename() or os.getcwd()
        quality = self.quality.get_active_text() or "best"
        ts_file = os.path.join(folder, self.safe_filename()) + ".ts"

        self.current_ts_file = ts_file
        self.final_file = ts_file
        self.open_folder_button.set_sensitive(False)

        self.start_button.set_sensitive(False)
        self.test_button.set_sensitive(False)
        self.stop_button.set_sensitive(True)
        self.set_status("Enregistrement en cours...")

        self.stats_timer_id = GLib.timeout_add(1000, self.update_stats)

        threading.Thread(
            target=self.record_worker,
            args=(url, quality, fmt, ts_file),
            daemon=True
        ).start()

    def record_worker(self, url, quality, fmt, ts_file):
        cmd = [self.streamlink, url, quality, "-o", ts_file]

        self.log_text("")
        self.log_text("Commande Streamlink :")
        self.log_text(" ".join(cmd))

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            for line in self.process.stdout:
                self.log_text(line.rstrip())

            self.process.wait()

            if self.user_stopped:
                self.log_text("Enregistrement arrêté par l’utilisateur.")
                self.log_text(f"Fichier conservé : {ts_file}")
                if fmt != "ts":
                    self.remux(ts_file, fmt)

            elif self.process.returncode == 0:
                self.log_text("Enregistrement terminé.")
                if fmt == "ts":
                    self.final_file = ts_file
                    self.log_text(f"Fichier final : {ts_file}")
                else:
                    self.remux(ts_file, fmt)

            else:
                self.log_text("Streamlink s’est arrêté avec une erreur.")

        except Exception as e:
            if self.user_stopped:
                self.log_text("Enregistrement arrêté par l’utilisateur.")
                if fmt != "ts":
                    self.remux(ts_file, fmt)
            else:
                self.log_text(f"Erreur : {e}")

        finally:
            self.process = None
            GLib.idle_add(self.start_button.set_sensitive, True)
            GLib.idle_add(self.test_button.set_sensitive, True)
            GLib.idle_add(self.stop_button.set_sensitive, False)
            GLib.idle_add(self.open_folder_button.set_sensitive, True)
            self.set_status("Prêt.")

    def update_stats(self):
        if not self.process and not self.recording_start:
            return False

        elapsed = int(time.time() - self.recording_start) if self.recording_start else 0
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60

        size_mb = 0
        if self.current_ts_file and os.path.exists(self.current_ts_file):
            size_mb = os.path.getsize(self.current_ts_file) / 1024 / 1024

        self.stats.set_text(f"Durée : {h:02d}:{m:02d}:{s:02d} — Taille : {size_mb:.1f} Mo")

        if self.process:
            return True

        self.recording_start = None
        return False

    def remux(self, ts_file, fmt):
        if not self.ffmpeg:
            self.log_text("Remux impossible : FFmpeg introuvable.")
            return

        if not os.path.exists(ts_file):
            self.log_text("Remux impossible : fichier TS introuvable.")
            return

        output = os.path.splitext(ts_file)[0] + "." + fmt
        cmd = [self.ffmpeg, "-y", "-i", ts_file, "-c", "copy", output]

        GLib.idle_add(self.show_remux_dialog)

        self.log_text("")
        self.log_text("Commande FFmpeg :")
        self.log_text(" ".join(cmd))

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            for line in proc.stdout:
                self.log_text(line.rstrip())

            proc.wait()

            if proc.returncode == 0:
                self.final_file = output
                self.log_text(f"Remux terminé : {output}")
                GLib.idle_add(
                    self.close_remux_dialog,
                    "Remux : fait",
                    f"Fichier final : {output}",
                    Gtk.MessageType.INFO
                )

            elif fmt == "mp4":
                self.log_text("MP4 impossible. Proposition de remux en MKV.")
                GLib.idle_add(self.ask_mkv_fallback, ts_file)

            else:
                GLib.idle_add(
                    self.close_remux_dialog,
                    "Remux impossible",
                    "FFmpeg n’a pas réussi à remuxer ce fichier. Le TS est conservé.",
                    Gtk.MessageType.ERROR
                )

        except Exception:
            GLib.idle_add(
                self.close_remux_dialog,
                "Remux impossible",
                "Une erreur est survenue pendant le remux. Le TS est conservé.",
                Gtk.MessageType.ERROR
            )

    def ask_mkv_fallback(self, ts_file):
        if self.remux_dialog:
            self.remux_dialog.destroy()
            self.remux_dialog = None

        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Le MP4 a échoué"
        )
        dialog.format_secondary_text("Voulez-vous tenter un remux en MKV à la place ?")

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            threading.Thread(target=self.remux, args=(ts_file, "mkv"), daemon=True).start()
        else:
            self.show_message("Fichier TS conservé", f"Fichier conservé : {ts_file}", Gtk.MessageType.INFO)

        return False

    def show_remux_dialog(self):
        self.remux_dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text="Remux en cours..."
        )
        self.remux_dialog.format_secondary_text("Ne ferme pas GUIStream pendant cette étape.")
        self.remux_dialog.show_all()
        return False

    def close_remux_dialog(self, title, message, message_type):
        if self.remux_dialog:
            self.remux_dialog.destroy()
            self.remux_dialog = None

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
        dialog.format_secondary_text("Le fichier déjà enregistré sera conservé puis remuxé si nécessaire.")

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            self.user_stopped = True
            self.log_text("Arrêt demandé par l’utilisateur.")
            self.process.terminate()

    def open_current_folder(self, button):
        target = self.final_file or self.current_ts_file or self.folder.get_filename()
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
        dialog.set_default_size(620, 420)

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

        update_streamlink_button = Gtk.Button(label="Mettre à jour Streamlink")
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

            rows.append((
                "FFmpeg",
                current_ffmpeg or "Non détecté",
                "Vérification auto non disponible",
                "À mettre à jour avec le système ou le paquet AppImage"
            ))

            rows.append((
                "GTK",
                f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}",
                "Fourni par le système",
                "Géré par Linux"
            ))

            message = (
                "Streamlink peut être vérifié via PyPI. "
                "FFmpeg et GTK dépendent généralement du système ou du paquet distribué."
            )

            GLib.idle_add(set_rows, rows, streamlink_update_available, message)

        threading.Thread(target=worker, daemon=True).start()

        dialog.run()
        dialog.destroy()

    def update_streamlink(self, button):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Mettre à jour Streamlink ?"
        )
        dialog.format_secondary_text(
            "GUIStream va lancer : python -m pip install --upgrade streamlink\n\n"
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
                    "Streamlink a été mis à jour. Redémarre GUIStream si nécessaire.",
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
        self.log_text(f"GTK : OK — {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}")
        self.log_text(f"Streamlink : {'OK — ' + self.streamlink if self.streamlink else 'MANQUANT'}")
        self.log_text(f"FFmpeg : {'OK — ' + self.ffmpeg if self.ffmpeg else 'MANQUANT'}")
        self.log_text(f"FFprobe : {'OK — ' + self.ffprobe if self.ffprobe else 'optionnel, non détecté'}")
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
            status.set_markup("🟢 <b>Tout est prêt.</b>" if self.streamlink and self.ffmpeg else "🔴 <b>Configuration incomplète.</b>")

            rows = [
                ("GTK", "🟢", f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"),
                ("Streamlink", "🟢" if self.streamlink else "🔴", get_tool_version(self.streamlink, ["--version"])),
                ("FFmpeg", "🟢" if self.ffmpeg else "🔴", get_tool_version(self.ffmpeg, ["-version"])),
                ("FFprobe", "🟢" if self.ffprobe else "🟡", get_tool_version(self.ffprobe, ["-version"])),
                ("Python", "🟢", sys.version.split()[0]),
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


if __name__ == "__main__":
    win = GUIStream()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()