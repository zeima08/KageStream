import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from kagestream.download.job import JobState
from kagestream.ui.job_rows import SectionedJobList
from kagestream.ui.widgets import button, page_container, section
from kagestream.utils.paths import open_folder


EMPTY_TEXTS = {
    "active": "Aucun téléchargement en cours.",
    "pending": "Aucun téléchargement en attente.",
    "done": "Aucun téléchargement terminé.",
}


def build_downloads_page(window):
    outer, content = page_container(
        "Téléchargements",
        "File d’attente des téléchargements musicaux (YouTube Music, SoundCloud, Bandcamp).",
    )

    clear_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    clear_row.pack_end(
        button(
            "Vider les terminés", lambda: window.download_manager.clear_finished(),
            tooltip="Retire de la liste les téléchargements terminés, annulés ou en "
                    "erreur. Les fichiers téléchargés ne sont pas supprimés.",
        ),
        False, False, 0,
    )
    content.pack_start(clear_row, False, False, 0)

    sections = {}
    for key, title in (("active", "En cours"), ("pending", "En attente"), ("done", "Terminés")):
        card = section(title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.pack_start(box, False, False, 0)
        content.pack_start(card, False, False, 0)
        sections[key] = box

    def build_job_row(job):
        """Construit la rangée d'un téléchargement et retourne (widget,
        refresh). La structure n'est recréée que si la signature change."""
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.set_margin_bottom(6)

        header = Gtk.Label(xalign=0)
        header.set_markup(
            f"<b>{GLib.markup_escape_text(job.album.title)}</b> — "
            f"{GLib.markup_escape_text(job.album.artist or 'Artiste inconnu')}"
        )
        row.pack_start(header, False, False, 0)

        progress = Gtk.ProgressBar()
        progress.set_show_text(True)
        row.pack_start(progress, False, False, 0)

        status_label = Gtk.Label(xalign=0)
        status_label.set_line_wrap(True)
        row.pack_start(status_label, False, False, 0)

        buttons = Gtk.Box(spacing=6)
        row.pack_start(buttons, False, False, 0)

        if job.state in (JobState.EN_ATTENTE, JobState.ANALYSE, JobState.TELECHARGEMENT):
            cancel_button = Gtk.Button(label="Annuler")
            cancel_button.connect("clicked", lambda _b, j=job: window.download_manager.cancel(j))
            buttons.pack_start(cancel_button, False, False, 0)

        if job.state == JobState.TERMINE:
            open_button = Gtk.Button(label="Ouvrir le dossier")

            def _open(_button, current_job=job):
                for track_job in current_job.tracks:
                    if track_job.final_path:
                        open_folder(track_job.final_path)
                        return
                open_folder(current_job.destination_root)

            open_button.connect("clicked", _open)
            buttons.pack_start(open_button, False, False, 0)

        if job.state not in (JobState.EN_ATTENTE, JobState.TELECHARGEMENT, JobState.ANALYSE):
            remove_button = Gtk.Button(label="Retirer de la liste")
            remove_button.connect(
                "clicked", lambda _b, j=job: window.download_manager.remove_job(j)
            )
            buttons.pack_start(remove_button, False, False, 0)

        def refresh():
            total = max(job.total_selected, 1)
            completed = job.completed_count

            # Progression de la piste en cours : progress_percent était calculé
            # par le manager mais jamais affiché, si bien que la barre restait
            # à zéro pendant toute la durée d'une longue piste.
            current = None
            for track_job in job.selected_tracks:
                if track_job.state == JobState.TELECHARGEMENT:
                    current = track_job
                    break

            fraction = completed / total
            if current is not None and current.progress_percent:
                in_track = min(1.0, max(0.0, current.progress_percent / 100.0))
                fraction = min(1.0, (completed + in_track) / total)

            progress.set_fraction(fraction)
            progress.set_text(f"{completed} / {job.total_selected} pistes")

            text = job.state.value
            if current is not None and current.progress_percent:
                text += f" — {current.progress_percent:.0f} %"
            if job.state == JobState.ERREUR and job.error:
                text += f" — {job.error}"
            status_label.set_text(text)
            return False

        refresh()
        row.show_all()
        return row, refresh

    def row_signature(job):
        return (job.state,)

    def section_for(job):
        if job.state in (JobState.TELECHARGEMENT, JobState.ANALYSE):
            return "active"
        if job.state == JobState.EN_ATTENTE:
            return "pending"
        return "done"

    def refresh():
        entries = [
            (job.id, section_for(job), row_signature(job), lambda j=job: build_job_row(j))
            for job in window.download_manager.jobs
        ]
        return job_list.sync(entries)

    job_list = SectionedJobList(sections, EMPTY_TEXTS)

    window.download_manager.add_listener(refresh)
    refresh()

    return outer
