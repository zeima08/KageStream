import os
import threading
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from kagestream.capture.job import CaptureState
from kagestream.media.ffprobe import probe_duration, parse_timecode, format_timecode
from kagestream.ui.job_rows import SectionedJobList
from kagestream.ui.widgets import button, page_container, section
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


EMPTY_TEXTS = {
    "active": "Aucune capture en cours.",
    "pending": "Aucune capture programmée.",
    "done": "Aucune capture terminée.",
}




def _format_duration(seconds):
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_captures_page(window):
    outer, content = page_container(
        "Captures",
        "Toutes les captures lancées depuis Capturer, avec leur statut, leur santé et "
        "les actions disponibles. Plusieurs captures peuvent tourner en même temps.",
    )

    clear_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    clear_button = button(
        "Vider les terminées", lambda: window.capture_manager.clear_finished(),
        tooltip="Retire de la liste les captures terminées, annulées ou en erreur. "
                "Les fichiers produits ne sont pas supprimés.",
    )
    clear_row.pack_end(clear_button, False, False, 0)
    content.pack_start(clear_row, False, False, 0)

    sections = {}
    for key, title in (("active", "En cours"), ("pending", "Programmées"), ("done", "Terminées")):
        card = section(title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.pack_start(box, False, False, 0)
        content.pack_start(card, False, False, 0)
        sections[key] = box

    def open_job_folder(job):
        target = job.cut_file or job.final_file or job.current_ts_file or job.folder
        open_folder(target)

    def show_cut_dialog(job):
        dialog = Gtk.Dialog(
            title="Couper cette vidéo",
            transient_for=window,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT
        )
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
        duration_label.set_text("Durée totale : calcul en cours…")
        content.pack_start(duration_label, False, False, 0)

        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        content.pack_start(grid, False, False, 0)

        start_entry = Gtk.Entry()
        start_entry.set_placeholder_text("HH:MM:SS, MM:SS ou secondes")
        start_entry.set_text("0")
        end_entry = Gtk.Entry()
        end_entry.set_placeholder_text("HH:MM:SS, MM:SS ou secondes")

        grid.attach(Gtk.Label(label="Début", xalign=0), 0, 0, 1, 1)
        grid.attach(start_entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Fin", xalign=0), 0, 1, 1, 1)
        grid.attach(end_entry, 1, 1, 1, 1)

        error_label = Gtk.Label(xalign=0)
        error_label.set_line_wrap(True)
        content.pack_start(error_label, False, False, 0)

        content.show_all()

        duration_state = {"total": None}

        def duration_ready(total):
            duration_state["total"] = total
            if total is not None:
                duration_label.set_text(f"Durée totale : {format_timecode(total)}")
                if not end_entry.get_text().strip():
                    end_entry.set_text(format_timecode(total))
            else:
                duration_label.set_text("Durée totale inconnue (ffprobe indisponible).")
            return False

        def probe_worker():
            # ffprobe sur un gros fichier peut prendre plusieurs secondes :
            # hors de question de bloquer le thread GTK pendant la sonde.
            total = probe_duration(window.ffprobe, job.final_file)
            GLib.idle_add(duration_ready, total)

        threading.Thread(target=probe_worker, daemon=True).start()

        def on_response(dlg, response_id):
            if response_id != Gtk.ResponseType.OK:
                dlg.destroy()
                return

            total_duration = duration_state["total"]
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
        """Construit la rangée d'une capture et retourne (widget, refresh).
        `refresh` met à jour les textes sans toucher à la structure : la
        rangée n'est reconstruite que si sa signature change (voir
        row_signature)."""
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.set_margin_bottom(6)

        header = Gtk.Label(xalign=0)
        row.pack_start(header, False, False, 0)

        status_label = Gtk.Label(xalign=0)
        status_label.set_line_wrap(True)
        row.pack_start(status_label, False, False, 0)

        report_label = None
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
            add_button(
                "Retirer de la liste",
                lambda j=job: window.capture_manager.remove_job(j)
            )

        def status_text():
            text = job.state.value
            if job.state in (CaptureState.EN_COURS, CaptureState.RECONNEXION) and job.recording_start:
                elapsed = _format_duration(time.time() - job.recording_start)
                size_mb = 0.0
                if job.current_ts_file and os.path.exists(job.current_ts_file):
                    size_mb = os.path.getsize(job.current_ts_file) / 1024 / 1024
                text += f" — Durée : {elapsed} — Taille : {size_mb:.1f} Mo"
            if job.stream_health not in ("", "Non analysé"):
                text += f" — Santé : {job.stream_health}"
            if job.state == CaptureState.ERREUR and job.error:
                text += f" — {job.error}"
            return text

        def refresh():
            header.set_markup(
                f"<b>{GLib.markup_escape_text(job.label)}</b>"
                + (f" — {GLib.markup_escape_text(job.active_backend)}" if job.active_backend else "")
            )
            status_label.set_text(status_text())
            if report_label is not None:
                report_label.set_text(job.last_health_report or "")
            return False

        refresh()
        row.show_all()
        return row, refresh

    def row_signature(job):
        """Signature structurelle : une rangée n'est reconstruite que si l'un
        de ces éléments change (les autres sont de simples textes)."""
        return (
            job.state,
            job.active_backend,
            bool(job.cut_file),
            bool(job.final_file) if job.state in DONE_STATES else False,
        )

    def section_for(job):
        if job.state == CaptureState.EN_ATTENTE:
            return "pending"
        if job.state in DONE_STATES:
            return "done"
        return "active"

    def refresh():
        entries = [
            (job.id, section_for(job), row_signature(job), lambda j=job: build_job_row(j))
            for job in window.capture_manager.jobs
        ]
        return job_list.sync(entries)

    job_list = SectionedJobList(sections, EMPTY_TEXTS)

    window.capture_manager.add_listener(refresh)
    refresh()

    return outer
