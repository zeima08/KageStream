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
        else:
            proc.send_signal(signal.SIGINT)
        log("[INFO] SIGINT envoyé")
    except Exception as e:
        log(f"[INFO] Échec de l’envoi de SIGINT : {e}")

    if wait_process_exit(proc, 3):
        log("[INFO] Processus terminé")
        return

    try:
        proc.terminate()
        log("[INFO] SIGTERM envoyé")
    except Exception as e:
        log(f"[INFO] Échec de l’envoi de SIGTERM : {e}")

    if wait_process_exit(proc, 3):
        log("[INFO] Processus terminé")
        return

    try:
        proc.kill()
        log("[INFO] SIGKILL envoyé")
    except Exception as e:
        log(f"[INFO] Échec de l’envoi de SIGKILL : {e}")

    wait_process_exit(proc, 5)
    log("[INFO] Processus terminé")


def wait_file_closed(path):
    import os
    return not path or os.path.exists(path)
