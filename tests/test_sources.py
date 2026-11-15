import unittest
from unittest.mock import patch

from kagestream.media.sources import (
    direct_source_filename,
    is_twitch_url,
    streamlink_codec_args,
    streamlink_header_args,
)


class TwitchDetectionTests(unittest.TestCase):
    def test_twitch_hosts(self):
        for url in ("https://www.twitch.tv/x", "https://twitch.tv/x", "http://player.twitch.tv/?x"):
            with self.subTest(url=url):
                self.assertTrue(is_twitch_url(url))

    def test_other_hosts(self):
        for url in ("https://notwitch.tv/x", "https://twitch.tv.exemple.org/x", "", "pas une url"):
            with self.subTest(url=url):
                self.assertFalse(is_twitch_url(url))


class StreamlinkArgsTests(unittest.TestCase):
    def test_headers_spoofed_for_non_twitch(self):
        args = streamlink_header_args("https://iptv.example.com/live.m3u8")
        self.assertIn("--http-header", args)
        self.assertIn("User-Agent=curl/8.22.0", args)
        self.assertIn("Accept=*/*", args)

    def test_twitch_keeps_default_headers(self):
        self.assertEqual(streamlink_header_args("https://www.twitch.tv/x"), [])

    def test_codec_args_only_for_twitch(self):
        self.assertEqual(streamlink_codec_args("https://iptv.example.com/x", "h264", "8.1.0"), [])

    def test_codec_preference_mapping(self):
        cases = {
            "h264": "h264",
            "av1": "h264,av1",
            "all": "h264,h265,av1",
            None: "h264",
            "inconnu": "h264",
        }
        for preference, expected in cases.items():
            with self.subTest(preference=preference):
                args = streamlink_codec_args("https://www.twitch.tv/x", preference, "8.1.0")
                self.assertEqual(args, ["--twitch-supported-codecs", expected])

    def test_codec_args_disabled_before_streamlink_8(self):
        self.assertEqual(streamlink_codec_args("https://www.twitch.tv/x", "all", "7.6.0"), [])
        # Version inconnue : on laisse passer (pas de blocage arbitraire).
        self.assertTrue(streamlink_codec_args("https://www.twitch.tv/x", "all", ""))


class DirectFilenameTests(unittest.TestCase):
    def test_filename_from_path(self):
        self.assertEqual(
            direct_source_filename("https://cdn.example.com/vod/film%20noir.mp4?token=1"),
            "film noir.mp4",
        )

    def test_empty_url_is_safe(self):
        self.assertEqual(direct_source_filename(""), "")

    def test_unsafe_characters_are_sanitized(self):
        self.assertNotIn("/", direct_source_filename("https://x.example/a/b:c*?.ts"))


if __name__ == "__main__":
    unittest.main()
