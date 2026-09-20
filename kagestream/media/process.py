import os
import signal
import subprocess
import sys


def wait_process_exit(proc, timeout):
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return True


def _posix_signal_group(proc, sig):
    """Envoie `sig` à tout le groupe de processus de `proc` (nécessite qu'il
    ait été lancé avec start_new_session=True), pour arrêter aussi les
    processus enfants qu'il a pu démarrer lui-même — par exemple le muxeur
    FFmpeg que Streamlink lance en interne pour les flux DASH séparés
    audio/vidéo, ou la fusion FFmpeg de yt-dlp. Sans ça, seul le processus
    de tête reçoit le signal : il peut se terminer normalement pendant que
    ses enfants continuent de tourner et d'écrire le fichier de sortie.
    Se rabat sur le PID seul si le process n'est pas meneur de son propre
    groupe (cas où il n'a pas été démarré avec start_new_session=True)."""
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        proc.send_signal(sig)


def escalate_process_stop(proc, log_callback=None):
    """Arrêt en trois paliers SIGINT -> SIGTERM -> SIGKILL, réutilisé par la
    capture (Streamlink/FFmpeg/yt-dlp) et par le DownloadManager musical."""
    if proc is None:
        return

    def log(text):
        if log_callback:
            log_callback(text)

    log("[INFO] Stop demandé")

    try:
        if sys.platform == "win32" and hasattr(signal, "CTRL_BREAK_EVENT"):
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        elif sys.platform == "win32":
            proc.send_signal(signal.SIGINT)
        else:
            _posix_signal_group(proc, signal.SIGINT)
        log("[INFO] SIGINT envoyé")
    except Exception as e:
        log(f"[INFO] Échec de l’envoi de SIGINT : {e}")

    if wait_process_exit(proc, 3):
        log("[INFO] Processus terminé")
        return

    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            _posix_signal_group(proc, signal.SIGTERM)
        log("[INFO] SIGTERM envoyé")
    except Exception as e:
        log(f"[INFO] Échec de l’envoi de SIGTERM : {e}")

    if wait_process_exit(proc, 3):
        log("[INFO] Processus terminé")
        return

    try:
        if sys.platform == "win32":
            proc.kill()
        else:
            _posix_signal_group(proc, signal.SIGKILL)
        log("[INFO] SIGKILL envoyé")
    except Exception as e:
        log(f"[INFO] Échec de l’envoi de SIGKILL : {e}")

    wait_process_exit(proc, 5)
    log("[INFO] Processus terminé")


def wait_file_closed(path):
    return not path or os.path.exists(path)
