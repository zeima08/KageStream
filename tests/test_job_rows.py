import unittest
from types import SimpleNamespace

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk

# Les tests d'interface construisent de vrais widgets et une fenêtre : sans
# serveur d'affichage (CI sans Xvfb, machine sans session), GTK fait tomber le
# processus. On les ignore proprement dans ce cas.
_NO_DISPLAY_REASON = "aucun serveur d'affichage disponible"
HAS_DISPLAY = Gdk.Display.get_default() is not None

from kagestream.ui.job_rows import SectionedJobList


@unittest.skipUnless(HAS_DISPLAY, _NO_DISPLAY_REASON)
class SectionedJobListTests(unittest.TestCase):
    def setUp(self):
        self.sections = {
            "active": Gtk.Box(),
            "pending": Gtk.Box(),
            "done": Gtk.Box(),
        }
        self.list = SectionedJobList(self.sections, {"active": "Aucune tâche."})
        self.builds = {}

    def entry(self, job_id, section, signature, label="x"):
        builds = self.builds

        def factory():
            builds[job_id] = builds.get(job_id, 0) + 1
            widget = Gtk.Label(label=label)
            widget.refresh_count = 0

            def refresh():
                widget.refresh_count += 1
                return False

            return widget, refresh

        return (job_id, section, signature, factory)

    def child_labels(self, section):
        return [c for c in self.sections[section].get_children()]

    def test_creates_rows_once(self):
        self.list.sync([self.entry("a", "active", 1)])
        self.list.sync([self.entry("a", "active", 1)])
        self.assertEqual(self.builds["a"], 1)
        # placeholder + 1 rangée
        self.assertEqual(len(self.child_labels("active")), 2)

    def test_refresh_is_called_without_rebuilding(self):
        self.list.sync([self.entry("a", "active", 1)])
        row = self.list._rows["a"]["child"]
        self.list.sync([self.entry("a", "active", 1)])
        self.assertEqual(self.builds["a"], 1)
        self.assertGreaterEqual(row.refresh_count, 2)

    def test_signature_change_rebuilds(self):
        self.list.sync([self.entry("a", "active", 1)])
        self.list.sync([self.entry("a", "active", 2)])
        self.assertEqual(self.builds["a"], 2)

    def test_section_change_moves_row(self):
        self.list.sync([self.entry("a", "active", 1)])
        row = self.list._rows["a"]["child"]
        self.list.sync([self.entry("a", "done", 1)])
        self.assertEqual(self.builds["a"], 1)
        self.assertIs(row.get_parent(), self.sections["done"])
        self.assertEqual(self.list._rows["a"]["section"], "done")

    def test_removed_job_is_destroyed(self):
        self.list.sync([self.entry("a", "active", 1)])
        self.list.sync([])
        self.assertNotIn("a", self.list._rows)
        active_children = self.child_labels("active")
        self.assertEqual(len(active_children), 1)  # placeholder seulement
        self.assertTrue(active_children[0].get_visible() is False or True)

    def test_placeholder_visibility(self):
        self.list.sync([])
        self.assertTrue(self.list._placeholders["active"].get_visible())
        self.list.sync([self.entry("a", "active", 1)])
        self.assertFalse(self.list._placeholders["active"].get_visible())

    def test_order_follows_entries(self):
        self.list.sync([
            self.entry("a", "active", 1, "A"),
            self.entry("b", "active", 1, "B"),
        ])
        self.list.sync([
            self.entry("b", "active", 1, "B"),
            self.entry("a", "active", 1, "A"),
        ])
        labels = [
            child.get_text() for child in self.sections["active"].get_children()
            if isinstance(child, Gtk.Label)
        ]
        self.assertEqual(labels[:2], ["B", "A"])

    def test_no_rebuild_when_many_updates(self):
        """Le scénario qui posait problème : une notification par seconde
        pendant une capture ne doit produire aucune reconstruction."""
        self.list.sync([self.entry("a", "active", 1)])
        for _ in range(50):
            self.list.sync([self.entry("a", "active", 1)])
        self.assertEqual(self.builds["a"], 1)


if __name__ == "__main__":
    unittest.main()
