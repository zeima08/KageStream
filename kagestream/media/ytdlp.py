import json
import os
import re
import subprocess
from urllib.parse import urlparse

KAGESTREAM_FINAL_MARKER = "KAGESTREAM_FINAL:"
DOWNLOAD_PROGRESS_RE = re.compile(r"\[download\]\s+([0-9]+(?:\.[0-9]+)?%)\s*(.*)")

# Chemins typiques d'un profil de navigateur, par famille de plateforme.
# L'ordre du dictionnaire est l'ordre de préférence : Firefox se lit sans
# trousseau de clés sous Linux, les navigateurs Chromium en ont besoin.
BROWSER_PROFILE_HINTS = {
    "firefox": [
        ("posix", "~/.mozilla/firefox"),
        ("nt", "~/AppData/Roaming/Mozilla/Firefox"),
    ],
    "chrome": [
        ("posix", "~/.config/google-chrome"),
        ("nt", "~/AppData/Local/Google/Chrome/User Data"),
    ],
    "edge": [
        ("posix", "~/.config/microsoft-edge"),
        ("nt", "~/AppData/Local/Microsoft/Edge/User Data"),
    ],
    "chromium": [
        ("posix", "~/.config/chromium"),
        ("nt", "~/AppData/Local/Chromium/User Data"),
    ],
    "brave": [
        ("posix", "~/.config/BraveSoftware/Brave-Browser"),
        ("nt", "~/AppData/Local/BraveSoftware/Brave-Browser/User Data"),
    ],
    "vivaldi": [
        ("posix", "~/.config/vivaldi"),
        ("nt", "~/AppData/Local/Vivaldi/User Data"),
    ],
    "opera": [
        ("posix", "~/.config/opera"),
        ("nt", "~/AppData/Roaming/Opera Software"),
    ],
}


# Sites de replay publics dont yt-dlp possède un extracteur fiable. Ils sont
# routés vers yt-dlp comme YouTube — sans être cités dans le README.
REPLAY_SITES = (
    ("arte.tv", "Arte"),
    ("france.tv", "france.tv"),
    ("rts.ch", "RTS"),
    ("srf.ch", "SRF"),
    ("rsi.ch", "RSI"),
    ("rtr.ch", "RTR"),
    ("swissinfo.ch", "Swissinfo"),
    ("srgssr.ch", "SRG SSR"),
)


def _host_matches(url, domains):
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _is_youtube_host(url):
    return _host_matches(url, ("youtube.com", "youtu.be", "youtube-nocookie.com"))


def replay_site_label(url):
    """Libellé du site de replay si l'URL en provient, sinon None."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    for domain, label in REPLAY_SITES:
        if host == domain or host.endswith("." + domain):
            return label
    return None


def is_replay_site_url(url):
    """Vrai pour les URL des sites de replay gérés par yt-dlp : elles se
    téléchargent via la page YouTube, même collées sur la page Capturer."""
    return replay_site_label(url) is not None


def youtube_cookie_args(url, browser=None):
    """Les cookies sont facultatifs et réservés aux domaines YouTube."""
    if browser and _is_youtube_host(url):
        return ["--cookies-from-browser", browser]
    return []


def is_bot_check_error(text):
    """Vrai si la sortie de yt-dlp correspond au blocage anti-robot YouTube
    (« Sign in to confirm you're not a bot »). L'apostrophe typographique
    variant selon la version, on se fie aux mots-clés en minuscules."""
    lowered = (text or "").lower()
    return "sign in to confirm" in lowered and "bot" in lowered


def is_cookie_copy_failure(text):
    """Vrai si yt-dlp n'a pas réussi à lire les cookies du navigateur
    (profil verrouillé, trousseau de clés indisponible…)."""
    lowered = (text or "").lower()
    return (
        "could not copy cookies" in lowered
        or "failed to copy cookies" in lowered
        or "could not find any cookies" in lowered
    )


def detect_available_browsers():
    """Navigateurs dont un profil existe sur cette machine, dans l'ordre de
    préférence, avec les identifiants compris par --cookies-from-browser."""
    family = "nt" if os.name == "nt" else "posix"
    found = []
    for browser, locations in BROWSER_PROFILE_HINTS.items():
        for location_family, path in locations:
            if location_family == family and os.path.isdir(os.path.expanduser(path)):
                found.append(browser)
                break
    return found


def cookie_retry_candidates(preferred=None, limit=2):
    """Navigateurs à essayer pour relancer une commande yt-dlp bloquée par la
    vérification anti-robot, en excluant celui déjà tenté (`preferred`)."""
    detected = detect_available_browsers()
    return [browser for browser in detected if browser != preferred][:limit]


def analysis_error_message(error):
    if "sign in to confirm" in (error or "").lower() and "bot" in error.lower():
        return (
            "Vérification YouTube requise",
            "YouTube demande de confirmer que tu n’es pas un robot. "
            "Ouvre la vidéo dans ton navigateur et effectue la vérification demandée. "
            "Dans « Outils → Dépendances », sélectionne ce navigateur sous "
            "« Session YouTube », puis relance l’analyse. "
            "Si le blocage persiste, mets yt-dlp à jour depuis cette même page. "
            "Le détail de l’erreur est dans le journal technique.",
        )
    return "Lien non reconnu", error or "yt-dlp n’a pas réussi à analyser ce lien."


def analyze_url(ytdlp_path, url, js_runtime_name=None, js_runtime_path=None,
                 allow_playlist=False, timeout=90, log_callback=None,
                 cookies_browser=None, browser_callback=None):
    """Exécute `yt-dlp --dump-single-json` sur une URL — vidéo YouTube, playlist,
    ou tout site pris en charge par yt-dlp (music.youtube.com, SoundCloud, Bandcamp...).
    Retourne (data, error) comme l'ancien KageStream.analyze_youtube.

    Si YouTube bloque avec « Sign in to confirm you're not a bot », l'analyse
    est relancée automatiquement avec les cookies des navigateurs détectés,
    même si aucun n'a été sélectionné dans Outils. `browser_callback`, s'il
    est fourni, reçoit le navigateur dont les cookies ont débloqué l'analyse."""
    if not ytdlp_path:
        return None, "yt-dlp est introuvable"

    def log(text):
        if log_callback:
            log_callback(text)

    def attempt(browser):
        cmd = [
            ytdlp_path,
            "--ignore-config",
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
        ]
        cmd.append("--yes-playlist" if allow_playlist else "--no-playlist")

        if js_runtime_name and js_runtime_path:
            cmd.extend([
                "--js-runtimes",
                f"{js_runtime_name}:{js_runtime_path}"
            ])

        cmd.extend(youtube_cookie_args(url, browser))
        cmd.extend(["--", url])

        log("Commande d’analyse yt-dlp :")
        log(" ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return None, f"L’analyse a dépassé {timeout} secondes.", False
        except Exception as e:
            return None, str(e), False

        if result.returncode != 0:
            error = (result.stderr or result.stdout or "Erreur yt-dlp").strip()
            retryable = is_bot_check_error(error) or is_cookie_copy_failure(error)
            return None, error, retryable

        try:
            return json.loads(result.stdout), "", False
        except ValueError:
            return None, "yt-dlp n’a pas renvoyé d’analyse exploitable.", False

    data, error, retryable = attempt(cookies_browser)

    if data:
        if cookies_browser and browser_callback:
            browser_callback(cookies_browser)
        return data, ""

    if retryable and _is_youtube_host(url):
        candidates = cookie_retry_candidates(preferred=cookies_browser)
        if not candidates:
            log(
                "[Cookies] Blocage anti-robot YouTube — aucun navigateur "
                "compatible (Firefox, Chrome, Edge…) n’a été détecté."
            )
        for browser in candidates:
            log(
                "[Cookies] Blocage anti-robot YouTube — nouvelle tentative "
                f"avec les cookies de {browser}."
            )
            data, error, retryable = attempt(browser)
            if data:
                if browser_callback:
                    browser_callback(browser)
                return data, ""
            if not retryable:
                break

    return None, error


def extract_final_path(line):
    if KAGESTREAM_FINAL_MARKER not in line:
        return None
    final_path = line.split(KAGESTREAM_FINAL_MARKER, 1)[1].strip()
    return final_path or None


def parse_download_progress(line):
    match = DOWNLOAD_PROGRESS_RE.search(line)
    if not match:
        return None
    percent = match.group(1)
    rest = match.group(2).strip()
    return percent, rest
