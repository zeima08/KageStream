import os
import queue
import subprocess
import sys
import threading
import uuid

from gi.repository import GLib

from kagestream.download.job import DownloadJob, JobState, TrackJob
from kagestream.media.process import escalate_process_stop, escalate_processes_stop
from kagestream.media.ytdlp import (
    cookie_retry_candidates,
    extract_final_path,
    is_bot_check_error,
    parse_download_progress,
    youtube_cookie_args,
)
from kagestream.utils.filenames import safe_join_under, sanitize_path_component


class DownloadTools:
    """Contexte d'exécution des téléchargements musicaux, sans dépendance à
    une fenêtre GTK : chemins d'outils, réglages de session, journal et
    callback de forçage des cookies YouTube."""

    def __init__(self, ytdlp=None, ffmpeg=None, aria2c=None,
                 javascript_runtime_name=None, javascript_runtime_path=None,
                 cookies_browser=None, log_callback=None, browser_forcer=None):
        self.ytdlp = ytdlp
        self.ffmpeg = ffmpeg
        self.aria2c = aria2c
        self.javascript_runtime_name = javascript_runtime_name
        self.javascript_runtime_path = javascript_runtime_path
        self.cookies_browser = cookies_browser
        self.log_callback = log_callback
        self.browser_forcer = browser_forcer

    def log(self, text):
        if self.log_callback:
            self.log_callback(text)

    def force_browser(self, browser):
        if self.browser_forcer:
            self.browser_forcer(browser)


class DownloadManager:
    """File d'attente de téléchargements musicaux (YouTube Music / SoundCloud /
    Bandcamp) : un seul job traité à la fois par un thread dédié, comme le
    modèle « une opération active » déjà utilisé par la capture. Toute mise à
    jour vers GTK passe par GLib.idle_add — aucun accès GTK depuis ce thread."""

    def __init__(self, tools_provider):
        """`tools_provider` retourne un DownloadTools à jour à chaque appel."""
        self._tools_provider = tools_provider
        self.jobs = []
        self._listeners = []
        self._queue = queue.Queue()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _tools(self):
        return self._tools_provider()

    def add_listener(self, callback):
        self._listeners.append(callback)

    def _notify(self):
        for callback in list(self._listeners):
            GLib.idle_add(callback)

    def enqueue(self, album, destination_root, format_id, quality,
                embed_metadata=True, embed_thumbnail=True, selected_indexes=None):
        tracks = [
            TrackJob(
                track=track,
                selected=(selected_indexes is None or track.index in selected_indexes),
            )
            for track in album.tracks
        ]
        job = DownloadJob(
            id=str(uuid.uuid4()),
            album=album,
            destination_root=destination_root,
            format_id=format_id,
            quality=quality,
            embed_metadata=embed_metadata,
            embed_thumbnail=embed_thumbnail,
            tracks=tracks,
        )
        self.jobs.append(job)
        self._queue.put(job)
        self._notify()
        return job

    def cancel(self, job):
        # Marquer la demande immédiatement, puis arrêter le processus dans un
        # thread dédié : escalate_process_stop peut bloquer jusqu'à 11 s
        # (SIGINT + SIGTERM + SIGKILL), ce qui gèlerait l'interface si cancel()
        # était appelé depuis un handler de bouton GTK.
        if job.cancel_requested:
            return
        job.cancel_requested = True
        self._notify()
        threading.Thread(target=self._cancel_worker, args=(job,), daemon=True).start()

    def _cancel_worker(self, job):
        process = job.process
        if process is not None:
            escalate_process_stop(process, log_callback=self._tools().log)

    def remove_job(self, job):
        """Retire un téléchargement terminé, annulé ou en erreur de la liste.
        Les fichiers téléchargés ne sont jamais touchés."""
        if job.state in (JobState.EN_ATTENTE, JobState.TELECHARGEMENT, JobState.ANALYSE):
            return False
        if job in self.jobs:
            self.jobs.remove(job)
            self._notify()
        return False

    def clear_finished(self):
        done = (JobState.TERMINE, JobState.ANNULE, JobState.ERREUR)
        self.jobs = [job for job in self.jobs if job.state not in done]
        self._notify()
        return False

    def shutdown(self):
        """Arrête le téléchargement musical en cours — appelé à la fermeture de
        la fenêtre : le processus yt-dlp tourne dans un groupe dédié et
        survivrait à l'application."""
        procs = []
        for job in self.jobs:
            job.cancel_requested = True
            if job.process is not None and job.process.poll() is None:
                procs.append(job.process)
        escalate_processes_stop(procs, log_callback=self._tools().log)

    def _run(self):
        while True:
            job = self._queue.get()
            if job.cancel_requested:
                job.state = JobState.ANNULE
                self._notify()
                continue
            self._process_job(job)

    def _process_job(self, job):
        job.state = JobState.TELECHARGEMENT
        self._notify()

        ytdlp_path = self.tools.ytdlp
        if not ytdlp_path:
            job.state = JobState.ERREUR
            job.error = "yt-dlp est introuvable."
            self._notify()
            return

        for track_job in job.tracks:
            if not track_job.selected:
                continue
            if job.cancel_requested:
                break

            track_job.state = JobState.TELECHARGEMENT
            self._notify()
            self._download_track(job, track_job, ytdlp_path)

        job.state = JobState.ANNULE if job.cancel_requested else JobState.TERMINE
        self._notify()

    def _build_track_command(self, job, track_job, ytdlp_path, output_template,
                             cookies_browser=None):
        track = track_job.track
        tools = self._tools()

        cmd = [
            ytdlp_path,
            "--ignore-config",
            "--newline",
            "--progress",
            "--no-playlist",
            "--no-overwrites",
            "--continue",
            "--output", output_template,
            "--print", "after_move:KAGESTREAM_FINAL:%(filepath)s",
        ]

        cmd.extend(youtube_cookie_args(track.url, cookies_browser or tools.cookies_browser))

        if job.format_id and job.format_id != "original":
            cmd.extend(["-x", "--audio-format", job.format_id, "--audio-quality", str(job.quality)])
        if job.embed_metadata:
            cmd.append("--embed-metadata")
        if job.embed_thumbnail:
            cmd.append("--embed-thumbnail")

        if tools.javascript_runtime_name and tools.javascript_runtime_path:
            cmd.extend([
                "--js-runtimes",
                f"{tools.javascript_runtime_name}:{tools.javascript_runtime_path}"
            ])
        if tools.ffmpeg:
            cmd.extend(["--ffmpeg-location", os.path.dirname(tools.ffmpeg)])
        if tools.aria2c:
            cmd.extend([
                "--external-downloader", tools.aria2c,
                "--external-downloader-args", "aria2c:-x16 -s16 -k1M",
            ])

        cmd.extend(["--", track.url])
        return cmd

    def _run_track_process(self, job, track_job, cmd):
        """Lance yt-dlp pour une piste, journalise sa sortie et retourne
        (code de retour, lignes capturées)."""
        tools = self._tools()
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
            start_new_session=(sys.platform != "win32"),
        )
        job.process = process

        captured = []
        for line in process.stdout:
            clean = line.rstrip()
            if not clean:
                continue
            captured.append(clean)
            tools.log(f"[Musique] {clean}")

            final_path = extract_final_path(clean)
            if final_path:
                track_job.final_path = final_path

            progress = parse_download_progress(clean)
            if progress:
                percent_text, _rest = progress
                try:
                    track_job.progress_percent = float(percent_text.rstrip("%"))
                except ValueError:
                    pass
                self._notify()

        process.wait()
        job.process = None
        return process.returncode, captured

    def _download_track(self, job, track_job, ytdlp_path):
        track = track_job.track
        tools = self._tools()

        try:
            destination_dir = safe_join_under(
                job.destination_root,
                job.album.artist or "Artiste inconnu",
                job.album.title or "Album",
            )
            os.makedirs(destination_dir, exist_ok=True)
        except Exception as e:
            track_job.state = JobState.ERREUR
            track_job.error = str(e)
            tools.log(f"[Musique] Erreur de destination : {e}")
            self._notify()
            return

        filename_stem = sanitize_path_component(f"{track.index:02d} - {track.title}")
        output_template = os.path.join(destination_dir, filename_stem + ".%(ext)s")

        cookies_used = bool(youtube_cookie_args(track.url, tools.cookies_browser))
        cmd = self._build_track_command(job, track_job, ytdlp_path, output_template)

        tools.log("[Musique] Commande yt-dlp :")
        tools.log("[Musique] " + " ".join(cmd))

        try:
            returncode, captured = self._run_track_process(job, track_job, cmd)

            # Blocage anti-robot YouTube : forcer les cookies d'un navigateur
            # détecté et relancer, même sans sélection dans Outils.
            if (returncode != 0 and not job.cancel_requested and not cookies_used
                    and is_bot_check_error("\n".join(captured))):
                candidates = cookie_retry_candidates(limit=1)
                forced_browser = candidates[0] if candidates else None
                if forced_browser and youtube_cookie_args(track.url, forced_browser):
                    tools.log(
                        f"[Musique] Blocage anti-robot YouTube — relance avec "
                        f"les cookies de {forced_browser}."
                    )
                    tools.force_browser(forced_browser)
                    cmd = self._build_track_command(
                        job, track_job, ytdlp_path, output_template,
                        cookies_browser=forced_browser,
                    )
                    tools.log("[Musique] Commande yt-dlp (avec cookies forcés) :")
                    tools.log("[Musique] " + " ".join(cmd))
                    returncode, captured = self._run_track_process(job, track_job, cmd)
                elif not candidates:
                    tools.log(
                        "[Musique] Blocage anti-robot YouTube — aucun navigateur "
                        "compatible (Firefox, Chrome, Edge…) n’a été détecté."
                    )

            if job.cancel_requested:
                track_job.state = JobState.ANNULE
            elif returncode == 0:
                track_job.state = JobState.TERMINE
                track_job.progress_percent = 100.0
            else:
                track_job.state = JobState.ERREUR
                track_job.error = f"yt-dlp s’est arrêté avec le code {returncode}."
                tools.log(f"[Musique] {track_job.error}")

        except Exception as e:
            job.process = None
            track_job.state = JobState.ERREUR
            track_job.error = str(e)
            tools.log(f"[Musique] Erreur : {e}")

        self._notify()
