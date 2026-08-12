import os
import re


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120] if name else ""


def sanitize_path_component(name, fallback="Inconnu"):
    """Comme sanitize_filename, mais refuse aussi les composants qui, une fois
    seuls dans un chemin (sans séparateur autour), permettraient de sortir du
    dossier de destination : "", "." et ".."."""
    cleaned = sanitize_filename(name)
    if cleaned in ("", ".", ".."):
        return fallback
    return cleaned


def safe_join_under(root, *components):
    """Joint des composants sanitizés sous `root` et vérifie que le chemin
    résultant reste bien à l'intérieur de `root` (anti path traversal)."""
    root_abs = os.path.abspath(root)
    path = root_abs
    for component in components:
        path = os.path.join(path, sanitize_path_component(component))

    resolved = os.path.abspath(path)
    if resolved != root_abs and not resolved.startswith(root_abs + os.sep):
        raise ValueError("Chemin de destination invalide.")
    return resolved
