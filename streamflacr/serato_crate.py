"""Serato smart crate management via serato-tools.

Creates a smart crate per SoundCloud playlist with a rule:
    Label IS <playlist_name>
so that all downloaded FLACs with that label tag auto-populate the crate.
"""

import logging
from pathlib import Path

from .config import SERATO_DIR

logger = logging.getLogger(__name__)


def _import_serato_tools():
    """Lazy import serato-tools. Raises ImportError if not installed."""
    from serato_tools.smart_crate import SmartCrate  # noqa: F401
    return SmartCrate


def ensure_smart_crate(playlist_name: str) -> Path | None:
    """Create or update a Serato smart crate that matches on Label IS playlist_name.

    Returns the path to the .scrate file, or None if serato-tools is not installed.
    """
    try:
        SmartCrate = _import_serato_tools()
    except ImportError:
        logger.warning("serato-tools not installed; skipping smart crate creation")
        logger.warning("Install with: pip install serato-tools --no-deps")
        return None

    safe_name = playlist_name.replace("/", "≫").replace("\\", "≫")
    smart_crates_dir = SERATO_DIR / "SmartCrates"
    smart_crates_dir.mkdir(parents=True, exist_ok=True)
    scrate_path = smart_crates_dir / f"{safe_name}.scrate"

    if scrate_path.exists():
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
