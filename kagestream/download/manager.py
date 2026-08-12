import os
import queue
import subprocess
import threading
import uuid

from gi.repository import GLib

from kagestream.download.job import DownloadJob, JobState, TrackJob
from kagestream.media.process import escalate_process_stop
from kagestream.media.ytdlp import extract_final_path, parse_download_progress
from kagestream.utils.filenames import safe_join_under, sanitize_path_component


class DownloadManager:
    """File d'attente de téléchargements musicaux (YouTube Music / SoundCloud /
    Bandcamp) : un seul job traité à la fois par un thread dédié, comme le
    modèle « une opération active » déjà utilisé par la capture. Toute mise à
    jour vers GTK passe par GLib.idle_add — aucun accès GTK depuis ce thread."""

    def __init__(self, window):
        self.window = window
        self.jobs = []
        self._listeners = []
        self._queue = queue.Queue()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

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
        job.cancel_requested = True
        if job.process is not None:
            escalate_process_stop(job.process, log_callback=self.window.log_text)
        self._notify()

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

        ytdlp_path = self.window.ytdlp
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

    def _download_track(self, job, track_job, ytdlp_path):
        track = track_job.track
        window = self.window

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
            window.log_text(f"[Musique] Erreur de destination : {e}")
            self._notify()
            return

        filename_stem = sanitize_path_component(f"{track.index:02d} - {track.title}")
        output_template = os.path.join(destination_dir, filename_stem + ".%(ext)s")

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

        if job.format_id and job.format_id != "original":
            cmd.extend(["-x", "--audio-format", job.format_id, "--audio-quality", str(job.quality)])
        if job.embed_metadata:
            cmd.append("--embed-metadata")
        if job.embed_thumbnail:
            cmd.append("--embed-thumbnail")

        if window.javascript_runtime_name and window.javascript_runtime_path:
            cmd.extend([
                "--js-runtimes",
                f"{window.javascript_runtime_name}:{window.javascript_runtime_path}"
            ])
        if window.ffmpeg:
            cmd.extend(["--ffmpeg-location", os.path.dirname(window.ffmpeg)])

        cmd.extend(["--", track.url])

        window.log_text("[Musique] Commande yt-dlp :")
        window.log_text("[Musique] " + " ".join(cmd))

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            job.process = process

            for line in process.stdout:
                clean = line.rstrip()
                if not clean:
                    continue
                window.log_text(f"[Musique] {clean}")

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

            if job.cancel_requested:
                track_job.state = JobState.ANNULE
            elif process.returncode == 0:
                track_job.state = JobState.TERMINE
                track_job.progress_percent = 100.0
            else:
                track_job.state = JobState.ERREUR
                track_job.error = f"yt-dlp s’est arrêté avec le code {process.returncode}."
                window.log_text(f"[Musique] {track_job.error}")

        except Exception as e:
            job.process = None
            track_job.state = JobState.ERREUR
            track_job.error = str(e)
            window.log_text(f"[Musique] Erreur : {e}")

        self._notify()
