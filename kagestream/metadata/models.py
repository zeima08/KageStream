from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TrackInfo:
    index: int
    title: str
    url: str
    artist: str = ""
    duration: Optional[float] = None
    id: str = ""


@dataclass
class AlbumInfo:
    provider: str
    source_url: str
    title: str
    artist: str = ""
    year: str = ""
    genre: str = ""
    artwork_url: str = ""
    tracks: List[TrackInfo] = field(default_factory=list)


def album_info_from_ytdlp_json(data, provider_id, source_url):
    """Convertit le JSON `yt-dlp --dump-single-json` (morceau ou playlist/album)
    en AlbumInfo/TrackInfo, quel que soit le site d'origine."""
    is_playlist = data.get("_type") == "playlist" or "entries" in data

    if is_playlist:
        entries = [entry for entry in (data.get("entries") or []) if entry]
        artist = data.get("uploader") or data.get("channel") or data.get("artist") or ""
        if not artist and entries:
            first_entry = entries[0]
            artist = (
                first_entry.get("artist")
                or first_entry.get("album_artist")
                or first_entry.get("uploader")
                or ""
            )
        tracks = []
        for position, entry in enumerate(entries, start=1):
            tracks.append(TrackInfo(
                index=entry.get("playlist_index") or position,
                title=entry.get("title") or f"Piste {position}",
                url=entry.get("webpage_url") or entry.get("original_url") or entry.get("url") or "",
                artist=entry.get("artist") or entry.get("uploader") or artist,
                duration=entry.get("duration"),
                id=str(entry.get("id") or ""),
            ))
        year = str(data.get("release_year") or "")[:4]
        return AlbumInfo(
            provider=provider_id,
            source_url=source_url,
            title=data.get("title") or "Album",
            artist=artist,
            year=year,
            genre=data.get("genre") or "",
            artwork_url=data.get("thumbnail") or "",
            tracks=tracks,
        )

    title = data.get("track") or data.get("title") or "Piste"
    artist = data.get("artist") or data.get("uploader") or data.get("channel") or ""
    album_title = data.get("album") or title
    year = str(data.get("release_year") or data.get("upload_date") or "")[:4]

    return AlbumInfo(
        provider=provider_id,
        source_url=source_url,
        title=album_title,
        artist=artist,
        year=year,
        genre=data.get("genre") or "",
        artwork_url=data.get("thumbnail") or "",
        tracks=[TrackInfo(
            index=int(data.get("track_number") or 1),
            title=title,
            url=data.get("webpage_url") or source_url,
            artist=artist,
            duration=data.get("duration"),
            id=str(data.get("id") or ""),
        )],
    )


FORMAT_CHOICES = [
    ("original", "Original — sans conversion"),
    ("mp3", "MP3"),
    ("aac", "AAC"),
    ("m4a", "M4A"),
    ("opus", "Opus"),
    ("vorbis", "Vorbis (OGG)"),
    ("flac", "FLAC"),
]

# Profils de téléchargement — voir context.md section 6. "quality" suit la
# convention --audio-quality de yt-dlp (0 = meilleur VBR, ou bitrate "192K").
PROFILES = {
    "compatible": {
        "label": "Compatible — MP3 192 kbps",
        "format": "mp3",
        "quality": "192K",
    },
    "qualite_max": {
        "label": "Qualité maximale disponible",
        "format": "original",
        "quality": "0",
    },
    "archivage": {
        "label": "Archivage — FLAC + métadonnées + pochette",
        "format": "flac",
        "quality": "0",
    },
    "custom": {
        "label": "Personnalisé",
        "format": None,
        "quality": "0",
    },
}
