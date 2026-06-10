"""Persistent state tracking to avoid re-downloading tracks."""

import json
import logging
from pathlib import Path

from .config import STATE_FILE

logger = logging.getLogger(__name__)


class StateManager:
    """Tracks which tracks have been seen and downloaded.

    State schema:
    {
        "playlists": {
            "<playlist_url>": {
                "name": "<playlist_name>",
                "seen_track_ids": ["12345", "67890", ...],
                "downloaded": {
                    "12345": {
                        "artist": "...",
                        "title": "...",
                        "local_path": "...",
                        "downloaded_at": "2026-01-01T00:00:00"
                    }
                }
            }
        }
    }
    """

    def __init__(self, state_file: Path | None = None):
        self.state_file = state_file or STATE_FILE
        self._state: dict = {"playlists": {}}
        self.load()

    def load(self) -> None:
        if self.state_file.exists():
            try:
                self._state = json.loads(self.state_file.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Could not load state file: %s", e)
                self._state = {"playlists": {}}

    def save(self) -> None:
        self.state_file.write_text(json.dumps(self._state, indent=2))

    def get_seen_ids(self, playlist_url: str) -> set[str]:
        playlist = self._state["playlists"].get(playlist_url, {})
        return set(playlist.get("seen_track_ids", []))

    def mark_seen(self, playlist_url: str, track_ids: list[str]) -> None:
        if playlist_url not in self._state["playlists"]:
            self._state["playlists"][playlist_url] = {"seen_track_ids": [], "downloaded": {}}
        existing = set(self._state["playlists"][playlist_url].get("seen_track_ids", []))
        existing.update(track_ids)
        self._state["playlists"][playlist_url]["seen_track_ids"] = list(existing)

    def mark_downloaded(self, playlist_url: str, track_id: str, artist: str, title: str, local_path: str) -> None:
        if playlist_url not in self._state["playlists"]:
            self._state["playlists"][playlist_url] = {"seen_track_ids": [], "downloaded": {}}
        from datetime import datetime, timezone
        self._state["playlists"][playlist_url]["downloaded"][track_id] = {
            "artist": artist,
            "title": title,
            "local_path": local_path,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save()

    def set_playlist_name(self, playlist_url: str, name: str) -> None:
        if playlist_url not in self._state["playlists"]:
            self._state["playlists"][playlist_url] = {"seen_track_ids": [], "downloaded": {}}
        self._state["playlists"][playlist_url]["name"] = name
