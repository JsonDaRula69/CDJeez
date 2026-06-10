"""Configuration management via environment / .env file."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Soulseek credentials
SLSK_USERNAME: str = os.environ.get("SLSK_USERNAME", "")
SLSK_PASSWORD: str = os.environ.get("SLSK_PASSWORD", "")

# SoundCloud
SOUNDCLOUD_USER_URL: str = os.environ.get("SOUNDCLOUD_USER_URL", "")
SOUNDCLOUD_POLL_INTERVAL: int = int(os.environ.get("SOUNDCLOUD_POLL_INTERVAL", "300"))  # seconds

# Download destination
DOWNLOAD_DIR: Path = Path(os.environ.get("DOWNLOAD_DIR", "/Users/djtchill/Music/_Serato_/Auto Import"))

# Serato
SERATO_DIR: Path = Path(os.environ.get("SERATO_DIR", "/Users/djtchill/Music/_Serato_"))

# State file (tracks last-seen set to avoid re-downloading)
STATE_FILE: Path = Path(os.environ.get("STATE_FILE", str(Path(__file__).parent.parent / "state.json")))

# Search preferences
SEARCH_TIMEOUT: int = int(os.environ.get("SEARCH_TIMEOUT", "30"))
PREFER_FREE_SLOTS: bool = os.environ.get("PREFER_FREE_SLOTS", "1") == "1"
MIN_FILESIZE_MB: int = int(os.environ.get("MIN_FILESIZE_MB", "5"))
