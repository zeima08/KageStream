import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from kagestream.ui.widgets import badge, choose_icon

# (libellé, page du Gtk.Stack, icônes candidates, sous-item)
SIDEBAR_ENTRIES = [
    ("Capturer", "capture", ("media-record-symbolic", "media-playback-start-symbolic"), False),
    ("Captures", "captures", ("camera-video-symbolic", "camera-web-symbolic"), False),
    ("Musique", "music", ("audio-x-generic-symbolic", "audio-volume-high-symbolic"), False),
    ("YouTube", "youtube", ("video-x-generic-symbolic", "emblem-videos-symbolic"), False),
    ("Téléchargements", "downloads", ("document-save-symbolic", "folder-download-symbolic"), False),
    ("Outils", None, None, False),
    ("Dépendances", "tools_deps", ("application-x-executable-symbolic", "utilities-terminal-symbolic"), True),
    ("Diagnostic", "tools_diag", ("utilities-system-monitor-symbolic", "dialog-information-symbolic"), True),
    ("Journal", "tools_logs", ("text-x-generic-symbolic", "document-open-symbolic"), True),
]

# Pages qui portent une pastille de compteur / d'alerte.
BADGE_PAGES = ("captures", "downloads", "tools_logs")
CAPTURE_ACTIVE_STATES = ("Enregistrement", "Reconnexion")
DOWNLOAD_ACTIVE_STATES = ("En attente", "Analyse", "Téléchargement")


class Sidebar:
    """Barre latérale : icônes, libellés ellipsés et pastilles de compteurs.

    Les pastilles répondent à une question concrète — « y a-t-il quelque chose
    en cours ? » — sans quitter la page où l'on se trouve."""

    def __init__(self, window, stack):
        self.window = window
        self.stack = stack
        self._rows = {}
        self._badges = {}

        self.widget = Gtk.ScrolledWindow()
        self.widget.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.widget.set_size_request(180, -1)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        listbox.get_style_context().add_class("sidebar")
        self.widget.add(listbox)
        self.listbox = listbox

        for label, page_name, icons, is_sub in SIDEBAR_ENTRIES:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            if page_name is None:
                # En-tête de section : lisible, mais pas une destination.
                text = Gtk.Label(label=label.upper(), xalign=0)
                text.get_style_context().add_class("sidebar-section")
                box.pack_start(text, True, True, 0)
                row.set_selectable(False)
                row.set_activatable(False)
                # Espace de séparation au-dessus de la section, plutôt qu'un
                # Gtk.Separator inséré dans le ListBox : un enfant qui n'est
                # pas un Gtk.ListBoxRow perturbe la liste des lignes.
                row.set_margin_top(14)
            else:
                icon_name = choose_icon(*icons)
                if icon_name:
                    box.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU),
                                   False, False, 0)

                text = Gtk.Label(label=label, xalign=0)
                text.set_ellipsize(3)  # Pango.EllipsizeMode.END
                box.pack_start(text, True, True, 0)

                marker = badge()
                marker.set_no_show_all(True)
                marker.hide()
                if page_name in BADGE_PAGES:
                    box.pack_end(marker, False, False, 0)
                    self._badges[page_name] = marker

                row._kagestream_page_name = page_name
                self._rows[page_name] = row

            if is_sub:
                box.set_margin_start(18)
            else:
                box.set_margin_start(4)

            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_end(10)
            row.add(box)
            listbox.add(row)

        listbox.connect("row-selected", self._on_row_selected)
        # row-activated couvre le clic et Entrée ; row-selected couvre la
        # navigation au clavier. Les deux mènent à la même page.
        listbox.connect("row-activated", self._on_row_selected)
        stack.connect("notify::visible-child-name", self._on_stack_page_changed)

        # Les managers notifient déjà via GLib.idle_add : brancher les pastilles
        # dessus évite un second minuteur.
        window.capture_manager.add_listener(self.refresh_badges)
        window.download_manager.add_listener(self.refresh_badges)

        listbox.show_all()
        for marker in self._badges.values():
            marker.hide()
        self.refresh_badges()

    # ------------------------------------------------------------------
    def _on_row_selected(self, _listbox, row):
        if row is None:
            return
        page_name = getattr(row, "_kagestream_page_name", None)
        if page_name:
            self.stack.set_visible_child_name(page_name)

    def _on_stack_page_changed(self, stack_widget, _param):
        row = self._rows.get(stack_widget.get_visible_child_name())
        if row is not None:
            self.listbox.select_row(row)

    # ------------------------------------------------------------------
    def _capture_alert(self):
        for job in self.window.capture_manager.jobs:
            if getattr(job, "stream_health", "") in ("problème détecté", "instable"):
                return True
        return False

    def _set_badge(self, page_name, text, warning=False):
        marker = self._badges.get(page_name)
        if marker is None:
            return

        context = marker.get_style_context()
        if warning:
            context.add_class("badge-warning")
        else:
            context.remove_class("badge-warning")

        if not text:
            marker.hide()
            return

        marker.set_text(str(text))
        marker.show()

    def refresh_badges(self):
        """Met à jour les compteurs affichés dans la navigation."""
        captures = sum(
            1 for job in self.window.capture_manager.jobs
            if job.state.value in CAPTURE_ACTIVE_STATES
        )
        self._set_badge("captures", captures, warning=self._capture_alert())

        downloads = sum(
            1 for job in self.window.download_manager.jobs
            if job.state.value in DOWNLOAD_ACTIVE_STATES
        )
        self._set_badge("downloads", downloads)

        self._set_badge("tools_logs", "!" if self._capture_alert() else "", warning=True)
        return False
