import os
import subprocess
import sys
import tempfile
import unittest

from kagestream.capture.manager import finalize_timeout
from kagestream.media.process import escalate_processes_stop, kill_process_group


def _popen(*args):
    return subprocess.Popen(
        list(args),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=(sys.platform != "win32"),
    )


@unittest.skipIf(sys.platform == "win32", "signaux POSIX uniquement sur ces tests")
class BatchStopTests(unittest.TestCase):
    def test_batch_stop_kills_running_processes(self):
        procs = [_popen("sleep", "60") for _ in range(3)]
        escalate_processes_stop(procs)
        for proc in procs:
            self.assertIsNotNone(proc.poll())

    def test_batch_stop_ignores_none_and_dead_processes(self):
        dead = _popen("true")
        dead.wait()
        # Ne doit ni lever, ni attendre : retour immédiat.
        escalate_processes_stop([None, dead])

    def test_kill_process_group_kills_child_too(self):
        # sh -c 'sleep 60 & sleep 60' : le groupe contient le shell et ses
        # enfants — kill_process_group doit tous les terminer.
        proc = _popen("sh", "-c", "sleep 60 & sleep 60")
        try:
            import time
            time.sleep(0.3)  # laisser les enfants démarrer
            kill_process_group(proc)
            proc.wait(timeout=5)
        finally:
            kill_process_group(proc)
        self.assertIsNotNone(proc.poll())


class FinalizeTimeoutTests(unittest.TestCase):
    def test_timeout_scales_with_file_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "capture.ts")
            with open(path, "wb") as handle:
                handle.truncate(2 * 1024 ** 3)  # 2 Gio creux : instantané
            # base 100 + 60 s/Gio
            self.assertEqual(finalize_timeout(path, 100, 60), 220)

    def test_timeout_falls_back_when_file_missing(self):
        # Fichier absent : marge sur 1 Gio supposé.
        self.assertEqual(finalize_timeout("/inexistant.ts", 100, 60), 160)

    def test_small_files_get_the_base_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mini.ts")
            open(path, "wb").close()
            # Plancher de 0.05 Gio : base 100 + 60 * 0.05 = 103 s.
            self.assertEqual(finalize_timeout(path, 100, 60), 103)


if __name__ == "__main__":
    unittest.main()
