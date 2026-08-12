from urllib.parse import urlparse

from kagestream.providers.base import YtdlpMusicProvider, register


class YouTubeMusicProvider(YtdlpMusicProvider):
    id = "youtube_music"
    label = "YouTube Music"

    def matches(self, url):
        try:
            host = (urlparse(url).hostname or "").lower()
            return host == "music.youtube.com"
        except Exception:
            return False


register(YouTubeMusicProvider())
