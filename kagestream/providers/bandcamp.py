from urllib.parse import urlparse

from kagestream.providers.base import YtdlpMusicProvider, register


class BandcampProvider(YtdlpMusicProvider):
    id = "bandcamp"
    label = "Bandcamp"

    def matches(self, url):
        try:
            host = (urlparse(url).hostname or "").lower()
            return host == "bandcamp.com" or host.endswith(".bandcamp.com")
        except Exception:
            return False


register(BandcampProvider())
