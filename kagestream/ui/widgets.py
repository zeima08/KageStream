"""Briques d'interface partagées par toutes les pages.

Elles fixent une fois pour toutes l'échelle d'espacement, la hiérarchie des
titres, l'association libellé/champ (mnémoniques) et la validation par Entrée,
au lieu de les répéter — avec des valeurs divergentes — dans chaque page.
"""

import inspect

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from kagestream.ui.theme import PAGE_MARGIN, PAGE_SPACING, ROW_SPACING, SECTION_SPACING


def _invoke(callback, widget):
    """Appelle une callback de clic avec le bouton si elle l'attend, sans
    argument sinon.

    Les gestionnaires existants prennent un paramètre (signature GTK
    `clicked`), tandis que les lambdas des pages n'en prennent aucun. Appeler
    systématiquement l'un ou l'autre casse l'autre moitié des boutons."""
    try:
        parameters = inspect.signature(callback).parameters
    except (TypeError, ValueError):
        return callback(widget)

    positional = [
        parameter for parameter in parameters.values()
        if parameter.kind in (parameter.POSITIONAL_ONLY,
                              parameter.POSITIONAL_OR_KEYWORD,
                              parameter.VAR_POSITIONAL)
        # Un paramètre avec valeur par défaut est optionnel : les lambdas du
        # genre `lambda j=job: ...` ne doivent pas recevoir le bouton.
        and (parameter.default is inspect.Parameter.empty
             or parameter.kind == parameter.VAR_POSITIONAL)
    ]
    return callback(widget) if positional else callback()


def _themed(widget, *classes):
    for name in classes:
        widget.get_style_context().add_class(name)
    return widget


def page_title(text):
    label = Gtk.Label(label=text, xalign=0)
    return _themed(label, "page-title")


def page_subtitle(text):
    label = Gtk.Label(label=text, xalign=0)
    label.set_line_wrap(True)
    return _themed(label, "page-subtitle")


def muted_label(text=""):
    label = Gtk.Label(label=text, xalign=0)
    label.set_line_wrap(True)
    return _themed(label, "muted")


def badge(text=""):
    label = Gtk.Label(label=text)
    return _themed(label, "badge")


def page_container(title, subtitle=None, scrollable=True):
    """Construit le cadre commun d'une page : titre, sous-titre facultatif et
    zone de contenu défilante avec des marges identiques partout.

    Retourne (outer, content) : `outer` est à insérer dans le Gtk.Stack,
    `content` est la boîte verticale où empiler le reste."""
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PAGE_SPACING)
    content.set_margin_top(PAGE_MARGIN)
    content.set_margin_bottom(PAGE_MARGIN)
    content.set_margin_start(PAGE_MARGIN)
    content.set_margin_end(PAGE_MARGIN)

    header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    header.pack_start(page_title(title), False, False, 0)
    if subtitle:
        header.pack_start(page_subtitle(subtitle), False, False, 0)
    content.pack_start(header, False, False, 0)

    if scrollable:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(content)
        outer.pack_start(scroller, True, True, 0)
    else:
        outer.pack_start(content, True, True, 0)

    return outer, content


def section(title=None):
    """Carte de section, remplaçant les Gtk.Frame aux marges hétérogènes.

    Retourne la boîte verticale à remplir ; le titre est déjà ajouté."""
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SECTION_SPACING)
    _themed(card, "card")

    if title:
        label = Gtk.Label(label=title.upper(), xalign=0)
        _themed(label, "section-title")
        card.pack_start(label, False, False, 0)

    return card


def form_grid():
    return Gtk.Grid(column_spacing=18, row_spacing=ROW_SPACING)


def add_row(grid, row, label_text, widget, tooltip=None):
    """Ajoute une ligne de formulaire avec un libellé associé au champ.

    Si le libellé ne contient pas déjà « _ », la mnémonique est placée sur le
    premier caractère : Alt+lettre amène le focus sur le champ, et les
    lecteurs d'écran disposent d'une relation libellé/champ explicite.

    `tooltip` est volontairement ignoré : un bug GTK 3 connu
    (https://gitlab.gnome.org/GNOME/gtk/-/issues/1785) empêche un menu
    déroulant de s'ouvrir lorsqu'une infobulle est affichée au même moment —
    la cause exacte du « les menus ne s'ouvrent plus » constaté. L'aide reste
    dans les textes sous les formulaires."""
    text = label_text if "_" in label_text else "_" + label_text
    label = Gtk.Label(label=text, xalign=0)
    label.set_use_underline(True)
    label.set_mnemonic_widget(widget)
    grid.attach(label, 0, row, 1, 1)
    grid.attach(widget, 1, row, 1, 1)
    return label


def bind_enter(entry, callback):
    """Valide le champ avec Entrée — le geste naturel après avoir collé une URL."""
    entry.connect("activate", lambda widget: _invoke(callback, widget))
    return callback


def button(text, callback=None, tooltip=None, primary=False, destructive=False):
    widget = Gtk.Button(label=text)
    # Sans halign START, un bouton placé dans une boîte verticale est étiré
    # sur toute la largeur (halign vaut FILL par défaut).
    widget.set_halign(Gtk.Align.START)
    if primary:
        _themed(widget, "suggested-action")
    if destructive:
        _themed(widget, "destructive-action")
    if tooltip:
        # Les boutons n'ouvrent pas de menu : leur infobulle est sans risque.
        widget.set_tooltip_text(tooltip)
    if callback is not None:
        widget.connect("clicked", lambda button: _invoke(callback, button))
    return widget


def action_bar():
    """Barre d'actions propre à une page, collée en bas de celle-ci."""
    bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    _themed(bar, "action-bar")
    return bar


def choose_icon(*candidates):
    """Première icône symbolique disponible dans le thème, ou None.

    Évite l'icône « cassée » sur les thèmes qui ne fournissent pas un nom
    donné (Adwaita, Papirus, etc.)."""
    theme = Gtk.IconTheme.get_default()
    if theme is None:
        return None
    for name in candidates:
        if theme.has_icon(name):
            return name
    return None
