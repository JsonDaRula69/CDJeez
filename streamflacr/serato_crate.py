"""Serato smart crate management via serato-tools.

Creates a smart crate per SoundCloud playlist with a rule:
    Label IS <playlist_name>
so that all downloaded FLACs with that label tag auto-populate the crate.

Serato data is highly sensitive — we back up before any modification
and never delete existing crates or files.
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path

from .config import SERATO_DIR

logger = logging.getLogger(__name__)

BACKUP_DIR = Path("/Users/djtchill/Music/_Serato_Backup_SFr")
MAX_BACKUPS = 5


def _rotate_backups() -> None:
    """Keep only the most recent MAX_BACKUPS backup directories."""
    if not BACKUP_DIR.exists():
        return
    backups = sorted(
        [p for p in BACKUP_DIR.iterdir() if p.is_dir() and p.name.startswith("Bk")],
        key=lambda p: p.name,
    )
    while len(backups) > MAX_BACKUPS:
        oldest = backups.pop(0)
        shutil.rmtree(oldest)
        logger.debug("Removed old backup: %s", oldest.name)


def backup_serato_changes(*paths: Path) -> None:
    """Back up Serato files before modifying them.

    Creates a timestamped backup directory and copies the given files
    into it, preserving directory structure relative to SERATO_DIR.
    Only backs up files that actually exist.
    """
    existing = [p for p in paths if p.exists()]
    if not existing:
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dest = BACKUP_DIR / f"Bk{timestamp}"
    backup_dest.mkdir(parents=True, exist_ok=True)

    for path in existing:
        rel = path.relative_to(SERATO_DIR) if path.is_relative_to(SERATO_DIR) else path.name
        dest = backup_dest / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

    _rotate_backups()
    logger.info("Backed up %d file(s) to %s", len(existing), backup_dest.name)


def ensure_smart_crate(playlist_name: str) -> Path | None:
    """Create or update a Serato smart crate that matches on Label IS playlist_name.

    Backs up the file before any modification. Never deletes existing crates.
    Returns the path to the .scrate file.
    """
    from serato_tools.smart_crate import SmartCrate

    safe_name = playlist_name.replace("/", "≫").replace("\\", "≫")
    smart_crates_dir = SERATO_DIR / "SmartCrates"
    smart_crates_dir.mkdir(parents=True, exist_ok=True)
    scrate_path = smart_crates_dir / f"{safe_name}.scrate"

    if scrate_path.exists():
        # Back up before overwriting
        backup_serato_changes(scrate_path)
        logger.info("Smart crate already exists: %s", scrate_path.name)
        sc = SmartCrate(str(scrate_path))
        _ensure_label_rule(sc, playlist_name)
        sc.save()
        return scrate_path

    sc = SmartCrate(str(scrate_path))
    _ensure_label_rule(sc, playlist_name)

    # Enable live update so Serato refreshes automatically
    for i, (f, v) in enumerate(sc.entries):
        if f == SmartCrate.Fields.SMARTCRATE_LIVE_UPDATE:
            sc.entries[i] = (f, [("brut", True)])
        if f == SmartCrate.Fields.SMARTCRATE_MATCH_ALL:
            sc.entries[i] = (f, [("brut", True)])

    sc.save()
    logger.info("Created smart crate: %s (Label IS '%s')", scrate_path.name, playlist_name)
    return scrate_path


def _ensure_label_rule(sc, playlist_name: str) -> None:
    """Make sure the smart crate has a Label IS rule for the playlist name."""
    sc.set_rule(sc.RuleField.LABEL, sc.RuleComparison.STR_IS, playlist_name)
