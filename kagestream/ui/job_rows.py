import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


class SectionedJobList:
    """Affiche des tâches réparties en sections GTK sans tout reconstruire.

    Une rangée n'est créée qu'une fois : elle est ensuite mise à jour en
    place (textes, barre de progression) à chaque notification. Elle n'est
    recréée que si sa « signature » change — c'est-à-dire si l'ensemble des
    widgets qu'elle contient doit changer (nouvel état, boutons différents) —
    et déplacée si sa section d'appartenance change.

    Sans ça, chaque notification (une par seconde pendant une capture, une
    par ligne de progression yt-dlp) détruisait et recréait toutes les
    rangées de toutes les tâches, y compris terminées : clignotement, perte
    du focus clavier et coût croissant avec l'historique de la session."""

    def __init__(self, sections, empty_texts=None):
        self._sections = sections
        self._rows = {}
        self._placeholders = {}
        for key, box in sections.items():
            label = Gtk.Label(label=(empty_texts or {}).get(key, ""), xalign=0)
            box.pack_start(label, False, False, 0)
            self._placeholders[key] = label

    def sync(self, entries):
        """entries : itérable de (job_id, section, signature, factory), dans
        l'ordre d'affichage souhaité. `factory()` doit retourner
        (widget, refresh_callable) ; refresh_callable est appelé à chaque
        synchronisation pour mettre à jour les données dynamiques."""
        seen = set()
        positions = {}

        for job_id, section, signature, factory in entries:
            seen.add(job_id)
            row = self._rows.get(job_id)

            if row is not None and row["signature"] != signature:
                self._destroy_row(job_id)
                row = None

            if row is None:
                widget, refresh = factory()
                widget.show_all()
                self._sections[section].pack_start(widget, False, False, 0)
                row = {
                    "child": widget,
                    "section": section,
                    "signature": signature,
                    "refresh": refresh,
                }
                self._rows[job_id] = row
            elif row["section"] != section:
                parent = row["child"].get_parent()
                if parent is not None:
                    parent.remove(row["child"])
                self._sections[section].pack_start(row["child"], False, False, 0)
                row["section"] = section

            if row["refresh"] is not None:
                row["refresh"]()

            index = positions.get(section, 0)
            positions[section] = index + 1
            self._sections[section].reorder_child(row["child"], index)

        for job_id in list(self._rows):
            if job_id not in seen:
                self._destroy_row(job_id)

        for key in self._sections:
            if positions.get(key, 0):
                self._placeholders[key].hide()
            else:
                self._placeholders[key].show()

        return False

    def _destroy_row(self, job_id):
        row = self._rows.pop(job_id)
        parent = row["child"].get_parent()
        if parent is not None:
            parent.remove(row["child"])
