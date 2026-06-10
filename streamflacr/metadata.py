"""FLAC metadata tagging via mutagen.

Writes artist, title, album, label (set to the SoundCloud playlist name),
and other standard Vorbis comment fields.
"""

import logging
from pathlib import Path

from mutagen.flac import FLAC

logger = logging.getLogger(__name__)


def tag_flac(
    filepath: Path,
    artist: str,
    title: str,
    playlist_name: str,
    album: str | None = None,
    genre: str | None = None,
    year: str | None = None,
) -> None:
    """Write metadata to a FLAC file.

    The 'label' field (Vorbis comment LABEL / publisher) is set to the
    SoundCloud playlist name so Serato smart crates can match on it.
    """
    audio = FLAC(str(filepath))

    audio["artist"] = artist
    audio["title"] = title
    audio["label"] = playlist_name  # This is the key Serato field

    if album:
        audio["album"] = album
    if genre:
        audio["genre"] = genre
    if year:
        audio["date"] = year

    audio.save()
    logger.info("Tagged %s: artist=%s, title=%s, label=%s", filepath.name, artist, title, playlist_name)
