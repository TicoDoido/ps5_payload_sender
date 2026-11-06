from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from ps5_ftp import FTPEntry, PS5FTPClient


def parse_capture_game_name(dat_data: bytes) -> str:
    """Decode game name from the PS5 capture .dat sidecar at offset 0x44."""
    raw = dat_data[0x44:0x44 + 256].split(b"\0", 1)[0]
    if not raw:
        return ""
    name = raw.decode("utf-8", errors="replace").strip()
    parts = name.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) == 14 and parts[1].isdigit():
        name = parts[0]
    return name.strip()


def capture_title_id(entry: FTPEntry) -> str:
    """Extract the title ID from .../photo|video/NPXS40087/<TitleID>/<bucket>/<file>."""
    segments = [part for part in entry.path.split("/") if part]
    try:
        media_index = next(i for i, part in enumerate(segments) if part in ("photo", "video"))
        return segments[media_index + 2]
    except (StopIteration, IndexError):
        return ""


def _format_epoch_ms(value: Any) -> str:
    try:
        timestamp = float(value) / 1000.0
        if not 0 < timestamp < 4102444800:
            return ""
        return datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def capture_datetime(entry: FTPEntry, meta: dict[str, Any] | None = None) -> str:
    """Prefer the capture timestamp from .meta, then fall back to its filename."""
    if meta:
        segment = meta.get("segmentInfo")
        if isinstance(segment, dict):
            absolute = segment.get("absoluteTime")
            if isinstance(absolute, list) and absolute:
                first = absolute[0]
                if isinstance(first, list) and first:
                    formatted = _format_epoch_ms(first[0])
                    if formatted:
                        return formatted
            for key in ("start", "end"):
                formatted = _format_epoch_ms(segment.get(key))
                if formatted:
                    return formatted

    stem = entry.name.rsplit(".", 1)[0]
    match = re.match(r"^(\d{8})_(\d{6})_", stem)
    if not match:
        return ""
    try:
        value = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
        return value.strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return ""


def _decode_meta(meta_data: bytes) -> dict[str, Any]:
    if not meta_data:
        return {}
    try:
        parsed = json.loads(meta_data.decode("utf-8-sig"))
        return parsed if isinstance(parsed, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def build_capture_details(
    client: PS5FTPClient,
    entries: list[FTPEntry],
) -> dict[str, dict[str, Any]]:
    """Pair JXR/JPG/MP4 files with sibling DAT/META files and cache metadata per title."""
    details: dict[str, dict[str, Any]] = {}
    directory_cache: dict[str, dict[str, FTPEntry]] = {}
    title_name_cache: dict[str, str] = {}

    for entry in entries:
        parent = entry.path.rsplit("/", 1)[0]
        if parent not in directory_cache:
            directory_cache[parent] = {
                child.name: child
                for child in client.list_dir(parent)
                if not child.is_dir
            }

        stem = entry.name.rsplit(".", 1)[0]
        dat_name = stem + ".dat"
        meta_name = stem + ".meta"
        dat_entry = directory_cache[parent].get(dat_name)
        meta_entry = directory_cache[parent].get(meta_name)
        title_id = capture_title_id(entry)

        game_name = title_name_cache.get(title_id, "")
        if title_id not in title_name_cache:
            if dat_entry:
                try:
                    dat_data = client.read_bytes(dat_entry.path, max_bytes=0x44 + 256)
                    game_name = parse_capture_game_name(dat_data)
                except Exception:
                    game_name = ""
            title_name_cache[title_id] = game_name

        meta: dict[str, Any] = {}
        if meta_entry:
            try:
                meta = _decode_meta(client.read_bytes(meta_entry.path, max_bytes=16 * 1024))
            except Exception:
                meta = {}

        details[entry.path] = {
            "title_id": title_id,
            "game_name": game_name,
            "captured_at": capture_datetime(entry, meta),
            "has_dat": dat_entry is not None,
            "has_meta": meta_entry is not None,
            "dat_path": dat_entry.path if dat_entry else "",
            "meta_path": meta_entry.path if meta_entry else "",
            "app_version": str(meta.get("appVer", "")),
            "app_version_title_id": str(meta.get("appVerTitleId", "")),
            "metadata": meta,
        }

    return details

