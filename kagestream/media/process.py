import os
import signal
import subprocess
import sys
import time


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


def kill_process_group(proc):
    """SIGKILL immédiat sur tout le groupe de processus (PID seul en repli),
    pour un processus déjà considéré comme perdu — par exemple un FFmpeg de
    finalisation resté bloqué au-delà de son délai garde-fou."""
    try:
        if sys.platform == "win32":
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def escalate_processes_stop(procs, log_callback=None):
    """Escalade SIGINT -> SIGTERM -> SIGKILL appliquée à plusieurs processus
    en parallèle, pour la fermeture de l'application : chaque palier est
    attendu une seule fois pour l'ensemble (au plus ~11 s au total), et non
    multiplié par le nombre de processus comme un appel en série
    d'escalate_process_stop."""
    running = [proc for proc in procs if proc is not None and proc.poll() is None]
    if not running:
        return

    def log(text):
        if log_callback:
            log_callback(text)

    def alive():
        return [proc for proc in running if proc.poll() is None]

    def signal_alive(sig):
        for proc in alive():
            try:
                if sys.platform == "win32":
                    if sig == signal.SIGINT and hasattr(signal, "CTRL_BREAK_EVENT"):
                        proc.send_signal(signal.CTRL_BREAK_EVENT)
                    elif sig == signal.SIGTERM:
                        proc.terminate()
                    else:
                        proc.kill()
                else:
                    _posix_signal_group(proc, sig)
            except Exception:
                pass

    def settle(timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not alive():
                return True
            time.sleep(0.1)
        return not alive()

    log(f"[INFO] Arrêt de {len(running)} processus en cours...")

    signal_alive(signal.SIGINT)
    if settle(3):
        log("[INFO] Tous les processus sont terminés.")
        return

    log(f"[INFO] {len(alive())} processus restants — SIGTERM.")
    signal_alive(signal.SIGTERM)
    if settle(3):
        log("[INFO] Tous les processus sont terminés.")
        return

    log(f"[INFO] {len(alive())} processus restants — SIGKILL.")
    signal_alive(signal.SIGKILL)
    settle(5)
    log("[INFO] Arrêt de tous les processus terminé.")


def open_handle_pids(path):
    """PIDs qui gardent `path` ouvert, via /proc (Linux). Retourne un ensemble
    vide si /proc n'est pas disponible ou si le fichier est absent."""
    target = os.path.realpath(path)
    pids = set()
    proc_root = "/proc"
    if not os.path.isdir(proc_root):
        return pids

    for entry in os.listdir(proc_root):
        if not entry.isdigit():
            continue
        fd_dir = os.path.join(proc_root, entry, "fd")
        try:
            handles = os.listdir(fd_dir)
        except OSError:
            continue
        for handle in handles:
            try:
                link = os.readlink(os.path.join(fd_dir, handle))
            except OSError:
                continue
            # Un fichier supprimé porte le suffixe " (deleted)".
            if link == target or link == target + " (deleted)":
                pids.add(int(entry))
                break
    return pids


def wait_file_closed(path, timeout=10.0, stable_for=2.0, poll_interval=0.25):
    """Attend que plus aucun processus ne garde `path` ouvert.

    Sous Linux, la vérification est réelle : les descripteurs de fichiers de
    /proc sont inspectés. Ailleurs (Windows, macOS, ou /proc indisponible),
    on se rabat sur la stabilité de la taille et de la date de modification
    pendant `stable_for` secondes — un fichier encore écrit change, un
    fichier libéré non.

    Retourne True si la fermeture est confirmée (ou si le fichier n'existe
    pas), False si le délai expire sans confirmation."""
    if not path or not os.path.exists(path):
        return True

    has_proc = os.path.isdir("/proc")
    deadline = time.monotonic() + timeout
    last_signature = None
    stable_since = None

    while time.monotonic() < deadline:
        if has_proc:
            if not open_handle_pids(path):
                return True
        else:
            try:
                stat_result = os.stat(path)
            except OSError:
                return True
            signature = (stat_result.st_size, stat_result.st_mtime_ns)
            now = time.monotonic()
            if signature != last_signature:
                last_signature = signature
                stable_since = now
            elif stable_since is not None and now - stable_since >= stable_for:
                return True
        time.sleep(poll_interval)

    if not os.path.exists(path):
        return True
    if has_proc:
        return not open_handle_pids(path)
    return False
