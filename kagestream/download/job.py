from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class JobState(Enum):
    EN_ATTENTE = "En attente"
    ANALYSE = "Analyse"
    TELECHARGEMENT = "Téléchargement"
    CONVERSION = "Conversion"
    TERMINE = "Terminé"
    ANNULE = "Annulé"
    ERREUR = "Erreur"


@dataclass
class TrackJob:
    track: object  # kagestream.metadata.models.TrackInfo
    selected: bool = True
    state: JobState = JobState.EN_ATTENTE
    progress_percent: float = 0.0
    error: str = ""
    final_path: str = ""


@dataclass
class DownloadJob:
    id: str
    album: object  # kagestream.metadata.models.AlbumInfo
    destination_root: str
    format_id: Optional[str]
    quality: str
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    tracks: List[TrackJob] = field(default_factory=list)
    state: JobState = JobState.EN_ATTENTE
    cancel_requested: bool = False
    process: object = None
    error: str = ""

    @property
    def selected_tracks(self):
        return [track_job for track_job in self.tracks if track_job.selected]

    @property
    def total_selected(self):
        return len(self.selected_tracks)

    @property
    def completed_count(self):
        return sum(1 for track_job in self.selected_tracks if track_job.state == JobState.TERMINE)
