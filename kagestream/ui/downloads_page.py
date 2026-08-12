import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from kagestream.download.job import JobState
from kagestream.utils.paths import open_folder


def build_downloads_page(window):
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.set_border_width(12)

    intro = Gtk.Label(
        label="File d’attente des téléchargements musicaux (YouTube Music, SoundCloud, Bandcamp).",
        xalign=0,
    )
    intro.set_line_wrap(True)
    outer.pack_start(intro, False, False, 0)

    sections = {}
    for key, title in (("active", "En cours"), ("pending", "En attente"), ("done", "Terminés")):
        frame = Gtk.Frame(label=title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(8)
        frame.add(box)
        outer.pack_start(frame, False, False, 0)
        sections[key] = box

    def clear_section(box):
        for child in list(box.get_children()):
            box.remove(child)

    def build_job_row(job):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.set_margin_bottom(6)

        header = Gtk.Label(xalign=0)
        header.set_markup(
            f"<b>{GLib.markup_escape_text(job.album.title)}</b> — "
            f"{GLib.markup_escape_text(job.album.artist or 'Artiste inconnu')}"
        )
        row.pack_start(header, False, False, 0)

        total = max(job.total_selected, 1)
        progress = Gtk.ProgressBar()
        progress.set_fraction(min(1.0, job.completed_count / total))
        progress.set_text(f"{job.completed_count} / {job.total_selected} pistes")
        progress.set_show_text(True)
        row.pack_start(progress, False, False, 0)

        status_text = job.state.value
        if job.state == JobState.ERREUR and job.error:
            status_text += f" — {job.error}"
        status_label = Gtk.Label(label=status_text, xalign=0)
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

        row.show_all()
        return row

    def refresh():
        for box in sections.values():
            clear_section(box)

        jobs = window.download_manager.jobs
        for job in jobs:
            if job.state in (JobState.TELECHARGEMENT, JobState.ANALYSE):
                sections["active"].pack_start(build_job_row(job), False, False, 0)
            elif job.state == JobState.EN_ATTENTE:
                sections["pending"].pack_start(build_job_row(job), False, False, 0)
            else:
                sections["done"].pack_start(build_job_row(job), False, False, 0)

        if not jobs:
            placeholder = Gtk.Label(label="Aucun téléchargement pour le moment.", xalign=0)
            placeholder.show()
            sections["pending"].pack_start(placeholder, False, False, 0)

        return False

    window.download_manager.add_listener(refresh)
    refresh()

    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.add(outer)
    return scroller
