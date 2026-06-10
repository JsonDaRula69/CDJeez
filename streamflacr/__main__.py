"""StreamFLACr main daemon.

Monitors ALL SoundCloud playlists for the authenticated user, searches
Soulseek for FLAC versions of new tracks, downloads them, tags metadata,
and creates matching Serato smart crates.
"""

import asyncio
import logging
from pathlib import Path

from .config import (
    DOWNLOAD_DIR,
    SEARCH_TIMEOUT,
    SOUNDCLOUD_POLL_INTERVAL,
    SOUNDCLOUD_USER_URL,
)
from .metadata import tag_flac
from .notify import send_notification
from .serato_crate import ensure_smart_crate
from .soundcloud import (
    PlaylistInfo,
    TrackInfo,
    discover_user_playlists,
    fetch_playlist_tracks,
    refresh_playlist_tracks,
    _api_get,
)
from .soulseek import SoulseekDownloader
from .state import StateManager

logger = logging.getLogger("streamflacr")


async def process_new_track(
    track: TrackInfo,
    playlist_name: str,
    slsk: SoulseekDownloader,
    state: StateManager,
    playlist_url: str,
) -> Path | None:
    """Search, download, tag, and integrate a single track. Returns local path on success."""
    logger.info("Processing: %s - %s", track.artist, track.title)

    candidates = await slsk.search_flac(track.artist, track.title, timeout=SEARCH_TIMEOUT)
    if not candidates:
        logger.warning("No FLAC found on Soulseek for: %s - %s", track.artist, track.title)
        send_notification("StreamFLACr", f"No FLAC found: {track.artist} - {track.title}")
        return None

    for candidate in candidates[:3]:
        local_path = await slsk.download(candidate["username"], candidate["remote_path"])
        if local_path and local_path.exists():
            tag_flac(
                filepath=local_path,
                artist=track.artist,
                title=track.title,
                playlist_name=playlist_name,
            )
            state.mark_downloaded(
                playlist_url=playlist_url,
                track_id=track.track_id,
                artist=track.artist,
                title=track.title,
                local_path=str(local_path),
            )
            send_notification("StreamFLACr", f"Downloaded: {track.artist} - {track.title}")
            return local_path

    logger.error("All download attempts failed for: %s - %s", track.artist, track.title)
    send_notification("StreamFLACr", f"Download failed: {track.artist} - {track.title}")
    return None


async def sync_playlist(
    playlist: PlaylistInfo,
    slsk: SoulseekDownloader,
    state: StateManager,
) -> None:
    """Check a single playlist for new tracks and download FLAC for them."""
    playlist_url = playlist.url
    playlist_name = playlist.title

    # Ensure there's a smart crate for this playlist
    ensure_smart_crate(playlist_name)

    # Fetch current tracks
    tracks = fetch_playlist_tracks(playlist_url)
    if not tracks:
        logger.debug("No tracks found in playlist: %s", playlist_name)
        return

    current_ids = {t.track_id for t in tracks}
    seen_ids = state.get_seen_ids(playlist_url)
    new_ids = current_ids - seen_ids

    if not new_ids:
        return

    logger.info("Found %d new track(s) in '%s'", len(new_ids), playlist_name)
    new_tracks = [t for t in tracks if t.track_id in new_ids]

    for track in new_tracks:
        try:
            await process_new_track(track, playlist_name, slsk, state, playlist_url)
        except Exception as e:
            logger.error("Error processing track %s: %s", track.title, e)

    # Mark all new tracks as seen (even failed ones)
    state.mark_seen(playlist_url, list(new_ids))
    state.save()


async def poll_loop(slsk: SoulseekDownloader, state: StateManager) -> None:
    """Main polling loop: discover all playlists, check each for new tracks."""
    # Initial sync: discover all existing playlists and mark their tracks as seen
    existing_playlists = discover_user_playlists(
        f"{SOUNDCLOUD_USER_URL}/sets" if SOUNDCLOUD_USER_URL else None
    )

    for playlist in existing_playlists:
        tracks = fetch_playlist_tracks(playlist.url)
        playlist.tracks = tracks
        state.set_playlist_name(playlist.url, playlist.title)
        state.mark_seen(playlist.url, [t.track_id for t in tracks])
        # Create smart crate for each existing playlist
        ensure_smart_crate(playlist.title)
    state.save()

    total_tracks = sum(len(p.tracks) for p in existing_playlists)
    logger.info(
        "Initial sync: %d playlists, %d tracks already known",
        len(existing_playlists),
        total_tracks,
    )
    send_notification("StreamFLACr", f"Watching {len(existing_playlists)} playlists")

    known_playlist_urls = {p.url for p in existing_playlists}

    while True:
        await asyncio.sleep(SOUNDCLOUD_POLL_INTERVAL)

        try:
            # Re-discover playlists to catch newly created ones
            current_playlists = discover_user_playlists(
                f"{SOUNDCLOUD_USER_URL}/sets" if SOUNDCLOUD_USER_URL else None
            )
        except Exception as e:
            logger.error("Error discovering playlists: %s", e)
            continue

        # Check for newly created playlists
        for playlist in current_playlists:
            if playlist.url not in known_playlist_urls:
                logger.info("New playlist detected: '%s'", playlist.title)
                state.set_playlist_name(playlist.url, playlist.title)
                ensure_smart_crate(playlist.title)
                known_playlist_urls.add(playlist.url)

        # Sync each playlist
        for playlist in current_playlists:
            try:
                await sync_playlist(playlist, slsk, state)
            except Exception as e:
                logger.error("Error syncing playlist '%s': %s", playlist.title, e)


async def run_once(slsk: SoulseekDownloader, state: StateManager) -> None:
    """Single-pass mode: check all playlists for new tracks, then exit."""
    playlists = discover_user_playlists(
        f"{SOUNDCLOUD_USER_URL}/sets" if SOUNDCLOUD_USER_URL else None
    )

    for playlist in playlists:
        try:
            await sync_playlist(playlist, slsk, state)
        except Exception as e:
            logger.error("Error syncing playlist '%s': %s", playlist.title, e)


async def amain(daemon: bool = False) -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    state = StateManager()
    slsk = SoulseekDownloader()

    try:
        await slsk.connect()

        if daemon:
            await poll_loop(slsk, state)
        else:
            await run_once(slsk, state)
    finally:
        await slsk.disconnect()


if __name__ == "__main__":
    from .cli import main
    main()
