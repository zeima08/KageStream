import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

from kagestream.utils.filenames import sanitize_filename


def playlist_title_from_location(location):
    try:
        parsed = urlparse(location)
        path = unquote(parsed.path).rstrip("/")
        name = os.path.basename(path)
        return sanitize_filename(name) or parsed.hostname or location
    except Exception:
        return location


def resolve_playlist_location(location, playlist_path):
    location = (location or "").strip()
    if not location:
        return ""

    if re.match(r"^[A-Za-z]:[\\/]", location) or os.path.isabs(location):
        return location

    parsed = urlparse(location)
    if parsed.scheme:
        return location

    return os.path.abspath(os.path.join(os.path.dirname(playlist_path), location))


def deduplicate_playlist_entries(entries):
    unique = []
    seen = set()

    for entry in entries:
        url = entry.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(entry)

    return unique


def parse_m3u_file(path):
    entries = []
    current_title = ""
    current_group = ""

    with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue

            if line.upper().startswith("#EXTINF:"):
                metadata, separator, label = line.partition(",")
                current_title = label.strip() if separator else ""

                group_match = re.search(
                    r'group-title\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
                    metadata,
                    flags=re.IGNORECASE
                )
                if group_match:
                    current_group = (group_match.group(1) or group_match.group(2) or "").strip()

                if not current_title:
                    name_match = re.search(
                        r'tvg-name\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
                        metadata,
                        flags=re.IGNORECASE
                    )
                    if name_match:
                        current_title = (name_match.group(1) or name_match.group(2) or "").strip()
                continue

            if line.upper().startswith("#EXTGRP:"):
                current_group = line.split(":", 1)[1].strip()
                continue

            if line.startswith("#"):
                continue

            location = resolve_playlist_location(line, path)
            if location:
                entries.append({
                    "title": current_title or playlist_title_from_location(location),
                    "group": current_group,
                    "url": location,
                })

            current_title = ""
            current_group = ""

    return deduplicate_playlist_entries(entries)


def xml_child_text(element, local_name):
    for child in list(element):
        tag = child.tag.rsplit("}", 1)[-1] if isinstance(child.tag, str) else ""
        if tag == local_name:
            return (child.text or "").strip()
    return ""


def parse_xspf_file(path):
    entries = []
    tree = ET.parse(path)

    for track in tree.getroot().iter():
        tag = track.tag.rsplit("}", 1)[-1] if isinstance(track.tag, str) else ""
        if tag != "track":
            continue

        location = resolve_playlist_location(xml_child_text(track, "location"), path)
        if not location:
            continue

        title = xml_child_text(track, "title") or playlist_title_from_location(location)
        group = xml_child_text(track, "album") or xml_child_text(track, "creator")
        entries.append({"title": title, "group": group, "url": location})

    return deduplicate_playlist_entries(entries)


def parse_playlist_file(path):
    extension = os.path.splitext(path)[1].lower()
    if extension in (".m3u", ".m3u8"):
        return parse_m3u_file(path)
    if extension == ".xspf":
        return parse_xspf_file(path)
    return []
