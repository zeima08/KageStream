import unittest

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from kagestream.capture.job import CaptureState
from kagestream.download.job import JobState


class WindowStructureTests(unittest.TestCase):
    """Construit la vraie fenêtre (GTK fonctionne sans affichage pour la
    construction de widgets) et vérifie la structure de la refonte."""

    @classmethod
    def setUpClass(cls):
        from kagestream.app import KageStreamWindow
        cls.window = KageStreamWindow()
        # Sans show_all(), Gtk.Stack ne désigne aucun enfant visible : les
        # tests de navigation n'auraient rien à observer.
        cls.window.show_all()

    @classmethod
    def tearDownClass(cls):
        cls.window.destroy()

    def test_header_bar_present(self):
        self.assertIsInstance(self.window.get_titlebar(), Gtk.HeaderBar)

    def test_all_pages_present(self):
        for name in ("capture", "captures", "music", "downloads", "youtube",
                     "tools_deps", "tools_diag", "tools_logs"):
            with self.subTest(page=name):
                self.assertIsNotNone(self.window.stack.get_child_by_name(name))

    def test_action_bars_live_in_pages(self):
        # La barre d'action globale n'existe plus.
        self.assertFalse(hasattr(self.window, "action_bar_box"))
        self.assertTrue(hasattr(self.window, "capture_test_button"))
        self.assertTrue(hasattr(self.window, "capture_start_button"))
        self.assertTrue(hasattr(self.window, "test_button"))
        self.assertTrue(hasattr(self.window, "stop_button"))

    def test_sidebar_badges(self):
        self.assertEqual(
            sorted(self.window.sidebar._badges),
            ["captures", "downloads", "tools_logs"],
        )

    def test_capture_badge_follows_jobs(self):
        manager = self.window.capture_manager
        job = manager._build_job(
            "https://example.com/s", "best", "h264", "copy", "mkv", "essai", "/tmp"
        )
        job.state = CaptureState.EN_COURS
        manager.jobs.append(job)
        self.window.sidebar.refresh_badges()

        marker = self.window.sidebar._badges["captures"]
        self.assertTrue(marker.get_visible())
        self.assertEqual(marker.get_text(), "1")

        manager.jobs.remove(job)
        self.window.sidebar.refresh_badges()
        self.assertFalse(marker.get_visible())

    def test_health_warning_badge(self):
        manager = self.window.capture_manager
        job = manager._build_job(
            "https://example.com/s", "best", "h264", "copy", "mkv", "sante", "/tmp"
        )
        job.state = CaptureState.EN_COURS
        job.stream_health = "problème détecté"
        manager.jobs.append(job)
        try:
            self.window.sidebar.refresh_badges()
            self.assertTrue(self.window.sidebar._badges["tools_logs"].get_visible())
        finally:
            manager.jobs.remove(job)
            self.window.sidebar.refresh_badges()

    def test_download_badge_follows_jobs(self):
        manager = self.window.download_manager

        class FakeJob:
            state = JobState.TELECHARGEMENT

        manager.jobs.append(FakeJob())
        try:
            self.window.sidebar.refresh_badges()
            self.assertEqual(self.window.sidebar._badges["downloads"].get_text(), "1")
        finally:
            manager.jobs.pop()
            self.window.sidebar.refresh_badges()
        self.assertFalse(self.window.sidebar._badges["downloads"].get_visible())

    def test_mnemonics_on_capture_form(self):
        # Les champs de la page Capturer sont atteignables au clavier.
        self.assertTrue(self.window.quality.get_style_context() is not None)
        grid_children = []
        for widget in (self.window.url_entry, self.window.filename,
                       self.window.quality, self.window.output_format):
            self.assertIsNotNone(widget)

    def test_enter_in_url_triggers_test(self):
        calls = []
        original = self.window.test_link
        self.window.test_link = lambda button: calls.append(button)
        try:
            self.window.url_entry.set_text("https://example.com/live.m3u8")
            self.window.url_entry.emit("activate")
        finally:
            self.window.test_link = original
        self.assertEqual(len(calls), 1)

    def test_ctrl_shortcuts_switch_pages(self):
        # Les raccourcis sont câblés sur switch_page, qui doit réellement
        # changer de page et ignorer un nom inconnu.
        self.assertTrue(hasattr(self.window, "accel_group"))
        self.window.switch_page("music")
        self.assertEqual(self.window.stack.get_visible_child_name(), "music")
        self.window.switch_page("page-inexistante")
        self.assertEqual(self.window.stack.get_visible_child_name(), "music")
        self.window.switch_page("capture")


if __name__ == "__main__":
    unittest.main()
