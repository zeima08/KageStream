import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import kagestream.deps.installer as installer


def make_zip(path, members):
    """Crée une archive zip avec les membres {nom: contenu}."""
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


class PlatformSelectionTests(unittest.TestCase):
    def test_linux_x86_64(self):
        with patch.object(installer.sys, "platform", "linux"), \
                patch.object(installer.platform, "machine", return_value="x86_64"):
            self.assertEqual(
                installer.ffmpeg_build_platform(), ("linux64", ".tar.xz", "")
            )

    def test_windows_x86_64(self):
        with patch.object(installer.sys, "platform", "win32"), \
                patch.object(installer.platform, "machine", return_value="AMD64"):
            self.assertEqual(installer.ffmpeg_build_platform(), ("win64", ".zip", ".exe"))

    def test_windows_arm64(self):
        with patch.object(installer.sys, "platform", "win32"), \
                patch.object(installer.platform, "machine", return_value="aarch64"):
            self.assertEqual(
                installer.ffmpeg_build_platform(), ("winarm64", ".zip", ".exe")
            )

    def test_unsupported_platform_is_explicit(self):
        with patch.object(installer.sys, "platform", "darwin"), \
                patch.object(installer.platform, "machine", return_value="x86_64"):
            with self.assertRaises(RuntimeError):
                installer.ffmpeg_build_platform()


class SafeExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_extracts_normal_tree(self):
        archive = os.path.join(self.tmp.name, "ok.zip")
        make_zip(archive, {"root/bin/tool.exe": b"data"})
        destination = os.path.join(self.tmp.name, "out")
        installer.extract_zip_safely(archive, destination)
        self.assertTrue(os.path.isfile(os.path.join(destination, "root/bin/tool.exe")))

    def test_rejects_path_traversal(self):
        archive = os.path.join(self.tmp.name, "bad.zip")
        make_zip(archive, {"../evade.txt": b"data"})
        destination = os.path.join(self.tmp.name, "out")
        os.makedirs(destination)
        with self.assertRaises(RuntimeError):
            installer.extract_zip_safely(archive, destination)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "evade.txt")))


class WindowsFfmpegInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin_dir = self.tmp.name

    def _run(self, archive_name, digest="abc123"):
        release = {
            "assets": [
                {"name": archive_name, "digest": f"sha256:{digest}",
                 "browser_download_url": "https://example.invalid/ffmpeg.zip"},
            ]
        }

        def fake_download(url, destination, expected, label, progress, timeout):
            make_zip(destination, {
                "ffmpeg-n8.0-latest-win64-gpl-8.0/bin/ffmpeg.exe": b"MZffmpeg",
                "ffmpeg-n8.0-latest-win64-gpl-8.0/bin/ffprobe.exe": b"MZffprobe",
            })
            return expected

        with patch.object(installer.sys, "platform", "win32"), \
                patch.object(installer.platform, "machine", return_value="AMD64"), \
                patch.object(installer, "user_bin_dir", return_value=self.bin_dir), \
                patch.object(installer, "github_latest_release", return_value=release), \
                patch.object(installer, "download_verified_file", side_effect=fake_download), \
                patch.object(installer.subprocess, "run",
                             return_value=subprocess.CompletedProcess([], 0, "ffmpeg version 8.0", "")):
            return installer.download_ffmpeg_binaries()

    def test_installs_exe_names(self):
        path, version, checksum = self._run(
            "ffmpeg-n8.0-latest-win64-gpl-8.0.zip"
        )
        self.assertTrue(path.endswith("ffmpeg.exe"))
        self.assertTrue(os.path.isfile(os.path.join(self.bin_dir, "ffmpeg.exe")))
        self.assertTrue(os.path.isfile(os.path.join(self.bin_dir, "ffprobe.exe")))
        self.assertIn("ffmpeg version", version)
        self.assertEqual(checksum, "abc123")

    def test_linux_archive_name_is_not_selected_on_windows(self):
        with self.assertRaises(RuntimeError):
            self._run("ffmpeg-n8.0-latest-linux64-gpl-8.0.tar.xz")


class WindowsStreamlinkInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin_dir = self.tmp.name

    def test_installs_portable_build(self):
        release = {
            "assets": [
                {"name": "streamlink-8.6.3-1-py315-x86_64.zip",
                 "digest": "sha256:deadbeef",
                 "browser_download_url": "https://example.invalid/x86_64.zip"},
                {"name": "streamlink-8.6.3-1-py315-aarch64.zip",
                 "digest": "sha256:other",
                 "browser_download_url": "https://example.invalid/aarch64.zip"},
            ]
        }

        def fake_download(url, destination, expected, label, progress, timeout):
            self.assertIn("x86_64", url)
            make_zip(destination, {
                "streamlink-8.6.3-1-py315-x86_64/streamlink.exe": b"MZstreamlink",
                "streamlink-8.6.3-1-py315-x86_64/_internal/lib.dll": b"dll",
            })
            return expected

        with patch.object(installer.sys, "platform", "win32"), \
                patch.object(installer.platform, "machine", return_value="AMD64"), \
                patch.object(installer, "user_bin_dir", return_value=self.bin_dir), \
                patch.object(installer, "github_latest_release", return_value=release), \
                patch.object(installer, "download_verified_file", side_effect=fake_download), \
                patch.object(installer.subprocess, "run",
                             return_value=subprocess.CompletedProcess([], 0, "streamlink 8.6.3", "")):
            path, version, checksum = installer.download_streamlink_portable()

        self.assertTrue(path.endswith("streamlink.exe"))
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(os.path.isdir(os.path.join(self.bin_dir, "_internal")))
        self.assertEqual(version, "streamlink 8.6.3")
        self.assertEqual(checksum, "deadbeef")

    def test_dispatch_from_appimage_entry_point(self):
        with patch.object(installer.sys, "platform", "win32"), \
                patch.object(installer, "download_streamlink_portable",
                             return_value=("p", "v", "c")) as portable:
            self.assertEqual(installer.download_streamlink_appimage(), ("p", "v", "c"))
            portable.assert_called_once()


if __name__ == "__main__":
    unittest.main()
