from kagestream.media.ytdlp import analyze_url
from kagestream.metadata.models import album_info_from_ytdlp_json


class MusicProvider:
    id = "base"
    label = "Générique"

    def matches(self, url):
        raise NotImplementedError

    def analyze(self, url, ytdlp_path, js_runtime_name=None, js_runtime_path=None, log_callback=None):
        raise NotImplementedError


class YtdlpMusicProvider(MusicProvider):
    """Provider basé exclusivement sur yt-dlp : YouTube Music, SoundCloud et
    Bandcamp n'ont besoin que de leur détection d'URL, yt-dlp gère déjà
    l'extraction des trois — aucune API officielle requise pour l'analyse."""

    def analyze(self, url, ytdlp_path, js_runtime_name=None, js_runtime_path=None, log_callback=None):
        data, error = analyze_url(
            ytdlp_path,
            url,
            js_runtime_name,
            js_runtime_path,
            allow_playlist=True,
            log_callback=log_callback,
        )
        if not data:
            return None, error

        return album_info_from_ytdlp_json(data, self.id, url), ""


_PROVIDERS = []


def register(provider):
    _PROVIDERS.append(provider)
    return provider


def find_provider(url):
    for provider in _PROVIDERS:
        if provider.matches(url):
            return provider
    return None
