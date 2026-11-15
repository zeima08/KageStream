import unittest

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk

# Les tests d'interface construisent de vrais widgets et une fenêtre : sans
# serveur d'affichage (CI sans Xvfb, machine sans session), GTK fait tomber le
# processus. On les ignore proprement dans ce cas.
_NO_DISPLAY_REASON = "aucun serveur d'affichage disponible"
HAS_DISPLAY = Gdk.Display.get_default() is not None

from kagestream.ui.widgets import (
    action_bar,
    add_row,
    badge,
    bind_enter,
    button,
    form_grid,
    muted_label,
    page_container,
    section,
)


@unittest.skipUnless(HAS_DISPLAY, _NO_DISPLAY_REASON)
class AddRowTests(unittest.TestCase):
    def test_label_is_associated_with_widget(self):
        grid = form_grid()
        entry = Gtk.Entry()
        label = add_row(grid, 0, "Dossier", entry)
        self.assertIs(label.get_mnemonic_widget(), entry)
        self.assertTrue(label.get_use_underline())

    def test_existing_mnemonic_is_preserved(self):
        grid = form_grid()
        entry = Gtk.Entry()
        label = add_row(grid, 0, "Heure de _début", entry)
        self.assertNotEqual(label.get_mnemonic_keyval(), Gdk.KEY_VoidSymbol)
        self.assertIn("début", label.get_text())

    def test_mnemonic_added_when_missing(self):
        grid = form_grid()
        entry = Gtk.Entry()
        label = add_row(grid, 1, "Qualité", entry)
        # GTK retire l'underscore de get_text() : la touche mnémonique est le
        # seul indicateur fiable de sa présence.
        self.assertNotEqual(label.get_mnemonic_keyval(), Gdk.KEY_VoidSymbol)

    def test_label_and_widget_land_on_same_row(self):
        grid = form_grid()
        entry = Gtk.Entry()
        label = add_row(grid, 3, "Lien", entry)
        self.assertEqual(grid.child_get_property(label, "top-attach"), 3)
        self.assertEqual(grid.child_get_property(entry, "top-attach"), 3)
        self.assertEqual(grid.child_get_property(label, "left-attach"), 0)
        self.assertEqual(grid.child_get_property(entry, "left-attach"), 1)


@unittest.skipUnless(HAS_DISPLAY, _NO_DISPLAY_REASON)
class ButtonCallbackTests(unittest.TestCase):
    """Régression : les gestionnaires de la fenêtre attendent un paramètre
    `button`, les lambdas des pages aucun. Le helper doit gérer les deux."""

    class Handler:
        def __init__(self):
            self.received = []

        def with_button(self, button):
            self.received.append(("avec", button))

    def test_method_expecting_button_receives_widget(self):
        handler = self.Handler()
        widget = button("Tester", handler.with_button)
        widget.emit("clicked")
        self.assertEqual(len(handler.received), 1)
        kind, received = handler.received[0]
        self.assertEqual(kind, "avec")
        self.assertIs(received, widget)

    def test_zero_argument_lambda_is_called(self):
        calls = []
        widget = button("Vider", lambda: calls.append(1))
        widget.emit("clicked")
        self.assertEqual(calls, [1])

    def test_optional_parameter_does_not_receive_button(self):
        received = []
        widget = button("x", lambda value="défaut": received.append(value))
        widget.emit("clicked")
        self.assertEqual(received, ["défaut"])

    def test_no_exception_for_both_shapes(self):
        handler = self.Handler()
        for callback in (handler.with_button, lambda: None, lambda b=None: None):
            with self.subTest(callback=callback):
                button("x", callback).emit("clicked")


@unittest.skipUnless(HAS_DISPLAY, _NO_DISPLAY_REASON)
class BindEnterTests(unittest.TestCase):
    def test_activate_triggers_callback(self):
        entry = Gtk.Entry()
        calls = []
        bind_enter(entry, lambda: calls.append(1))
        entry.emit("activate")
        self.assertEqual(calls, [1])


@unittest.skipUnless(HAS_DISPLAY, _NO_DISPLAY_REASON)
class ButtonTests(unittest.TestCase):
    def test_primary_button_has_suggested_class(self):
        widget = button("Enregistrer", primary=True)
        self.assertTrue(widget.get_style_context().has_class("suggested-action"))

    def test_secondary_button_has_no_suggested_class(self):
        widget = button("Tester")
        self.assertFalse(widget.get_style_context().has_class("suggested-action"))

    def test_callback_and_tooltip(self):
        calls = []
        widget = button("Stop", lambda: calls.append(1), tooltip="Arrête le transfert")
        self.assertEqual(widget.get_tooltip_text(), "Arrête le transfert")
        widget.emit("clicked")
        self.assertEqual(calls, [1])


@unittest.skipUnless(HAS_DISPLAY, _NO_DISPLAY_REASON)
class ContainerTests(unittest.TestCase):
    def test_page_container_has_title_and_scrolling(self):
        outer, content = page_container("Capturer", "Sous-titre")
        self.assertIsInstance(outer.get_children()[0], Gtk.ScrolledWindow)
        texts = [
            child.get_text()
            for child in content.get_children()[0].get_children()
            if isinstance(child, Gtk.Label)
        ]
        self.assertIn("Capturer", texts)
        self.assertIn("Sous-titre", texts)

    def test_page_container_without_scrolling(self):
        outer, _content = page_container("Journal", scrollable=False)
        self.assertNotIsInstance(outer.get_children()[0], Gtk.ScrolledWindow)

    def test_section_has_card_class_and_title(self):
        card = section("Format")
        self.assertTrue(card.get_style_context().has_class("card"))
        labels = [c for c in card.get_children() if isinstance(c, Gtk.Label)]
        self.assertTrue(labels)
        self.assertEqual(labels[0].get_text(), "FORMAT")

    def test_action_bar_class(self):
        self.assertTrue(action_bar().get_style_context().has_class("action-bar"))

    def test_muted_and_badge_classes(self):
        self.assertTrue(muted_label("x").get_style_context().has_class("muted"))
        self.assertTrue(badge("3").get_style_context().has_class("badge"))


if __name__ == "__main__":
    unittest.main()
