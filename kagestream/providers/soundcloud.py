from urllib.parse import urlparse

from kagestream.providers.base import YtdlpMusicProvider, register


class SoundCloudProvider(YtdlpMusicProvider):
    id = "soundcloud"
    label = "SoundCloud"

    def matches(self, url):
        try:
            host = (urlparse(url).hostname or "").lower()
            return host == "snd.sc" or host == "soundcloud.com" or host.endswith(".soundcloud.com")
        except Exception:
            return False


register(SoundCloudProvider())
