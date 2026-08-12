import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

# (libellé affiché, nom de la page dans le Gtk.Stack, indentation "sous-item")
SIDEBAR_ENTRIES = [
    ("Capturer", "capture", False),
    ("Musique", "music", False),
    ("YouTube", "youtube", False),
    ("Téléchargements", "downloads", False),
    ("Outils", None, False),
    ("Dépendances", "tools_deps", True),
    ("Diagnostic", "tools_diag", True),
    ("Logs", "tools_logs", True),
]


def build_sidebar(stack):
    """Construit la barre latérale de navigation et la relie au Gtk.Stack fourni."""
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_size_request(190, -1)

    listbox = Gtk.ListBox()
    listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    scroller.add(listbox)

    row_by_page = {}
    first_row = None

    for label, page_name, indented in SIDEBAR_ENTRIES:
        row = Gtk.ListBoxRow()
        text = Gtk.Label(xalign=0)
        if page_name is None:
            text.set_markup(f"<b>{label}</b>")
            row.set_selectable(False)
            row.set_activatable(False)
        else:
            text.set_text(("    " if indented else "") + label)

        text.set_margin_top(6)
        text.set_margin_bottom(6)
        text.set_margin_start(12 if not indented else 22)
        text.set_margin_end(12)
        row.add(text)
        listbox.add(row)

        if page_name is not None:
            row_by_page[page_name] = row
            if first_row is None:
                first_row = row
            row._kagestream_page_name = page_name

    def on_row_selected(_listbox, row):
        if row is None:
            return
        page_name = getattr(row, "_kagestream_page_name", None)
        if page_name:
            stack.set_visible_child_name(page_name)

    def on_stack_page_changed(stack_widget, _param):
        page_name = stack_widget.get_visible_child_name()
        row = row_by_page.get(page_name)
        if row is not None:
            listbox.select_row(row)

    listbox.connect("row-selected", on_row_selected)
    stack.connect("notify::visible-child-name", on_stack_page_changed)

    # Ne pas sélectionner de ligne ici : le Gtk.Stack n'a pas encore ses
    # pages (ajoutées après l'appel à build_sidebar). C'est l'appelant qui
    # fixe la page visible initiale une fois toutes les pages construites ;
    # le handler notify::visible-child-name met alors la sidebar à jour.
    listbox.show_all()
    return scroller
