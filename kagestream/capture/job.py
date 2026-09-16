from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CaptureState(Enum):
    EN_ATTENTE = "En attente"
    EN_COURS = "Enregistrement"
    RECONNEXION = "Reconnexion"
    EN_ATTENTE_REMUX = "En attente de remux"
    DECISION_REMUX = "Vérifier ou remuxer ?"
    VERIFICATION = "Vérification du TS"
    DECISION_POST_VERIF = "Continuer le remux ?"
    REMUX = "Remux"
    DECISION_MKV = "Remuxer en MKV ?"
    CONVERSION = "Conversion"
    TERMINE = "Terminé"
    ANNULE = "Annulé"
    ERREUR = "Erreur"


@dataclass
class CaptureJob:
    id: str
    label: str
    url: str
    quality: str
    twitch_preference: str
    profile: str
    output_format: str
    filename: str
    folder: str
    schedule_start: Optional[float] = None
    schedule_end: Optional[float] = None
    state: CaptureState = CaptureState.EN_ATTENTE
    process: object = None
    cancel_requested: bool = False
    schedule_cancelled: bool = False
    current_ts_file: str = ""
    final_file: str = ""
    cut_file: str = ""
    recording_start: Optional[float] = None
    active_backend: str = ""
    stream_health: str = "Non analysé"
    last_health_report: str = ""
    stream_warning_count: int = 0
    last_ts_analysis: dict = field(default_factory=dict)
    error: str = ""
    pending_ts_file: str = ""
    pending_fmt: str = ""
