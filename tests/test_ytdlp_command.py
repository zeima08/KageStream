import os
import unittest

from kagestream.media.ytdlp_command import (
    YtdlpTools,
    build_ytdlp_command,
    youtube_output_template,
)

BASE_CONFIG = {
    "source_mode": "youtube_video",
    "resolution": "best",
    "container": "mkv",
    "subtitles": "none",
    "auto_subs": False,
    "embed_subs": False,
    "embed_metadata": True,
    "embed_thumbnail": True,
    "write_infojson": False,
    "filename": "",
}


def make_tools(**overrides):
    values = {
        "ytdlp": "/usr/bin/yt-dlp",
        "ffmpeg": "/usr/bin/ffmpeg",
        "aria2c": None,
        "javascript_runtime_name": "deno",
        "javascript_runtime_path": "/usr/bin/deno",
    }
    values.update(overrides)
    return YtdlpTools(**values)


class YtdlpCommandTests(unittest.TestCase):
    def build(self, config=None, tools=None, url="https://www.youtube.com/watch?v=x"):
        merged = dict(BASE_CONFIG)
        merged.update(config or {})
        return build_ytdlp_command(url, "/tmp/out", merged, tools or make_tools())

    def test_url_is_last_and_separated(self):
        cmd = self.build()
        self.assertEqual(cmd[-2:], ["--", "https://www.youtube.com/watch?v=x"])

    def test_best_resolution_selector(self):
        cmd = self.build()
        self.assertEqual(cmd[cmd.index("--format") + 1], "bestvideo*+bestaudio/best")

    def test_bounded_resolution_selector(self):
        cmd = self.build({"resolution": "1080"})
        selector = cmd[cmd.index("--format") + 1]
        self.assertIn("height<=1080", selector)

    def test_container_drives_merge_and_remux(self):
        cmd = self.build({"container": "mp4"})
        self.assertEqual(cmd[cmd.index("--merge-output-format") + 1], "mp4")
        self.assertEqual(cmd[cmd.index("--remux-video") + 1], "mp4")

    def test_playlist_flag(self):
        cmd = self.build({"source_mode": "youtube_playlist"})
        self.assertIn("--yes-playlist", cmd)

    def test_live_from_start(self):
        cmd = self.build({"source_mode": "youtube_live_start"})
        self.assertIn("--live-from-start", cmd)

    def test_javascript_runtime_forwarded(self):
        cmd = self.build()
        self.assertEqual(cmd[cmd.index("--js-runtimes") + 1], "deno:/usr/bin/deno")

    def test_ffmpeg_location_forwarded(self):
        cmd = self.build()
        self.assertEqual(cmd[cmd.index("--ffmpeg-location") + 1], "/usr/bin")

    def test_aria2c_optional(self):
        self.assertNotIn("--external-downloader", self.build())
        cmd = self.build(tools=make_tools(aria2c="/usr/bin/aria2c"))
        self.assertEqual(cmd[cmd.index("--external-downloader") + 1], "/usr/bin/aria2c")

    def test_subtitles_all(self):
        cmd = self.build({"subtitles": "all"})
        self.assertIn("--write-subs", cmd)
        self.assertEqual(cmd[cmd.index("--sub-langs") + 1], "all,-live_chat")
        self.assertIn("--write-auto-subs", cmd)

    def test_subtitles_single_language_with_embedding(self):
        cmd = self.build({"subtitles": "fr", "embed_subs": True})
        self.assertEqual(cmd[cmd.index("--sub-langs") + 1], "fr")
        self.assertIn("--embed-subs", cmd)
        self.assertNotIn("--write-auto-subs", cmd)

    def test_metadata_and_thumbnail_toggles(self):
        cmd = self.build({"embed_metadata": False, "embed_thumbnail": False})
        self.assertNotIn("--embed-metadata", cmd)
        self.assertNotIn("--embed-thumbnail", cmd)

    def test_info_json_embedded_only_for_mkv(self):
        mkv = self.build({"write_infojson": True, "container": "mkv"})
        self.assertIn("--embed-info-json", mkv)
        mp4 = self.build({"write_infojson": True, "container": "mp4"})
        self.assertIn("--write-info-json", mp4)
        self.assertNotIn("--embed-info-json", mp4)

    def test_cookies_only_for_youtube_and_when_asked(self):
        youtube = self.build()
        self.assertNotIn("--cookies-from-browser", youtube)
        with_cookie = self.build(tools=make_tools(cookies_browser="firefox"))
        self.assertEqual(
            with_cookie[with_cookie.index("--cookies-from-browser") + 1], "firefox"
        )
        other_site = self.build(url="https://soundcloud.com/x", tools=make_tools(cookies_browser="firefox"))
        self.assertNotIn("--cookies-from-browser", other_site)

    def test_explicit_cookies_override_tools_default(self):
        cmd = self.build(tools=make_tools(cookies_browser="firefox"),
                         url="https://www.youtube.com/watch?v=x")
        cmd = build_ytdlp_command(
            "https://www.youtube.com/watch?v=x", "/tmp/out",
            dict(BASE_CONFIG), make_tools(cookies_browser="firefox"), "chrome",
        )
        self.assertEqual(cmd[cmd.index("--cookies-from-browser") + 1], "chrome")

    def test_final_marker_present(self):
        cmd = self.build()
        self.assertIn("after_move:KAGESTREAM_FINAL:%(filepath)s", cmd)


class OutputTemplateTests(unittest.TestCase):
    def test_playlist_template_keeps_index(self):
        template = youtube_output_template("/tmp", "nom", is_playlist=True)
        self.assertIn("%(playlist_index)03d", template)

    def test_literal_percent_is_escaped(self):
        template = youtube_output_template("/tmp", "100% pur")
        self.assertIn("100%% pur", template)

    def test_default_template_uses_title_and_id(self):
        template = youtube_output_template("/tmp", "")
        self.assertIn("%(title).120s", template)
        self.assertIn("%(id)s", template)


if __name__ == "__main__":
    unittest.main()
