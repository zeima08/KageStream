import os
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from kagestream.capture.job import CaptureState
from kagestream.media.ffprobe import probe_duration, parse_timecode, format_timecode
from kagestream.utils.paths import open_folder

ACTIVE_STATES = {
    CaptureState.EN_COURS,
    CaptureState.RECONNEXION,
    CaptureState.EN_ATTENTE_REMUX,
    CaptureState.DECISION_REMUX,
    CaptureState.VERIFICATION,
    CaptureState.DECISION_POST_VERIF,
    CaptureState.REMUX,
    CaptureState.DECISION_MKV,
    CaptureState.CONVERSION,
}
DONE_STATES = {CaptureState.TERMINE, CaptureState.ANNULE, CaptureState.ERREUR}


def _format_duration(seconds):
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_captures_page(window):
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.set_border_width(12)

    intro = Gtk.Label(
        label=(
            "Toutes les captures lancées depuis l’onglet Capturer, avec leur statut, "
            "leur santé et les actions disponibles. Plusieurs captures peuvent tourner "
            "en même temps."
        ),
        xalign=0,
    )
    intro.set_line_wrap(True)
    outer.pack_start(intro, False, False, 0)

    sections = {}
    for key, title in (("active", "En cours"), ("pending", "Programmées"), ("done", "Terminées")):
        frame = Gtk.Frame(label=title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(8)
        frame.add(box)
        outer.pack_start(frame, False, False, 0)
        sections[key] = box

    def clear_section(box):
        for child in list(box.get_children()):
            box.remove(child)

    def open_job_folder(job):
        target = job.cut_file or job.final_file or job.current_ts_file or job.folder
        open_folder(target)

    def show_cut_dialog(job):
        total_duration = probe_duration(window.ffprobe, job.final_file)

        dialog = Gtk.Dialog(title="Couper cette vidéo", transient_for=window, flags=0)
        dialog.add_button("Annuler", Gtk.ResponseType.CANCEL)
        dialog.add_button("Couper", Gtk.ResponseType.OK)
        dialog.set_default_size(420, -1)

        content = dialog.get_content_area()
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_spacing(8)

        duration_label = Gtk.Label(xalign=0)
        duration_label.set_text(
            f"Durée totale : {format_timecode(total_duration)}"
            if total_duration is not None
            else "Durée totale inconnue (ffprobe indisponible)."
        )
        content.pack_start(duration_label, False, False, 0)

        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        content.pack_start(grid, False, False, 0)

        start_entry = Gtk.Entry()
        start_entry.set_placeholder_text("HH:MM:SS, MM:SS ou secondes")
        start_entry.set_text("0")
        end_entry = Gtk.Entry()
        end_entry.set_placeholder_text("HH:MM:SS, MM:SS ou secondes")
        if total_duration is not None:
            end_entry.set_text(format_timecode(total_duration))

        grid.attach(Gtk.Label(label="Début", xalign=0), 0, 0, 1, 1)
        grid.attach(start_entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Fin", xalign=0), 0, 1, 1, 1)
        grid.attach(end_entry, 1, 1, 1, 1)

        error_label = Gtk.Label(xalign=0)
        error_label.set_line_wrap(True)
        content.pack_start(error_label, False, False, 0)

        content.show_all()

        def on_response(dlg, response_id):
            if response_id != Gtk.ResponseType.OK:
                dlg.destroy()
                return

            start_seconds = parse_timecode(start_entry.get_text())
            end_seconds = parse_timecode(end_entry.get_text())

            if start_seconds is None or end_seconds is None:
                error_label.set_text("Format invalide. Utilise HH:MM:SS, MM:SS ou un nombre de secondes.")
                return
            if start_seconds >= end_seconds:
                error_label.set_text("Le début doit être avant la fin.")
                return
            if total_duration is not None and end_seconds > total_duration + 1:
                error_label.set_text("La fin dépasse la durée totale de la vidéo.")
                return

            window.capture_manager.cut_file(job, start_seconds, end_seconds)
            dlg.destroy()

        dialog.connect("response", on_response)
        dialog.show()

    def build_job_row(job):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.set_margin_bottom(6)

        header = Gtk.Label(xalign=0)
        header.set_markup(
            f"<b>{GLib.markup_escape_text(job.label)}</b>"
            + (f" — {GLib.markup_escape_text(job.active_backend)}" if job.active_backend else "")
        )
        row.pack_start(header, False, False, 0)

        status_text = job.state.value
        if job.state in (CaptureState.EN_COURS, CaptureState.RECONNEXION) and job.recording_start:
            elapsed = _format_duration(time.time() - job.recording_start)
            size_mb = 0.0
            if job.current_ts_file and os.path.exists(job.current_ts_file):
                size_mb = os.path.getsize(job.current_ts_file) / 1024 / 1024
            status_text += f" — Durée : {elapsed} — Taille : {size_mb:.1f} Mo"
        if job.stream_health not in ("", "Non analysé"):
            status_text += f" — Santé : {job.stream_health}"
        if job.state == CaptureState.ERREUR and job.error:
            status_text += f" — {job.error}"
        status_label = Gtk.Label(label=status_text, xalign=0)
        status_label.set_line_wrap(True)
        row.pack_start(status_label, False, False, 0)

        if job.last_health_report and job.state in (
            CaptureState.DECISION_POST_VERIF, CaptureState.DECISION_MKV
        ):
            report_label = Gtk.Label(label=job.last_health_report, xalign=0)
            report_label.set_line_wrap(True)
            row.pack_start(report_label, False, False, 0)

        if job.cut_file:
            cut_label = Gtk.Label(label=f"Fichier coupé : {job.cut_file}", xalign=0)
            cut_label.set_line_wrap(True)
            row.pack_start(cut_label, False, False, 0)

        buttons = Gtk.Box(spacing=6)
        row.pack_start(buttons, False, False, 0)

        def add_button(label, callback):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _b: callback())
            buttons.pack_start(button, False, False, 0)

        if job.state == CaptureState.EN_ATTENTE:
            add_button(
                "Annuler la programmation",
                lambda j=job: window.capture_manager.cancel_schedule(j)
            )
        elif job.state in (CaptureState.EN_COURS, CaptureState.RECONNEXION):
            add_button("Stop", lambda j=job: window.capture_manager.stop(j))
        elif job.state == CaptureState.DECISION_REMUX:
            add_button(
                "Vérifier le TS",
                lambda j=job: window.capture_manager.resolve_decision(j, "verify")
            )
            add_button(
                "Remuxer directement",
                lambda j=job: window.capture_manager.resolve_decision(j, "remux_directly")
            )
        elif job.state == CaptureState.DECISION_POST_VERIF:
            add_button(
                "Continuer le remux",
                lambda j=job: window.capture_manager.resolve_decision(j, "continue_remux")
            )
            add_button(
                "Conserver le TS",
                lambda j=job: window.capture_manager.resolve_decision(j, "keep_ts")
            )
        elif job.state == CaptureState.DECISION_MKV:
            add_button(
                "Remuxer en MKV",
                lambda j=job: window.capture_manager.resolve_decision(j, "try_mkv")
            )
            add_button(
                "Garder le TS",
                lambda j=job: window.capture_manager.resolve_decision(j, "keep_ts")
            )
        elif job.state in DONE_STATES:
            if job.final_file and os.path.isfile(job.final_file):
                add_button("Ouvrir le dossier", lambda j=job: open_job_folder(j))
            if job.state == CaptureState.TERMINE and job.final_file and os.path.isfile(job.final_file):
                add_button("Couper cette vidéo…", lambda j=job: show_cut_dialog(j))

        row.show_all()
        return row

    def refresh():
        for box in sections.values():
            clear_section(box)

        jobs = window.capture_manager.jobs
        for job in jobs:
            if job.state == CaptureState.EN_ATTENTE:
                sections["pending"].pack_start(build_job_row(job), False, False, 0)
            elif job.state in DONE_STATES:
                sections["done"].pack_start(build_job_row(job), False, False, 0)
            else:
                sections["active"].pack_start(build_job_row(job), False, False, 0)

        if not jobs:
            placeholder = Gtk.Label(label="Aucune capture pour le moment.", xalign=0)
            placeholder.show()
            sections["active"].pack_start(placeholder, False, False, 0)

        return False

    window.capture_manager.add_listener(refresh)
    refresh()

    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.add(outer)
    return scroller
