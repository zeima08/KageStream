import subprocess
import unittest
from unittest.mock import patch

from kagestream.media.ytdlp import (
    analysis_error_message,
    analyze_url,
    youtube_cookie_args,
)
from kagestream.providers.youtube_music import YouTubeMusicProvider


class YouTubeSessionTests(unittest.TestCase):
    def test_cookies_are_opt_in(self):
        self.assertEqual(youtube_cookie_args("https://youtube.com/watch?v=test"), [])

    def test_youtube_domains(self):
        for host in ("www.youtube.com", "music.youtube.com", "youtu.be", "youtube-nocookie.com"):
            with self.subTest(host=host):
                self.assertEqual(
                    youtube_cookie_args(f"https://{host}/watch?v=test", "firefox"),
                    ["--cookies-from-browser", "firefox"],
                )

    def test_other_sites_do_not_receive_cookies(self):
        for host in ("soundcloud.com", "dailymotion.com", "notyoutube.com", "youtube.com.example.org"):
            with self.subTest(host=host):
                self.assertEqual(youtube_cookie_args(f"https://{host}/track", "chrome"), [])

    @patch("kagestream.media.ytdlp.subprocess.run")
    def test_analysis_passes_browser_before_url_separator(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '{"id": "test"}', "")
        url = "https://music.youtube.com/watch?v=test"
        data, error = analyze_url("yt-dlp", url, cookies_browser="firefox")
        self.assertEqual(data, {"id": "test"})
        self.assertEqual(error, "")
        self.assertEqual(run.call_args.args[0][-4:], ["--cookies-from-browser", "firefox", "--", url])

    @patch("kagestream.providers.base.analyze_url")
    def test_music_provider_forwards_browser(self, analyze):
        analyze.return_value = (None, "test error")
        result = YouTubeMusicProvider().analyze(
            "https://music.youtube.com/watch?v=test", "yt-dlp", cookies_browser="chrome"
        )
        self.assertEqual(result, (None, "test error"))
        self.assertEqual(analyze.call_args.kwargs["cookies_browser"], "chrome")
        self.assertTrue(analyze.call_args.kwargs["allow_playlist"])

    def test_bot_error_explains_session_verification(self):
        title, message = analysis_error_message(
            "ERROR: [youtube] test: Sign in to confirm you’re not a bot."
        )
        self.assertEqual(title, "Vérification YouTube requise")
        self.assertIn("Session YouTube", message)

    def test_other_errors_keep_details(self):
        self.assertEqual(analysis_error_message("Video unavailable"), ("Lien non reconnu", "Video unavailable"))
        self.assertEqual(analysis_error_message(None)[0], "Lien non reconnu")


if __name__ == "__main__":
    unittest.main()
