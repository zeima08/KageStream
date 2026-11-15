import functools
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from urllib.parse import urlparse

from gi.repository import GLib

from kagestream.capture.job import CaptureJob, CaptureState
from kagestream.constants import (
    matches_stream_problem,
    is_serious_ffmpeg_issue,
    RECONNECT_WINDOW_SECONDS,
    RECONNECT_RETRY_INTERVAL,
    RECONNECT_GRACE_PERIOD,
    DIRECT_STREAM_USER_AGENT,
    DIRECT_STREAM_HEADERS,
)
from kagestream.media.ffprobe import format_timecode
from kagestream.media.sources import (
    SourceTools,
    streamlink_can_handle_url,
    streamlink_codec_args,
    streamlink_header_args,
    probe_direct_source,
)
from kagestream.media.process import (
    escalate_process_stop,
    escalate_processes_stop,
    kill_process_group,
    wait_file_closed,
)
from kagestream.utils.filenames import sanitize_path_component

# Délais max des sous-processus de finalisation : base fixe + marge par Gio,
# pour ne jamais tuer un traitement légitime tout en débloquant la file si
# FFmpeg reste bloqué (TS corrompu, entrée spéciale). La conversion (réencodage)
# est des ordres de grandeur plus lente que le remux (copie de flux).
HEALTH_TIMEOUT_BASE = 120
HEALTH_TIMEOUT_PER_GB = 60
REMUX_TIMEOUT_BASE = 180
REMUX_TIMEOUT_PER_GB = 60
TRANSCODE_TIMEOUT_BASE = 5400
TRANSCODE_TIMEOUT_PER_GB = 1800
CUT_TIMEOUT_BASE = 120
CUT_TIMEOUT_PER_GB = 60


def finalize_timeout(file_path, base, per_gb):
    """Délai maximal d'un sous-processus de finalisation, dimensionné sur la
    taille du fichier à traiter."""
    try:
        size_gb = os.path.getsize(file_path) / (1024 ** 3)
    except OSError:
        size_gb = 1.0
    return int(base + per_gb * max(size_gb, 0.05))


class CaptureManager:
    """Gère plusieurs captures (Streamlink / IPTV / FFmpeg direct) en parallèle.

    Chaque capture tourne dans son propre thread dès son lancement — pas de
    file d'attente pour l'enregistrement lui-même. En revanche, la
    finalisation (analyse FFmpeg, remux, conversion) est gourmande en CPU :
    elle passe par une file d'attente séquentielle (_finalize_queue) traitée
    par un unique thread, pour qu'un seul remux/conversion tourne à la fois
    même si plusieurs captures se terminent en même temps."""

    def __init__(self, tools_provider, log_callback):
        """`tools_provider` est un appelable sans argument qui retourne un
        SourceTools à jour (les chemins changent après une installation) ;
        `log_callback` reçoit le texte destiné au journal. Aucune dépendance
        à une fenêtre GTK : le manager est utilisable et testable sans UI."""
        self._tools_provider = tools_provider
        self._log_callback = log_callback
        self.jobs = []
        self._listeners = []
        self._finalize_queue = queue.Queue()
        self._reserved_outputs = set()
        self._reserved_outputs_lock = threading.Lock()
        self._finalize_proc = None
        self._tick_id = None

        threading.Thread(target=self._finalize_loop, daemon=True).start()

    # ------------------------------------------------------------------
    # Notification UI
    # ------------------------------------------------------------------
    def add_listener(self, callback):
        self._listeners.append(callback)

    def _notify(self):
        for callback in list(self._listeners):
            GLib.idle_add(callback)

    def _tick(self):
        active_states = (CaptureState.EN_COURS, CaptureState.RECONNEXION)
        if any(job.state in active_states for job in self.jobs):
            self._notify()
            return True
        # Plus rien à rafraîchir : le timer s'éteint au lieu de réveiller la
        # boucle GLib chaque seconde pendant toute la session.
        self._tick_id = None
        return False

    def _ensure_tick(self):
        if self._tick_id is None:
            self._tick_id = GLib.timeout_add(1000, self._tick)
        return False

    def remove_job(self, job):
        """Retire une tâche terminée de la liste affichée. Le fichier produit
        n'est jamais touché."""
        if job.state in (CaptureState.EN_COURS, CaptureState.RECONNEXION,
                          CaptureState.EN_ATTENTE):
            return False
        if job in self.jobs:
            self.jobs.remove(job)
            self._notify()
        return False

    def clear_finished(self):
        """Vide les captures terminées, annulées ou en erreur."""
        done = (CaptureState.TERMINE, CaptureState.ANNULE, CaptureState.ERREUR)
        self.jobs = [job for job in self.jobs if job.state not in done]
        self._notify()
        return False

    def _log(self, job, text):
        if not text:
            self._log_callback("")
        else:
            self._log_callback(f"[{job.label}] {text}")

    def _tools(self):
        return self._tools_provider()

    def _label_from_url(self, url):
        try:
            host = urlparse(url).hostname
        except Exception:
            host = None
        return host or url or "Capture"

    def _build_job(self, url, quality, twitch_preference, profile, output_format,
                    filename, folder, schedule_start=None, schedule_end=None):
        return CaptureJob(
            id=str(uuid.uuid4()),
            label=filename or self._label_from_url(url),
            url=url,
            quality=quality,
            twitch_preference=twitch_preference,
            profile=profile,
            output_format=output_format,
            filename=filename,
            folder=folder,
            schedule_start=schedule_start,
            schedule_end=schedule_end,
        )

    # ------------------------------------------------------------------
    # Démarrage / programmation
    # ------------------------------------------------------------------
    def start_capture(self, url, quality, twitch_preference, profile, output_format,
                       filename, folder):
        job = self._build_job(url, quality, twitch_preference, profile, output_format,
                               filename, folder)
        ts_file = self._reserve_ts_path(job.folder, job.filename)
        job.current_ts_file = ts_file
        job.final_file = ts_file
        self.jobs.append(job)
        self._notify()
        self._ensure_tick()

        threading.Thread(target=self._record_worker, args=(job,), daemon=True).start()
        return job

    def schedule_capture(self, start_at, end_at, url, quality, twitch_preference,
                          profile, output_format, filename, folder):
        job = self._build_job(
            url, quality, twitch_preference, profile, output_format, filename, folder,
            schedule_start=start_at.timestamp(), schedule_end=end_at.timestamp()
        )
        self.jobs.append(job)
        self._notify()
        self._ensure_tick()

        threading.Thread(
            target=self._schedule_worker, args=(job, start_at, end_at), daemon=True
        ).start()
        return job

    def cancel_schedule(self, job):
        job.schedule_cancelled = True
        self._notify()

    def _abort_schedule_if_cancelled(self, job):
        if not job.schedule_cancelled:
            return False
        self._log(job, "[INFO] Programmation annulée avant le démarrage.")
        job.state = CaptureState.ANNULE
        self._notify()
        return True

    def _reserve_ts_path(self, folder, filename):
        """Choisit un chemin .ts qui n'écrase ni un fichier existant ni une
        capture de la session en cours : nom.ts, puis nom-2.ts, nom-3.ts, …
        Le fichier étant créé par le sous-processus quelques instants plus
        tard, les chemins déjà réservés sont mémorisés pour éviter qu'une
        seconde capture démarrée entre-temps ne reçoive le même nom."""
        stem = sanitize_path_component(filename, "capture")
        with self._reserved_outputs_lock:
            candidate = os.path.join(folder, f"{stem}.ts")
            counter = 2
            while candidate in self._reserved_outputs or os.path.exists(candidate):
                candidate = os.path.join(folder, f"{stem}-{counter}.ts")
                counter += 1
            self._reserved_outputs.add(candidate)
            return candidate

    def _schedule_worker(self, job, start_at, end_at):
        try:
            while True:
                remaining = (start_at - datetime.now()).total_seconds()
                if remaining <= 0:
                    break
                if self._abort_schedule_if_cancelled(job):
                    return
                time.sleep(min(remaining, 1))

            # L'annulation peut tomber pendant le dernier time.sleep : il faut
            # relire le drapeau après la sortie de boucle, sinon l'enregistrement
            # démarrerait malgré l'annulation demandée.
            if self._abort_schedule_if_cancelled(job):
                return

            self._log(
                job,
                "[INFO] Heure de début atteinte — lancement de l’enregistrement programmé."
            )
            ts_file = self._reserve_ts_path(job.folder, job.filename)
            job.current_ts_file = ts_file
            job.final_file = ts_file

            threading.Thread(
                target=self._watch_schedule_end, args=(job, end_at), daemon=True
            ).start()
            GLib.idle_add(self._ensure_tick)
            self._record_worker(job)

        except Exception as e:
            self._log(job, f"[INFO] Erreur de programmation : {e}")
            job.error = str(e)
            job.state = CaptureState.ERREUR
            self._notify()

    def _watch_schedule_end(self, job, end_at):
        while datetime.now() < end_at:
            if job.cancel_requested or job.state not in (
                CaptureState.EN_ATTENTE, CaptureState.EN_COURS, CaptureState.RECONNEXION
            ):
                return
            time.sleep(1)

        if job.state in (CaptureState.EN_COURS, CaptureState.RECONNEXION):
            self._log(job, "[INFO] Heure de fin atteinte — arrêt automatique programmé.")
            self.stop(job)

    # ------------------------------------------------------------------
    # Arrêt
    # ------------------------------------------------------------------
    def stop(self, job):
        if job.cancel_requested:
            return
        job.cancel_requested = True
        self._notify()
        threading.Thread(target=self._stop_worker, args=(job,), daemon=True).start()

    def _stop_worker(self, job):
        try:
            if job.process:
                escalate_process_stop(job.process, log_callback=lambda t: self._log(job, t))

            ts_file = job.current_ts_file
            if ts_file and os.path.exists(ts_file):
                self._log(job, "Vérification de la fermeture du fichier TS...")
                if wait_file_closed(ts_file):
                    self._log(job, "[INFO] Fichier TS fermé correctement.")
                else:
                    self._log(
                        job,
                        "[INFO] Un processus garde encore le fichier TS ouvert après "
                        "l’arrêt — il peut rester incomplet."
                    )
        except Exception as e:
            self._log(job, f"Erreur pendant l’arrêt : {e}")

    def shutdown(self):
        """Arrête tous les sous-processus actifs — appelé à la fermeture de la
        fenêtre : les enregistrements tournant dans des groupes de processus
        dédiés (start_new_session), ils survivraient à l'application et
        continueraient d'écrire leurs fichiers en arrière-plan."""
        procs = []
        for job in list(self.jobs):
            job.cancel_requested = True
            job.schedule_cancelled = True
            if job.process is not None and job.process.poll() is None:
                procs.append(job.process)
        if self._finalize_proc is not None and self._finalize_proc.poll() is None:
            procs.append(self._finalize_proc)
        escalate_processes_stop(procs, log_callback=self._log_callback)

    # ------------------------------------------------------------------
    # Construction / exécution de la commande d'enregistrement
    # ------------------------------------------------------------------
    def _build_record_command(self, job, ts_file):
        tools = self._tools()

        if streamlink_can_handle_url(tools.streamlink, job.url):
            backend = "Streamlink"
            cmd = [tools.streamlink]
            cmd.extend(streamlink_header_args(job.url))
            cmd.extend(
                streamlink_codec_args(job.url, job.twitch_preference, tools.streamlink_version)
            )
            cmd.extend([job.url, job.quality, "-o", ts_file])
            return backend, cmd, True, ""

        valid, details = probe_direct_source(
            tools.ffmpeg, tools.ffprobe, job.url,
            log_callback=tools.log_callback,
        )
        if not valid:
            return None, None, False, details

        cmd = [
            tools.ffmpeg,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel", "warning",
            "-extension_picky", "0",
            "-rw_timeout", "15000000",
        ]

        if job.url.lower().startswith(("http://", "https://")):
            cmd.extend([
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-user_agent", DIRECT_STREAM_USER_AGENT,
                "-headers", DIRECT_STREAM_HEADERS,
            ])

        cmd.extend(["-i", job.url, "-map", "0", "-c", "copy", "-f", "mpegts", ts_file])
        return "FFmpeg direct", cmd, True, details

    def _run_capture_process(self, job, cmd, backend):
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        # start_new_session (POSIX) place le process dans son propre groupe,
        # comme creationflags le fait côté Windows : Streamlink démarre en
        # interne un muxeur FFmpeg (flux DASH séparés audio/vidéo) qui, sans
        # ça, ne recevrait jamais l'arrêt et continuerait à écrire le fichier
        # après un Stop — voir escalate_process_stop dans media/process.py.
        job.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creationflags,
            start_new_session=(sys.platform != "win32"),
        )
        return self._read_capture_process(job, backend)

    def _read_capture_process(self, job, backend):
        for line in job.process.stdout:
            clean = line.rstrip()
            self._log(job, clean)
            self._inspect_streamlink_line(job, clean)

        job.process.wait()
        return job.process.returncode

    def _inspect_streamlink_line(self, job, line):
        if not matches_stream_problem(line):
            return

        job.stream_warning_count += 1
        self._log(job, f"⚠️ Signal suspect #{job.stream_warning_count} : {line}")

        if job.stream_warning_count >= 5:
            job.stream_health = "instable"
            job.last_health_report = f"{job.stream_warning_count} signaux suspects"
        else:
            job.stream_health = "à surveiller"
            job.last_health_report = f"{job.stream_warning_count} signal suspect"
        self._notify()

    def _attempt_reconnect(self, job, ts_file, segment_files, previous_backend):
        job.state = CaptureState.RECONNEXION
        self._log(
            job,
            f"[INFO] Flux {previous_backend} interrompu — tentative de reconnexion "
            f"pendant {RECONNECT_WINDOW_SECONDS}s (sauf arrêt manuel)."
        )
        self._notify()
        deadline = time.time() + RECONNECT_WINDOW_SECONDS

        while time.time() < deadline and not job.cancel_requested:
            remaining = max(0, int(deadline - time.time()))
            self._log(job, f"[INFO] Nouvelle tentative de reconnexion ({remaining}s avant abandon)")

            segment_path = f"{os.path.splitext(ts_file)[0]}.reconnect{len(segment_files)}.ts"
            backend, cmd, valid, details = self._build_record_command(job, segment_path)

            if not valid:
                self._sleep_until(job, min(time.time() + RECONNECT_RETRY_INTERVAL, deadline))
                continue

            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

            try:
                probe_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=creationflags,
                    start_new_session=(sys.platform != "win32"),
                )
            except Exception as e:
                self._log(job, f"[INFO] Reconnexion impossible : {e}")
                self._sleep_until(job, min(time.time() + RECONNECT_RETRY_INTERVAL, deadline))
                continue

            job.process = probe_process
            self._sleep_until(job, min(time.time() + RECONNECT_GRACE_PERIOD, deadline))

            has_data = os.path.exists(segment_path) and os.path.getsize(segment_path) > 0
            still_running = probe_process.poll() is None

            if has_data and still_running and not job.cancel_requested:
                self._log(job, f"[INFO] Source retrouvée — reprise de l’enregistrement ({backend}).")
                # Repartir d'un compteur propre : les alertes de la connexion
                # précédente ne doivent pas condamner la nouvelle session.
                job.stream_warning_count = 0
                job.stream_health = "Non analysé"
                job.last_health_report = ""
                segment_files.append(segment_path)
                job.current_ts_file = segment_path
                return backend

            escalate_process_stop(probe_process, log_callback=lambda t: self._log(job, t))
            if os.path.exists(segment_path) and os.path.getsize(segment_path) == 0:
                try:
                    os.remove(segment_path)
                except OSError:
                    pass

            if job.cancel_requested:
                break

            self._sleep_until(job, min(time.time() + RECONNECT_RETRY_INTERVAL, deadline))

        if not job.cancel_requested:
            self._log(
                job,
                f"[INFO] Reconnexion impossible après {RECONNECT_WINDOW_SECONDS}s — "
                "arrêt de l’enregistrement."
            )
        return None

    def _sleep_until(self, job, until):
        while time.time() < until and not job.cancel_requested:
            time.sleep(min(0.5, max(0, until - time.time())))

    def _merge_segments(self, job, segment_files):
        existing = [path for path in segment_files if path and os.path.exists(path)]
        if not existing:
            return segment_files[0] if segment_files else None

        primary = existing[0]
        extras = existing[1:]

        if extras:
            self._log(job, f"[INFO] Fusion de {len(existing)} segments après reconnexion(s).")
            try:
                with open(primary, "ab") as output:
                    for extra in extras:
                        with open(extra, "rb") as part:
                            shutil.copyfileobj(part, output)
                        os.remove(extra)
                self._log(job, f"[INFO] Segments fusionnés dans : {primary}")
            except Exception as e:
                self._log(job, f"[INFO] Fusion des segments impossible : {e}")

        return primary

    def _record_worker(self, job):
        ts_file = job.current_ts_file
        segment_files = [ts_file]
        job.state = CaptureState.EN_COURS
        self._notify()

        try:
            self._log(job, "")

            backend, cmd, valid, details = self._build_record_command(job, ts_file)

            if not valid:
                self._log(job, f"Source refusée : {details}")
                job.error = "Source non reconnue (ni Streamlink, ni flux direct FFmpeg)."
                job.state = CaptureState.ERREUR
                self._notify()
                return

            if backend == "FFmpeg direct":
                self._log(job, f"Flux direct détecté : {details}")

            job.active_backend = backend
            self._log(job, f"Commande {backend} :")
            self._log(job, " ".join(cmd))
            job.recording_start = time.time()

            returncode = self._run_capture_process(job, cmd, backend)

            while not job.cancel_requested and returncode != 0:
                backend = self._attempt_reconnect(job, ts_file, segment_files, backend)
                if backend is None:
                    break
                job.active_backend = backend
                job.state = CaptureState.EN_COURS
                self._notify()
                returncode = self._read_capture_process(job, backend)

            merged = self._merge_segments(job, segment_files)
            job.current_ts_file = merged
            has_data = bool(merged) and os.path.exists(merged) and os.path.getsize(merged) > 0

            if job.cancel_requested:
                self._log(job, "Enregistrement arrêté par l’utilisateur.")
                if has_data:
                    self._log(job, f"Fichier conservé : {merged}")
                    self._enqueue_finalize(job, merged, job.output_format, job.profile)
                else:
                    self._log(job, "Aucune donnée vidéo n’a été enregistrée.")
                    job.state = CaptureState.ANNULE
                    self._notify()

            elif returncode == 0:
                self._log(job, "Enregistrement terminé.")
                if has_data:
                    self._enqueue_finalize(job, merged, job.output_format, job.profile)
                else:
                    self._log(job, "L’enregistrement est vide.")
                    job.error = "Fichier vide"
                    job.state = CaptureState.ERREUR
                    self._notify()

            elif has_data:
                self._log(
                    job,
                    f"{backend} s’est arrêté avec le code {returncode}, "
                    "mais la partie déjà enregistrée est conservée."
                )
                self._enqueue_finalize(job, merged, job.output_format, job.profile)
            else:
                self._log(job, f"{backend} s’est arrêté avec une erreur.")
                job.error = f"{backend} a quitté avec une erreur"
                job.state = CaptureState.ERREUR
                self._notify()

        except Exception as e:
            merged = self._merge_segments(job, segment_files)
            if job.cancel_requested:
                self._log(job, "Enregistrement arrêté par l’utilisateur.")
                if merged and os.path.exists(merged) and os.path.getsize(merged) > 0:
                    self._enqueue_finalize(job, merged, job.output_format, job.profile)
                    return
            self._log(job, f"Erreur : {e}")
            job.error = str(e)
            job.state = CaptureState.ERREUR
            self._notify()

        finally:
            job.process = None

    # ------------------------------------------------------------------
    # File d'attente de finalisation (remux / vérification / conversion)
    # ------------------------------------------------------------------
    def _enqueue_finalize(self, job, ts_file, fmt, profile):
        job.state = CaptureState.EN_ATTENTE_REMUX
        self._notify()
        self._finalize_queue.put(functools.partial(self._do_finalize, job, ts_file, fmt, profile))

    def _finalize_loop(self):
        while True:
            task = self._finalize_queue.get()
            try:
                task()
            except Exception as e:
                self._log_callback(f"[Finalisation] Erreur inattendue : {e}")

    def resolve_decision(self, job, choice):
        ts_file = job.pending_ts_file
        fmt = job.pending_fmt

        if choice == "verify":
            job.state = CaptureState.EN_ATTENTE_REMUX
            self._notify()
            self._finalize_queue.put(functools.partial(self._do_verify, job, ts_file, fmt))
        elif choice in ("remux_directly", "continue_remux"):
            job.state = CaptureState.EN_ATTENTE_REMUX
            self._notify()
            self._finalize_queue.put(functools.partial(self._do_remux, job, ts_file, fmt))
        elif choice == "try_mkv":
            job.state = CaptureState.EN_ATTENTE_REMUX
            self._notify()
            self._finalize_queue.put(functools.partial(self._do_remux, job, ts_file, "mkv"))
        elif choice == "keep_ts":
            job.final_file = ts_file
            job.state = CaptureState.TERMINE
            self._log(job, f"Fichier TS conservé sans remux : {ts_file}")
            self._notify()

    def _do_finalize(self, job, ts_file, fmt, profile):
        if profile != "copy":
            job.state = CaptureState.CONVERSION
            self._notify()
            self._check_recording_health(job, ts_file)
            self._do_transcode(job, ts_file, fmt, profile)
        elif fmt == "ts":
            self._check_recording_health(job, ts_file)
            job.final_file = ts_file
            job.state = CaptureState.TERMINE
            self._log(job, f"Fichier final : {ts_file}")
            self._notify()
        else:
            job.state = CaptureState.DECISION_REMUX
            job.pending_ts_file = ts_file
            job.pending_fmt = fmt
            self._notify()

    def _do_verify(self, job, ts_file, fmt):
        job.state = CaptureState.VERIFICATION
        self._notify()

        try:
            healthy = self._check_recording_health(job, ts_file)
            report = job.last_ts_analysis or {}
            summary = "\n".join([
                f"Paquets corrompus détectés : {len(report.get('corrupted_packets', []))}",
                f"Erreurs DTS détectées : {len(report.get('dts_errors', []))}",
                f"Timestamps invalides détectés : {len(report.get('timestamp_errors', []))}",
                f"Alertes sérieuses au total : {len(report.get('serious_issues', []))}",
                "",
                "État général : " + ("OK" if healthy else "problème détecté"),
            ])
            job.last_health_report = summary
            job.pending_ts_file = ts_file
            job.pending_fmt = fmt
            job.state = CaptureState.DECISION_POST_VERIF
            self._notify()
        except Exception as e:
            self._log(job, f"[INFO] Erreur pendant l’analyse du TS : {e}")
            job.error = str(e)
            job.final_file = ts_file
            job.state = CaptureState.ERREUR
            self._notify()

    def _run_finalize_process(self, job, cmd, description, timeout):
        """Lance un FFmpeg de finalisation dans son propre groupe de processus,
        journalise sa sortie et applique un garde-fou : au-delà de `timeout`
        secondes sans fin, le groupe est tué (SIGKILL) pour ne jamais bloquer
        la file de finalisation — un FFmpeg figé sur un TS corrompu la
        gelait auparavant pour toujours. Retourne (proc, expiré, lignes)."""
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creationflags,
            start_new_session=(sys.platform != "win32"),
        )
        self._finalize_proc = proc
        # Permet au bouton Stop de la ligne d'arrêter aussi un remux ou une
        # conversion en cours, comme pour l'enregistrement.
        job.process = proc

        state = {"expired": False}

        def expire():
            state["expired"] = True
            self._log(
                job,
                f"[ERREUR] {description} : {timeout} s écoulées sans fin — "
                "arrêt forcé de FFmpeg pour débloquer la file de finalisation."
            )
            kill_process_group(proc)

        watchdog = threading.Timer(timeout, expire)
        watchdog.daemon = True
        watchdog.start()

        lines = []
        try:
            for line in proc.stdout:
                clean = line.rstrip()
                if clean:
                    lines.append(clean)
                    self._log(job, clean)
            proc.wait()
        finally:
            watchdog.cancel()
            self._finalize_proc = None
            job.process = None

        return proc, state["expired"], lines

    def _check_recording_health(self, job, file_path):
        tools = self._tools()
        if not tools.ffmpeg or not os.path.exists(file_path):
            job.last_health_report = "Analyse impossible : FFmpeg ou fichier introuvable."
            self._log(job, job.last_health_report)
            return False

        self._log(job, "")
        self._log(job, "===== Analyse santé du fichier =====")
        self._log(job, "[INFO] Analyse du TS")
        self._log(job, f"Fichier analysé : {file_path}")

        cmd = [tools.ffmpeg, "-v", "warning", "-i", file_path, "-f", "null", "-"]
        self._log(job, "Commande analyse :")
        self._log(job, " ".join(cmd))

        issues = []
        serious_issues = []
        corrupted_packets = []
        dts_errors = []
        timestamp_errors = []

        try:
            timeout = finalize_timeout(file_path, HEALTH_TIMEOUT_BASE, HEALTH_TIMEOUT_PER_GB)
            proc, expired, issues = self._run_finalize_process(
                job, cmd, "Analyse du TS", timeout
            )

            for clean in issues:
                lower = clean.lower()
                if is_serious_ffmpeg_issue(clean):
                    serious_issues.append(clean)
                if "corrupt" in lower:
                    corrupted_packets.append(clean)
                if "dts" in lower:
                    dts_errors.append(clean)
                if "timestamp" in lower or "pts" in lower:
                    timestamp_errors.append(clean)

            if expired:
                serious_issues.append(f"Analyse interrompue : délai de {timeout} s dépassé.")
            elif proc.returncode != 0:
                serious_issues.append(f"FFmpeg a terminé avec le code {proc.returncode}")

            job.last_ts_analysis = {
                "file": file_path,
                "issues": issues,
                "serious_issues": serious_issues,
                "corrupted_packets": corrupted_packets,
                "dts_errors": dts_errors,
                "timestamp_errors": timestamp_errors,
            }

            if serious_issues:
                job.last_health_report = (
                    f"Problème probable : {len(serious_issues)} alerte(s) sérieuse(s), "
                    f"{len(issues)} avertissement(s) total."
                )
                self._log(job, "⚠️ " + job.last_health_report)
                job.stream_health = "problème détecté"
                return False

            if issues:
                job.last_health_report = f"À surveiller : {len(issues)} avertissement(s)."
                self._log(job, "⚠️ " + job.last_health_report)
                job.stream_health = "à surveiller"
                return True

            job.last_health_report = "OK : aucun problème évident détecté par FFmpeg."
            self._log(job, "✅ " + job.last_health_report)
            job.stream_health = "OK"
            return True

        except Exception as e:
            job.last_health_report = f"Analyse impossible : {e}"
            self._log(job, job.last_health_report)
            job.stream_health = "analyse impossible"
            job.last_ts_analysis = {}
            return False

    def _do_remux(self, job, ts_file, fmt):
        job.state = CaptureState.REMUX
        self._notify()
        tools = self._tools()

        if not tools.ffmpeg:
            self._log(job, "Remux impossible : FFmpeg introuvable.")
            job.error = "FFmpeg introuvable"
            job.final_file = ts_file
            job.state = CaptureState.ERREUR
            self._notify()
            return

        if not os.path.exists(ts_file):
            self._log(job, "Remux impossible : fichier TS introuvable.")
            job.error = "Fichier TS introuvable"
            job.final_file = ts_file
            job.state = CaptureState.ERREUR
            self._notify()
            return

        output = os.path.splitext(ts_file)[0] + "." + fmt

        # Chaque palier réduit un peu plus les flux/options pour maximiser les
        # chances de produire un fichier, quel que soit le multiplex DVB/IPTV
        # d'origine.
        mapping_attempts = [
            (
                ["-map", "0:v?", "-map", "0:a?", "-map", "0:s?", "-c", "copy", "-bsf:a", "aac_adtstoasc"],
                "vidéo + audio + sous-titres"
            ),
            (
                ["-map", "0:v:0?", "-map", "0:a?", "-c", "copy", "-bsf:a", "aac_adtstoasc"],
                "vidéo + audio, sous-titres exclus"
            ),
            (
                ["-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy"],
                "vidéo + première piste audio, sans filtre"
            ),
        ]

        self._log(job, "")
        self._log(job, "[INFO] Remux lancé")

        try:
            expired = False
            for index, (extra_args, label) in enumerate(mapping_attempts):
                cmd = [tools.ffmpeg, "-y", "-i", ts_file] + extra_args + [output]

                self._log(job, "Commande FFmpeg :" if index == 0 else f"Nouvelle tentative ({label}) :")
                self._log(job, " ".join(cmd))

                timeout = finalize_timeout(ts_file, REMUX_TIMEOUT_BASE, REMUX_TIMEOUT_PER_GB)
                proc, expired, _lines = self._run_finalize_process(job, cmd, "Remux", timeout)

                if (not expired and proc.returncode == 0
                        and os.path.isfile(output) and os.path.getsize(output) > 0):
                    job.final_file = output
                    job.state = CaptureState.TERMINE
                    self._log(job, f"Remux terminé : {output}")
                    self._log(job, "[INFO] Remux terminé")
                    self._notify()
                    return

                if expired:
                    # FFmpeg est resté bloqué sur ce fichier : réessayer avec un
                    # mapping réduit ne changerait rien.
                    break

                if index < len(mapping_attempts) - 1:
                    self._log(
                        job,
                        "Remux impossible avec ce mapping (flux incompatibles avec le conteneur). "
                        "Nouvelle tentative avec un mapping réduit..."
                    )

            if fmt == "mp4":
                self._log(job, "MP4 impossible. Proposition de remux en MKV.")
                job.pending_ts_file = ts_file
                job.pending_fmt = "mkv"
                job.state = CaptureState.DECISION_MKV
                self._notify()
            else:
                job.error = (
                    "Délai de remux dépassé — FFmpeg a été arrêté de force."
                    if expired
                    else "FFmpeg n’a pas réussi à remuxer ce fichier, même avec un mapping réduit."
                )
                job.final_file = ts_file
                job.state = CaptureState.ERREUR
                self._log(job, job.error + " Le TS est conservé.")
                self._notify()

        except Exception as e:
            self._log(job, f"Erreur pendant le remux : {e}")
            job.error = str(e)
            job.final_file = ts_file
            job.state = CaptureState.ERREUR
            self._notify()

    def _ffmpeg_encoder_available(self, encoder):
        tools = self._tools()
        if not tools.ffmpeg:
            return False
        try:
            result = subprocess.run(
                [tools.ffmpeg, "-hide_banner", "-encoders"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=20,
            )
            return bool(re.search(rf"\b{re.escape(encoder)}\b", result.stdout or ""))
        except Exception:
            return False

    def _do_transcode(self, job, ts_file, fmt, profile):
        tools = self._tools()
        if not tools.ffmpeg or not os.path.exists(ts_file):
            self._log(job, "Conversion impossible : FFmpeg ou fichier TS introuvable.")
            job.error = "FFmpeg ou fichier TS introuvable"
            job.final_file = ts_file
            job.state = CaptureState.ERREUR
            self._notify()
            return

        profiles = {
            "h264_aac": {
                "label": "H.264 + AAC",
                "encoders": ("libx264", "aac"),
                "args": [
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                ],
            },
            "av1_opus": {
                "label": "AV1 + Opus",
                "encoders": ("libsvtav1", "libopus"),
                "args": [
                    "-c:v", "libsvtav1", "-preset", "10", "-crf", "32",
                    "-pix_fmt", "yuv420p", "-c:a", "libopus", "-b:a", "160k",
                ],
            },
        }
        settings = profiles.get(profile)
        if not settings:
            self._log(job, f"Profil de conversion inconnu : {profile}")
            job.error = f"Profil de conversion inconnu : {profile}"
            job.final_file = ts_file
            job.state = CaptureState.ERREUR
            self._notify()
            return

        missing = [
            encoder for encoder in settings["encoders"]
            if not self._ffmpeg_encoder_available(encoder)
        ]
        if missing:
            message = (
                "Ce build de FFmpeg ne contient pas les encodeurs nécessaires : "
                + ", ".join(missing)
                + f".\n\nLe fichier TS original est conservé :\n{ts_file}"
            )
            self._log(job, message)
            job.error = message
            job.final_file = ts_file
            job.state = CaptureState.ERREUR
            self._notify()
            return

        output = os.path.splitext(ts_file)[0] + "." + fmt
        cmd = [
            tools.ffmpeg,
            "-y",
            "-hide_banner",
            "-i", ts_file,
            "-map", "0:v:0",
            "-map", "0:a?",
            "-map_metadata", "0",
        ]
        cmd.extend(settings["args"])
        if fmt == "mp4":
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(output)

        self._log(job, "")
        self._log(job, f"Conversion {settings['label']} après capture :")
        self._log(job, " ".join(cmd))

        try:
            timeout = finalize_timeout(ts_file, TRANSCODE_TIMEOUT_BASE, TRANSCODE_TIMEOUT_PER_GB)
            process, expired, _lines = self._run_finalize_process(
                job, cmd, f"Conversion {settings['label']}", timeout
            )

            if not expired and process.returncode == 0 and os.path.isfile(output):
                job.final_file = output
                job.state = CaptureState.TERMINE
                self._log(job, f"Conversion terminée : {output}")
            else:
                job.final_file = ts_file
                job.error = (
                    f"Conversion interrompue : délai de {timeout} s dépassé."
                    if expired
                    else "La conversion a échoué ou a été arrêtée."
                )
                job.state = CaptureState.ERREUR
                self._log(job, f"{job.error} Le TS est conservé : {ts_file}")
        except Exception as e:
            job.process = None
            job.final_file = ts_file
            job.error = str(e)
            job.state = CaptureState.ERREUR
            self._log(job, f"Erreur de conversion : {e}")

        self._notify()

    # ------------------------------------------------------------------
    # Découpe (après remux/conversion)
    # ------------------------------------------------------------------
    def cut_file(self, job, start_seconds, end_seconds):
        threading.Thread(
            target=self._cut_worker, args=(job, start_seconds, end_seconds), daemon=True
        ).start()

    def _cut_worker(self, job, start_seconds, end_seconds):
        tools = self._tools()
        source = job.final_file

        if not tools.ffmpeg or not source or not os.path.isfile(source):
            self._log(job, "[Découpe] Impossible : FFmpeg ou fichier source introuvable.")
            return

        stem, ext = os.path.splitext(source)
        output = f"{stem}_coupe{ext}"
        counter = 2
        while os.path.exists(output):
            output = f"{stem}_coupe{counter}{ext}"
            counter += 1

        cmd = [
            tools.ffmpeg, "-y",
            "-ss", format_timecode(start_seconds),
            "-to", format_timecode(end_seconds),
            "-i", source,
            "-c", "copy",
            output,
        ]
        self._log(job, "[Découpe] Commande FFmpeg :")
        self._log(job, "[Découpe] " + " ".join(cmd))

        try:
            timeout = finalize_timeout(source, CUT_TIMEOUT_BASE, CUT_TIMEOUT_PER_GB)
            proc, expired, _lines = self._run_finalize_process(
                job, cmd, "Découpe", timeout
            )

            if not expired and proc.returncode == 0 and os.path.isfile(output):
                job.cut_file = output
                self._log(job, f"[Découpe] Fichier coupé : {output}")
            elif expired:
                self._log(job, f"[Découpe] Délai de {timeout} s dépassé — découpe interrompue.")
            else:
                self._log(job, "[Découpe] Échec de la découpe.")
        except Exception as e:
            self._log(job, f"[Découpe] Erreur : {e}")

        self._notify()
