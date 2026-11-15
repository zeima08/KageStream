import os
import threading
import urllib.request

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, GLib, GdkPixbuf

from kagestream.media.ytdlp import analysis_error_message
from kagestream.providers import find_provider
from kagestream.metadata.models import FORMAT_CHOICES, PROFILES
from kagestream.ui.widgets import (
    action_bar,
    add_row,
    bind_enter,
    button,
    form_grid,
    muted_label,
    page_container,
    section,
)


def build_music_page(window):
    outer, content = page_container(
        "Musique",
        "Colle un lien YouTube Music, SoundCloud ou Bandcamp, puis analyse-le.",
    )

    # --- Source ---------------------------------------------------------
    source_card = section("Source")
    url_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    url_entry = Gtk.Entry()
    url_entry.set_placeholder_text("Colle une URL YouTube Music, SoundCloud ou Bandcamp…")
    url_entry.set_hexpand(True)
    analyze_button = button("Analyser", primary=True,
                            tooltip="Interroge yt-dlp et affiche l’album et ses pistes.")
    url_row.pack_start(url_entry, True, True, 0)
    url_row.pack_start(analyze_button, False, False, 0)
    source_card.pack_start(url_row, False, False, 0)

    status_label = muted_label("")
    status_label.set_no_show_all(True)
    status_label.hide()
    source_card.pack_start(status_label, False, False, 0)
    content.pack_start(source_card, False, False, 0)

    # --- Album ----------------------------------------------------------
    result_card = section("Album")
    result_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
    result_card.pack_start(result_box, False, False, 0)

    cover_image = Gtk.Image()
    cover_image.set_size_request(110, 110)
    result_box.pack_start(cover_image, False, False, 0)

    info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    result_box.pack_start(info_box, True, True, 0)
    title_label = Gtk.Label(xalign=0)
    artist_label = Gtk.Label(xalign=0)
    meta_label = muted_label("")
    for label in (title_label, artist_label):
        label.set_line_wrap(True)
    info_box.pack_start(title_label, False, False, 0)
    info_box.pack_start(artist_label, False, False, 0)
    info_box.pack_start(meta_label, False, False, 0)

    selection_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    select_all_button = button("Tout cocher", tooltip="Sélectionne toutes les pistes.")
    select_none_button = button("Tout décocher", tooltip="Désélectionne toutes les pistes.")
    selection_row.pack_start(select_all_button, False, False, 0)
    selection_row.pack_start(select_none_button, False, False, 0)
    result_card.pack_start(selection_row, False, False, 0)

    tracks_listbox = Gtk.ListBox()
    tracks_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
    # Pas de scroller imbriqué : la page entière défile, la liste s'étend.
    tracks_listbox.set_size_request(-1, 200)
    result_card.pack_start(tracks_listbox, False, False, 0)
    # Masquée tant qu'aucun album n'est analysé : sinon une grande carte vide
    # occupe la moitié de la page.
    result_card.set_no_show_all(True)
    result_card.hide()
    content.pack_start(result_card, False, False, 0)

    # --- Destination ----------------------------------------------------
    options_card = section("Destination")
    options_grid = form_grid()

    profile_combo = Gtk.ComboBoxText()
    for profile_id, profile in PROFILES.items():
        profile_combo.append(profile_id, profile["label"])
    profile_combo.set_active_id("compatible")

    format_combo = Gtk.ComboBoxText()
    for format_id, label in FORMAT_CHOICES:
        format_combo.append(format_id, label)
    format_combo.set_active_id("mp3")
    format_combo.set_sensitive(False)

    default_music_dir = os.path.join(os.path.expanduser("~"), "Musique")
    try:
        os.makedirs(default_music_dir, exist_ok=True)
    except OSError:
        default_music_dir = os.path.expanduser("~")

    folder_chooser = Gtk.FileChooserButton(
        title="Dossier de destination",
        action=Gtk.FileChooserAction.SELECT_FOLDER,
    )
    folder_chooser.set_filename(default_music_dir)

    add_row(options_grid, 0, "Profil", profile_combo,
            tooltip="Compatible (MP3 192k), Qualité maximale, Archivage (FLAC) ou Personnalisé.")
    add_row(options_grid, 1, "Format", format_combo,
            tooltip="Utilisé uniquement avec le profil « Personnalisé ».")
    add_row(options_grid, 2, "Dossier", folder_chooser)

    options_card.pack_start(options_grid, False, False, 0)
    content.pack_start(options_card, False, False, 0)

    # --- Barre d'action -------------------------------------------------
    bar = action_bar()
    download_button = button(
        "Télécharger la sélection", primary=True,
        tooltip="Ajoute les pistes cochées à la file de téléchargement.",
    )
    download_button.set_sensitive(False)
    bar.pack_end(download_button, False, False, 0)
    outer.pack_start(bar, False, False, 0)

    bind_enter(url_entry, lambda: on_analyze_clicked(None))

    state = {"album": None, "rows": []}

    def set_status(text):
        def apply():
            status_label.set_text(text)
            status_label.show()
            return False
        GLib.idle_add(apply)

    def on_profile_changed(_combo):
        profile_id = profile_combo.get_active_id() or "compatible"
        profile = PROFILES.get(profile_id, PROFILES["custom"])
        if profile_id == "custom":
            format_combo.set_sensitive(True)
        else:
            format_combo.set_sensitive(False)
            format_combo.set_active_id(profile["format"])

    profile_combo.connect("changed", on_profile_changed)

    def clear_tracks():
        for child in list(tracks_listbox.get_children()):
            tracks_listbox.remove(child)
        state["rows"] = []

    def populate_tracks(album):
        clear_tracks()
        for track in album.tracks:
            row = Gtk.ListBoxRow()
            row_box = Gtk.Box(spacing=8)
            row_box.set_border_width(4)
            check = Gtk.CheckButton()
            check.set_active(True)

            duration_text = ""
            if track.duration:
                minutes, seconds = divmod(int(track.duration), 60)
                duration_text = f" ({minutes}:{seconds:02d})"

            label = Gtk.Label(label=f"{track.index:02d} — {track.title}{duration_text}", xalign=0)
            label.set_hexpand(True)
            row_box.pack_start(check, False, False, 0)
            row_box.pack_start(label, True, True, 0)
            row.add(row_box)
            row.kagestream_check = check
            row.kagestream_track = track
            tracks_listbox.add(row)
            state["rows"].append(row)
        tracks_listbox.show_all()

    def selected_indexes():
        return {
            row.kagestream_track.index
            for row in state["rows"]
            if row.kagestream_check.get_active()
        }

    def on_select_all(_button):
        for row in state["rows"]:
            row.kagestream_check.set_active(True)

    def on_select_none(_button):
        for row in state["rows"]:
            row.kagestream_check.set_active(False)

    select_all_button.connect("clicked", on_select_all)
    select_none_button.connect("clicked", on_select_none)

    def load_cover(url):
        # Chargement de la pochette en tâche de fond, best-effort.
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "KageStream"})
            with urllib.request.urlopen(request, timeout=10) as response:
                data = response.read()
            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            if pixbuf:
                pixbuf = pixbuf.scale_simple(110, 110, GdkPixbuf.InterpType.BILINEAR)
                GLib.idle_add(cover_image.set_from_pixbuf, pixbuf)
        except Exception:
            pass

    def analyze_worker(url):
        try:
            provider = find_provider(url)
            if provider is None:
                set_status("URL non reconnue (YouTube Music, SoundCloud ou Bandcamp attendus).")
                return

            set_status(f"Analyse {provider.label} en cours...")
            album, error = provider.analyze(
                url,
                window.ytdlp,
                window.javascript_runtime_name,
                window.javascript_runtime_path,
                log_callback=window.log_text,
                cookies_browser=window.youtube_cookies_browser,
            )

            if not album:
                window.log_text(error)
                title, message = analysis_error_message(error)
                set_status(f"{title} : {message}")
                return

            state["album"] = album

            def apply_result():
                title_label.set_markup(f"<b>{GLib.markup_escape_text(album.title)}</b>")
                artist_label.set_text(album.artist or "Artiste inconnu")
                meta_label.set_text(
                    f"{provider.label} — {len(album.tracks)} piste(s)"
                    + (f" — {album.year}" if album.year else "")
                )
                cover_image.clear()
                populate_tracks(album)
                download_button.set_sensitive(True)
                return False

            GLib.idle_add(apply_result)
            set_status(f"{len(album.tracks)} piste(s) trouvée(s).")

            if album.artwork_url:
                threading.Thread(target=load_cover, args=(album.artwork_url,), daemon=True).start()

        except Exception as e:
            # Sans ce garde-fou, une exception imprévue (ex. métadonnée inattendue
            # renvoyée par yt-dlp) tuait le thread en silence et laissait le
            # bouton Analyser désactivé jusqu'au redémarrage.
            window.log_text(f"[Musique] Erreur pendant l’analyse : {e}")
            set_status(f"Analyse impossible : {e}")
        finally:
            GLib.idle_add(analyze_button.set_sensitive, True)

    def on_analyze_clicked(_button):
        url = url_entry.get_text().strip()
        if not url:
            set_status("Colle une URL avant d’analyser.")
            return
        if not window.ytdlp:
            set_status("yt-dlp est introuvable — installe-le depuis Outils → Dépendances.")
            return

        analyze_button.set_sensitive(False)
        download_button.set_sensitive(False)
        set_status("Analyse en cours...")
        threading.Thread(target=analyze_worker, args=(url,), daemon=True).start()

    analyze_button.connect("clicked", on_analyze_clicked)

    def on_download_clicked(_button):
        album = state["album"]
        if not album:
            return

        indexes = selected_indexes()
        if not indexes:
            set_status("Sélectionne au moins une piste avant de télécharger.")
            return

        profile_id = profile_combo.get_active_id() or "compatible"
        profile = PROFILES.get(profile_id, PROFILES["custom"])
        format_id = format_combo.get_active_id() if profile_id == "custom" else profile["format"]
        destination_root = folder_chooser.get_filename() or default_music_dir

        window.download_manager.enqueue(
            album,
            destination_root,
            format_id,
            profile.get("quality", "0"),
            embed_metadata=True,
            embed_thumbnail=True,
            selected_indexes=indexes,
        )
        set_status("Ajouté à la file de téléchargement — suis la progression dans « Téléchargements ».")
        window.stack.set_visible_child_name("downloads")

    download_button.connect("clicked", on_download_clicked)

    return outer
