# StreamFLACr

Automatically download FLAC versions of songs added to SoundCloud playlists via Soulseek, tag them with metadata, and create matching Serato smart crates.

## How it works

1. **Discovers** all your SoundCloud playlists automatically (including private ones)
2. **Monitors** for new tracks added to any playlist
3. **Detects** new playlists as they're created
4. **Searches** Soulseek for FLAC versions of each new track
5. **Downloads** the best candidate (prefers free slots, fast speeds, larger files)
6. **Tags** the FLAC with artist, title, and the playlist name as the **Label** field
7. **Creates** a Serato smart crate per playlist with rule: `Label IS <playlist_name>`
8. Files land in `~/Music/_Serato_/Auto Import` — Serato picks them up automatically

## Install

```bash
pipx install streamflacr
```

Or from source:

```bash
pipx install .
```

## Setup

```bash
streamflacr setup
```

The setup wizard will:

- **Detect SoundCloud login** in Chrome (auto-extracts OAuth token from cookies)
- **Auto-discover your profile URL** from the SoundCloud API
- **Detect SoulseekQt** installation and data
- **Prompt for credentials** when something is missing
- **Install Serato tools** (smart crate support)
- **Write configuration** to `.env`
- **Register a LaunchDaemon** so StreamFLACr starts on login

All existing and future playlists are monitored automatically — no need to specify them manually.

## Usage

Single pass (check once and exit):
```bash
streamflacr
```

Daemon mode (poll continuously):
```bash
streamflacr --daemon
```

Re-run setup:
```bash
streamflacr setup
```

Unregister LaunchDaemon:
```bash
streamflacr setup --uninstall
```

## Configuration

All config lives in `.env` in the project directory (created by `streamflacr setup`):

| Variable | Default | Description |
|---|---|---|
| `SLSK_USERNAME` | — | Soulseek username (required) |
| `SLSK_PASSWORD` | — | Soulseek password (required) |
| `SOUNDCLOUD_USER_URL` | auto | Your SoundCloud profile URL |
| `SOUNDCLOUD_POLL_INTERVAL` | `300` | Seconds between polls |
| `DOWNLOAD_DIR` | `~/Music/_Serato_/Auto Import` | Where FLACs land |
| `SERATO_DIR` | `~/Music/_Serato_` | Serato database directory |
| `SEARCH_TIMEOUT` | `30` | Seconds to wait for Soulseek results |
| `PREFER_FREE_SLOTS` | `1` | Prefer users with free upload slots |
| `MIN_FILESIZE_MB` | `5` | Skip files smaller than this |
