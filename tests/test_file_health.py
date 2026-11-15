import os
import subprocess
import sys
import tempfile
import time
import unittest

from kagestream.constants import is_serious_ffmpeg_issue, matches_stream_problem
from kagestream.media.process import open_handle_pids, wait_file_closed


@unittest.skipIf(not os.path.isdir("/proc"), "nécessite /proc (Linux)")
class WaitFileClosedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "capture.ts")
        with open(self.path, "wb") as handle:
            handle.write(b"\x47" * 188)

    def test_missing_file_is_considered_closed(self):
        self.assertTrue(wait_file_closed(os.path.join(self.tmp.name, "absent.ts")))

    def test_empty_path(self):
        self.assertTrue(wait_file_closed(""))

    def test_file_held_open_is_not_reported_closed(self):
        holder = subprocess.Popen(
            [sys.executable, "-c",
             "import sys,time; f=open(sys.argv[1],'wb'); "
             "f.write(b'x'*10); f.flush(); time.sleep(30)",
             self.path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 5
            while not open_handle_pids(self.path) and time.monotonic() < deadline:
                time.sleep(0.05)

            self.assertTrue(open_handle_pids(self.path), "le détenteur n'a pas été détecté")
            started = time.monotonic()
            closed = wait_file_closed(self.path, timeout=1.5, poll_interval=0.1)
            elapsed = time.monotonic() - started
            self.assertFalse(closed, "un fichier encore ouvert a été déclaré fermé")
            self.assertGreaterEqual(elapsed, 1.0)
        finally:
            holder.kill()
            holder.wait()

    def test_file_released_is_reported_closed(self):
        holder = subprocess.Popen(
            [sys.executable, "-c",
             "import sys,time; f=open(sys.argv[1],'ab'); time.sleep(0.4)",
             self.path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        holder.wait()
        self.assertTrue(wait_file_closed(self.path, timeout=3, poll_interval=0.1))


class StreamHealthPatternTests(unittest.TestCase):
    def test_normal_streamlink_progress_is_not_a_problem(self):
        """Sorties normales d'un flux sain : aucune ne doit alerter."""
        for line in (
            "[cli][info] Opening stream: 1080p (hls)",
            "[download][1080p] Written 12.3 MiB / 40.0 MiB (30%)",
            "Segment 12/40 fetched",
            "[cli][info] Retrying in 15 seconds...",
            "available streams: 360p, 720p, 1080p, best",
            "[ffmpeg] Non-monotonous DTS in output stream 0:1",
            "[http] retry attempt 1",
        ):
            with self.subTest(line=line):
                self.assertFalse(matches_stream_problem(line))

    def test_real_incidents_are_detected(self):
        for line in (
            "error while reading HTTP response",
            "Failed to open stream: HTTP Error 403 Forbidden",
            "HTTP Error 404 Not Found",
            "Connection reset by peer",
            "connection timed out",
            "Invalid data found when processing input",
            "packet corrupt",
        ):
            with self.subTest(line=line):
                self.assertTrue(matches_stream_problem(line))

    def test_benign_ffmpeg_warnings_are_not_serious(self):
        for line in (
            "[mpegts @ 0x1] Non-monotonous DTS in output stream 0:1; previous: 12, current: 10",
            "[mpegts @ 0x1] pts has no value",
            "[mpegts @ 0x1] dts < pcr, TS is invalid",
            "timestamp discrepancy 0.02",
        ):
            with self.subTest(line=line):
                self.assertFalse(is_serious_ffmpeg_issue(line))

    def test_real_ffmpeg_issues_are_serious(self):
        for line in (
            "[mpegts @ 0x1] Packet corrupt (stream = 0, dts = 1234)",
            "Invalid timestamp",
            "error while decoding MB 12 34",
            "Invalid data found when processing input",
            "decode_slice_header error",
        ):
            with self.subTest(line=line):
                self.assertTrue(is_serious_ffmpeg_issue(line))


if __name__ == "__main__":
    unittest.main()
