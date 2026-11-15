import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from kagestream.app import KageStreamWindow


def main():
    win = KageStreamWindow()
    # L'arrêt des sous-processus à la fermeture est géré par KageStreamWindow
    # (signal "destroy" -> shutdown puis Gtk.main_quit).
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
