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


BAD_STREAM_PATTERNS = [
    "error", "failed", "timeout", "timed out", "discontinuity",
    "corrupt", "packet corrupt", "segment", "retry",
    "403", "404", "connection reset", "connection aborted"
]

FFMPEG_HEALTH_PATTERNS = [
    "non-monotonous dts", "invalid timestamp", "corrupt",
    "packet corrupt", "error while decoding", "missing picture",
    "pts", "dts", "timestamp", "invalid data"
]


RECONNECT_WINDOW_SECONDS = 120
RECONNECT_RETRY_INTERVAL = 15
RECONNECT_GRACE_PERIOD = 5
