import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from kagestream.media.ytdlp import (
    analysis_error_message,
    analyze_url,
    detect_available_browsers,
    is_bot_check_error,
    is_cookie_copy_failure,
    is_replay_site_url,
    replay_site_label,
    youtube_cookie_args,
)
from kagestream.providers.youtube_music import YouTubeMusicProvider

BOT_CHECK_ERROR = "ERROR: [youtube] abc: Sign in to confirm you’re not a bot. This helps protect our community."


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


class BotCheckDetectionTests(unittest.TestCase):
    def test_bot_check_detected(self):
        self.assertTrue(is_bot_check_error(BOT_CHECK_ERROR))
        # Apostrophe droite ou typographique : même détection.
        self.assertTrue(is_bot_check_error(
            "ERROR: Sign in to confirm you're not a bot."
        ))

    def test_other_errors_are_not_bot_checks(self):
        for text in ("Video unavailable", "Private video", "", None,
                     "Sign in to confirm your age"):
            with self.subTest(text=text):
                self.assertFalse(is_bot_check_error(text))

    def test_cookie_copy_failure_detected(self):
        self.assertTrue(is_cookie_copy_failure(
            "ERROR: could not copy cookies from browser firefox: locked"
        ))
        self.assertFalse(is_cookie_copy_failure("Video unavailable"))


class ReplaySiteRoutingTests(unittest.TestCase):
    def test_replay_hosts_are_detected(self):
        for url in (
            "https://www.arte.tv/fr/video/123-456/xyz/",
            "https://arte.tv/fr/videos/123/",
            "https://www.france.tv/documentaires/xyz.html",
            "https://play.rts.ch/watch/123",
            "https://www.rts.ch/play/tv/direct",
            "https://www.srf.ch/play/tv/video/xyz",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_replay_site_url(url))

    def test_replay_labels(self):
        self.assertEqual(replay_site_label("https://www.arte.tv/fr/"), "Arte")
        self.assertEqual(replay_site_label("https://play.rts.ch/watch/1"), "RTS")
        self.assertEqual(replay_site_label("https://www.france.tv/"), "france.tv")

    def test_non_replay_hosts(self):
        for url in (
            "https://youtube.com/watch?v=x",
            "https://music.youtube.com/watch?v=x",
            "https://soundcloud.com/track",
            "https://dailymotion.com/video/x",
            # Suffixes ressemblants : seul le domaine exact compte.
            "https://arte.tv.example.org/",
            "https://notarte.tv/",
            "https://example.com/",
            "",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_replay_site_url(url))

    def test_replay_urls_get_no_youtube_cookies(self):
        # Les cookies YouTube ne doivent jamais fuiter vers un replay.
        self.assertEqual(
            youtube_cookie_args("https://www.arte.tv/fr/video/1/", "firefox"), []
        )
        self.assertEqual(
            youtube_cookie_args("https://play.rts.ch/watch/1", "chrome"), []
        )


class BrowserDetectionTests(unittest.TestCase):
    def test_firefox_profile_detected_from_home(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".mozilla", "firefox"))
            with patch.dict(os.environ, {"HOME": home}):
                self.assertEqual(detect_available_browsers(), ["firefox"])

    def test_no_browser_without_profile(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.dict(os.environ, {"HOME": home}):
                self.assertEqual(detect_available_browsers(), [])


class AnalysisCookieRetryTests(unittest.TestCase):
    URL = "https://www.youtube.com/watch?v=test"

    def _bot_check_run(self):
        return subprocess.CompletedProcess([], 1, "", BOT_CHECK_ERROR)

    def _success_run(self):
        return subprocess.CompletedProcess([], 0, '{"id": "ok"}', "")

    @patch("kagestream.media.ytdlp.detect_available_browsers", return_value=["firefox"])
    @patch("kagestream.media.ytdlp.subprocess.run")
    def test_bot_check_retries_with_detected_browser(self, run, _browsers):
        run.side_effect = [self._bot_check_run(), self._success_run()]
        data, error = analyze_url("yt-dlp", self.URL)
        self.assertEqual(data, {"id": "ok"})
        self.assertEqual(error, "")
        self.assertEqual(run.call_count, 2)
        second_cmd = run.call_args_list[1].args[0]
        self.assertIn("--cookies-from-browser", second_cmd)
        self.assertEqual(second_cmd[second_cmd.index("--cookies-from-browser") + 1], "firefox")

    @patch("kagestream.media.ytdlp.detect_available_browsers", return_value=[])
    @patch("kagestream.media.ytdlp.subprocess.run")
    def test_no_browser_means_no_retry(self, run, _browsers):
        run.side_effect = [self._bot_check_run()]
        data, error = analyze_url("yt-dlp", self.URL)
        self.assertIsNone(data)
        self.assertIn("not a bot", error)
        self.assertEqual(run.call_count, 1)

    @patch("kagestream.media.ytdlp.detect_available_browsers", return_value=["firefox"])
    @patch("kagestream.media.ytdlp.subprocess.run")
    def test_non_youtube_url_never_gets_cookie_retry(self, run, _browsers):
        run.side_effect = [self._bot_check_run()]
        data, error = analyze_url("yt-dlp", "https://soundcloud.com/track")
        self.assertIsNone(data)
        self.assertEqual(run.call_count, 1)

    @patch("kagestream.media.ytdlp.detect_available_browsers", return_value=["firefox"])
    @patch("kagestream.media.ytdlp.subprocess.run")
    def test_unrelated_error_is_returned_without_retry(self, run, _browsers):
        run.side_effect = [subprocess.CompletedProcess([], 1, "", "ERROR: Video unavailable")]
        data, error = analyze_url("yt-dlp", self.URL)
        self.assertIsNone(data)
        self.assertIn("Video unavailable", error)
        self.assertEqual(run.call_count, 1)

    @patch("kagestream.media.ytdlp.detect_available_browsers", return_value=["firefox"])
    @patch("kagestream.media.ytdlp.subprocess.run")
    def test_successful_forced_retry_reports_browser(self, run, _browsers):
        run.side_effect = [self._bot_check_run(), self._success_run()]
        forced = []
        data, _error = analyze_url("yt-dlp", self.URL, browser_callback=forced.append)
        self.assertEqual(data, {"id": "ok"})
        self.assertEqual(forced, ["firefox"])

    @patch("kagestream.media.ytdlp.detect_available_browsers", return_value=["firefox"])
    @patch("kagestream.media.ytdlp.subprocess.run")
    def test_selected_browser_failure_falls_back_to_detected(self, run, _browsers):
        # Le navigateur choisi dans Outils ne peut pas être lu (profil
        # verrouillé) : on retombe sur le premier navigateur détecté.
        cookie_failure = subprocess.CompletedProcess(
            [], 1, "", "ERROR: could not copy cookies from browser chrome: locked"
        )
        run.side_effect = [cookie_failure, self._success_run()]
        data, error = analyze_url("yt-dlp", self.URL, cookies_browser="chrome")
        self.assertEqual(data, {"id": "ok"})
        self.assertEqual(run.call_count, 2)
        second_cmd = run.call_args_list[1].args[0]
        self.assertEqual(second_cmd[second_cmd.index("--cookies-from-browser") + 1], "firefox")

    @patch("kagestream.media.ytdlp.detect_available_browsers", return_value=["firefox"])
    @patch("kagestream.media.ytdlp.subprocess.run")
    def test_bot_check_persisting_stops_the_loop(self, run, _browsers):
        # Le blocage persiste même avec les cookies : l'utilisateur doit faire
        # la vérification lui-même — on ne boucle pas sur les tentatives.
        run.side_effect = [self._bot_check_run(), self._bot_check_run()]
        data, error = analyze_url("yt-dlp", self.URL)
        self.assertIsNone(data)
        self.assertIn("not a bot", error)
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
