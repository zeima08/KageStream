import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from kagestream.app import KageStreamWindow


def main():
    win = KageStreamWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
