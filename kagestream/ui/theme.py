"""Feuille de style de KageStream.

Une seule palette : celle du thème GTK courant. Les couleurs sont dérivées de
@theme_selected_bg_color / @theme_fg_color / @theme_bg_color, donc le mode
sombre du bureau est suivi sans réglage supplémentaire. Le CSS ne sert qu'à
donner une échelle d'espacement et une hiérarchie de titres homogènes — pas à
redessiner les widgets natifs.
"""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

# Échelle d'espacement unique, réutilisée par les pages.
PAGE_MARGIN = 18
PAGE_SPACING = 16
SECTION_PADDING = 14
SECTION_SPACING = 10
ROW_SPACING = 10

CSS = """
.page-title {
    font-size: 150%;
    font-weight: 600;
}

.page-subtitle {
    color: alpha(@theme_fg_color, 0.65);
    font-size: 95%;
}

.section-title {
    font-size: 85%;
    font-weight: 600;
    color: alpha(@theme_fg_color, 0.7);
}

.card {
    background-color: alpha(@theme_fg_color, 0.05);
    border-radius: 10px;
    padding: 14px;
}

.muted {
    color: alpha(@theme_fg_color, 0.6);
    font-size: 92%;
}

.badge {
    background-color: @theme_selected_bg_color;
    color: @theme_selected_fg_color;
    border-radius: 10px;
    font-size: 82%;
    font-weight: 600;
    padding: 1px;
    min-width: 18px;
}

.badge-warning {
    background-color: #c64600;
    color: #ffffff;
}

.sidebar-section {
    font-size: 82%;
    font-weight: 600;
    color: alpha(@theme_fg_color, 0.55);
}

.action-bar {
    padding: 12px;
    border-top: 1px solid alpha(@theme_fg_color, 0.12);
}
"""

_provider = None


def load_theme():
    """Installe la feuille de style sur l'écran par défaut. Idempotent."""
    global _provider
    if _provider is not None:
        return _provider

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS.encode("utf-8"))

    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    _provider = provider
    return provider
