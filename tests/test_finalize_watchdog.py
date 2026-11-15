import os
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import kagestream.capture.manager as capture_manager_module
from kagestream.capture.job import CaptureJob, CaptureState
from kagestream.capture.manager import CaptureManager
from kagestream.media.sources import SourceTools


class LogCollector:
    """Collecte le journal produit par le manager — aucune fenêtre GTK."""

    def __init__(self):
        self.logs = []

    def __call__(self, text):
        self.logs.append(text)


def make_manager(ffmpeg):
    logs = LogCollector()
    manager = CaptureManager(lambda: SourceTools(ffmpeg=ffmpeg), logs)
    return manager, logs


def _make_fake_ffmpeg(directory, body):
    path = os.path.join(directory, "fake-ffmpeg")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def _make_job(folder, filename):
    return CaptureJob(
        id="job-test",
        label=filename,
        url="https://example.com/stream",
        quality="best",
        twitch_preference="h264",
        profile="copy",
        output_format="mkv",
        filename=filename,
        folder=folder,
    )


@unittest.skipIf(sys.platform == "win32", "scripts shell et signaux POSIX")
class FinalizeWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = self.tmp.name

    def _hang_ffmpeg(self):
        # Simule un FFmpeg figé sur un TS corrompu : il ignore ses arguments
        # et ne rend jamais la main de lui-même.
        return _make_fake_ffmpeg(self.folder, "while true; do sleep 1; done")

    def test_stuck_remux_is_killed_and_reported(self):
        ffmpeg = self._hang_ffmpeg()
        manager, _logs = make_manager(ffmpeg)
        ts_file = os.path.join(self.folder, "capture.ts")
        with open(ts_file, "wb") as handle:
            handle.write(b"\x47" * 188 * 10)

        job = _make_job(self.folder, "capture")
        job.current_ts_file = ts_file
        job.final_file = ts_file

        # Délai garde-fou ramené à 1 s pour le test.
        with patch.object(capture_manager_module, "REMUX_TIMEOUT_BASE", 1), \
                patch.object(capture_manager_module, "REMUX_TIMEOUT_PER_GB", 0):
            started = time.monotonic()
            manager._do_remux(job, ts_file, "mkv")
            elapsed = time.monotonic() - started

        # La file ne doit pas rester bloquée : quelques secondes, pas l'infini.
        self.assertLess(elapsed, 15, "le watchdog n'a pas débloqué le remux")
        self.assertEqual(job.state, CaptureState.ERREUR)
        self.assertIn("délai", job.error.lower())
        self.assertIsNone(job.process)
        # Le TS original est conservé.
        self.assertEqual(job.final_file, ts_file)
        self.assertTrue(os.path.exists(ts_file))

    def test_second_finalize_runs_after_a_stuck_one(self):
        """Preuve de bout en bout : après un remux tué par le watchdog, la
        file de finalisation traite la tâche suivante."""
        ffmpeg = self._hang_ffmpeg()
        manager, _logs = make_manager(ffmpeg)

        stuck_ts = os.path.join(self.folder, "stuck.ts")
        with open(stuck_ts, "wb") as handle:
            handle.write(b"\x47" * 188)
        stuck_job = _make_job(self.folder, "stuck")

        marker = os.path.join(self.folder, "second-task-ran")
        second_job = _make_job(self.folder, "second")

        def second_task():
            open(marker, "w").close()

        with patch.object(capture_manager_module, "REMUX_TIMEOUT_BASE", 1), \
                patch.object(capture_manager_module, "REMUX_TIMEOUT_PER_GB", 0):
            manager._finalize_queue.put(
                lambda: manager._do_remux(stuck_job, stuck_ts, "mkv")
            )
            manager._finalize_queue.put(second_task)
            deadline = time.monotonic() + 20
            while not os.path.exists(marker) and time.monotonic() < deadline:
                time.sleep(0.1)

        self.assertTrue(
            os.path.exists(marker),
            "la file de finalisation est restée bloquée sur la tâche figée"
        )

    def test_fast_success_is_not_interrupted(self):
        ffmpeg = _make_fake_ffmpeg(
            self.folder,
            'for arg in "$@"; do last="$arg"; done; echo ok > "$last"',
        )
        manager, _logs = make_manager(ffmpeg)
        ts_file = os.path.join(self.folder, "ok.ts")
        with open(ts_file, "wb") as handle:
            handle.write(b"\x47" * 188)

        job = _make_job(self.folder, "ok")
        with patch.object(capture_manager_module, "REMUX_TIMEOUT_BASE", 30), \
                patch.object(capture_manager_module, "REMUX_TIMEOUT_PER_GB", 0):
            manager._do_remux(job, ts_file, "mkv")

        self.assertEqual(job.state, CaptureState.TERMINE)
        self.assertTrue(job.final_file.endswith(".mkv"))


if __name__ == "__main__":
    unittest.main()
