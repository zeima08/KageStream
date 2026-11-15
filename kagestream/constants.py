import os
import sys

APP_NAME = "KageStream"
APP_AUTHOR = "Zeima"
APP_TITLE = f"{APP_NAME}"

# kagestream/constants.py lives one directory below the project root (where
# kagestream.py and assets/ live), so PROJECT_ROOT must go up one extra level
# compared to the historical single-file layout.
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)

BASE_DIR = getattr(sys, "_MEIPASS", PROJECT_ROOT)
ICON_PATH = os.path.join(BASE_DIR, "assets", "icons", "kagestream.png")

YTDLP_RELEASE_BASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download"
DENO_RELEASE_BASE = "https://github.com/denoland/deno/releases/latest/download"
GITHUB_API_BASE = "https://api.github.com/repos"


# Motifs réellement anormaux dans la sortie de Streamlink/FFmpeg pendant une
# capture. Les mots isolés « segment », « retry », « error », « pts » ou « dts »
# sont volontairement absents : ils apparaissent dans la sortie NORMALE d'un
# flux sain (« Segment 12/40 », « Non-monotonous DTS » bénin) et déclenchaient
# des alertes « instable » sur des enregistrements parfaits.
BAD_STREAM_PATTERNS = [
    "error while",
    "failed to open",
    "failed to read",
    "http error 4",
    "http error 5",
    "403 forbidden",
    "404 not found",
    "connection reset",
    "connection aborted",
    "connection refused",
    "timed out",
    "timeout error",
    "read error",
    "invalid data",
    "corrupt",
]

# Motifs considérés comme sérieux après analyse du fichier produit. Ici aussi
# les jetons seuls (« pts », « dts », « timestamp ») sont exclus : FFmpeg en
# émet sur presque tout TS sans que le fichier soit défectueux. Les compteurs
# de DTS/timestamps restent collectés séparément pour le rapport détaillé.
FFMPEG_HEALTH_PATTERNS = [
    "invalid timestamp",
    "corrupt",
    "packet corrupt",
    "error while decoding",
    "missing picture",
    "invalid data",
    "decode_slice_header error",
    "no frame!",
]


def matches_stream_problem(line):
    """Vrai si la ligne de sortie d'une capture signale un incident réel."""
    lower = (line or "").lower()
    return any(pattern in lower for pattern in BAD_STREAM_PATTERNS)


def is_serious_ffmpeg_issue(line):
    """Vrai si une ligne de l'analyse FFmpeg indique un problème sérieux."""
    lower = (line or "").lower()
    return any(pattern in lower for pattern in FFMPEG_HEALTH_PATTERNS)


RECONNECT_WINDOW_SECONDS = 120
RECONNECT_RETRY_INTERVAL = 15
RECONNECT_GRACE_PERIOD = 5

# Nombre de lignes conservées dans le journal technique : au-delà, les plus
# anciennes sont supprimées pour que la session reste fluide.
MAX_LOG_LINES = 5000

# Certaines sources IPTV/HLS refusent ou limitent le user-agent par défaut de
# FFmpeg (Lavf/x.y). Se faire passer pour curl avec un en-tête Accept générique
# débloque ces sources sans rien changer pour celles qui n'en ont pas besoin.
DIRECT_STREAM_USER_AGENT = "curl/8.22.0"
DIRECT_STREAM_HEADERS = "Accept: */*\r\n"
