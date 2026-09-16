import json
import subprocess


def probe_duration(ffprobe_path, file_path):
    """Renvoie la durée totale (en secondes) d'un fichier média via ffprobe,
    ou None si elle n'a pas pu être déterminée."""
    if not ffprobe_path:
        return None
    try:
        result = subprocess.run(
            [ffprobe_path, "-v", "quiet", "-print_format", "json", "-show_format", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
        )
        data = json.loads(result.stdout or "{}")
        duration = data.get("format", {}).get("duration")
        return float(duration) if duration is not None else None
    except Exception:
        return None


def parse_timecode(text):
    """Analyse une durée écoulée saisie par l'utilisateur : 'SS', 'MM:SS' ou
    'HH:MM:SS' (secondes flottantes acceptées). Renvoie des secondes, ou None
    si le texte n'est pas un timecode valide."""
    text = (text or "").strip()
    if not text:
        return None

    parts = text.split(":")
    if len(parts) > 3:
        return None

    try:
        values = [float(part) for part in parts]
    except ValueError:
        return None

    while len(values) < 3:
        values.insert(0, 0.0)

    hours, minutes, seconds = values
    if hours < 0 or minutes < 0 or seconds < 0:
        return None

    return hours * 3600 + minutes * 60 + seconds


def format_timecode(seconds):
    """Formate des secondes en 'HH:MM:SS.mmm', accepté par ffmpeg -ss/-to."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
