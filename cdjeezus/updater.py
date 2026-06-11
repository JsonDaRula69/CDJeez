"""Self-update mechanism for CDJeezus.

Stops the daemon, upgrades the package via pip/uv, preserves config and
state, then restarts. Also handles data migrations between versions.

When any code change modifies the format of state.json, config, or
other operational data, a migration step must be added here.
"""

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from .config import CONFIG_DIR, STATE_FILE
from .setup import kill_running_daemon, register_launchdaemon, INSTALLED_PLIST, ENV_FILE
from .daemon import request_stop
from .style import (
    success, warning, error, info, separator, box, box_bottom, box_line,
    step_header, c, BRIGHT_CYAN, BRIGHT_AMBER,
)

logger = logging.getLogger(__name__)

CURRENT_STATE_VERSION = 5  # Increment when state.json schema changes


def _get_installed_version() -> str:
    """Get the currently installed version."""
    from . import __version__
    return __version__


def _get_latest_version() -> str | None:
    """Check PyPI for the latest released version."""
    try:
        import urllib.request
        url = "https://pypi.org/pypi/cdjeezus/json"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            return data["info"]["version"]
    except Exception as e:
        logger.error("Could not check PyPI for updates: %s", e)
        return None


def _migrate_state(state: dict) -> dict:
    """Migrate state.json to the current schema.

    v1 (pre-0.20.0): No version field, downloaded entries lack label_name.
    v2 (0.20.0+): Has version field, downloaded entries may have label_name.
    v3 (0.24.0+): Adds serato_blocked_transfer flag.
    v4 (0.25.0+): Adds verification fields (verified, verification_method, verification_confidence).
    v5 (0.26.0+): Adds library_fingerprinted and upscale_prompted flags.
    """
    version = state.get("version", 1)

    if version < 2:
        for url, playlist in state.get("playlists", {}).items():
            for tid, info in playlist.get("downloaded", {}).items():
                info.setdefault("local_path", "")
                info.setdefault("downloaded_at", "")
        logger.info("Migrated state from v1 to v2")

    if version < 3:
        state.setdefault("serato_blocked_transfer", False)
        logger.info("Migrated state from v2 to v3")

    if version < 4:
        for url, playlist in state.get("playlists", {}).items():
            for tid, info in playlist.get("downloaded", {}).items():
                info.setdefault("verified", None)
                info.setdefault("verification_method", "")
                info.setdefault("verification_confidence", 0.0)
        logger.info("Migrated state from v3 to v4")

    if version < 5:
        state.setdefault("library_fingerprinted", False)
        state.setdefault("upscale_prompted", False)
        logger.info("Migrated state from v4 to v5")

    state["version"] = CURRENT_STATE_VERSION
    return state


def _migrate_env() -> None:
    """Migrate .env config file: add missing keys with defaults."""
    if not ENV_FILE.exists():
        return

    defaults = {
        "PRIMARY_DJ": "serato",
        "TWO_WAY_SYNC": "0",
        "SOUNDCLOUD_POLL_INTERVAL": "300",
        "SEARCH_TIMEOUT": "30",
        "PREFER_FREE_SLOTS": "1",
        "MIN_FILESIZE_MB": "5",
        "SERATO_CHECK_INTERVAL": "30",
        "FINGERPRINT_VERIFY": "1",
        "UPSCALE_ENABLED": "0",
        "AUTO_UPDATE_INTERVAL": "14400",
    }

    try:
        lines = ENV_FILE.read_text().splitlines()
        existing_keys = set()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                existing_keys.add(key)
            new_lines.append(line)

        for key, default in defaults.items():
            if key not in existing_keys:
                new_lines.append(f"{key}={default}")

        ENV_FILE.write_text("\n".join(new_lines) + "\n")
        logger.info("Migrated .env config (added %d missing keys)",
                     len(set(defaults.keys()) - existing_keys))
    except Exception as e:
        logger.warning("Could not migrate .env: %s", e)


def _backup_config() -> Path:
    """Back up config directory before update."""
    backup_dir = CONFIG_DIR / "backups" / f"pre-update-{_get_installed_version()}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    for f in (ENV_FILE, STATE_FILE):
        if f.exists():
            shutil.copy2(f, backup_dir / f.name)

    logger.info("Config backed up to %s", backup_dir)
    return backup_dir


def auto_update_if_available() -> None:
    """Check PyPI for new version. If found, flag for update and shut down.

    Called from the daemon poll loop. Writes an `auto-update-pending` flag
    and triggers graceful shutdown. The LaunchAgent relaunches the daemon,
    which then runs `perform_pending_update()`.
    """
    latest = _get_latest_version()
    if latest is None:
        return

    current = _get_installed_version()
    if latest != current:
        logger.info("New version available: v%s (current: v%s)", latest, current)
        flag = CONFIG_DIR / "auto-update-pending"
        flag.write_text(latest)
        logger.info("Auto-update flagged. Daemon will update on next launch.")


def perform_pending_update() -> bool:
    """If an auto-update is pending, perform it now.

    Returns True if an update was performed (caller should restart).
    Called at daemon startup before the main loop begins.
    """
    flag = CONFIG_DIR / "auto-update-pending"
    if not flag.exists():
        return False

    target_version = flag.read_text().strip()
    flag.unlink(missing_ok=True)
    logger.info("Performing pending auto-update to v%s", target_version)

    current = _get_installed_version()
    print(f"  {step_header(0, 6, f'Auto-updating v{current} -> v{target_version}...')}")

    # Back up
    backup_dir = _backup_config()
    print(success(f"Config backed up"))

    # Upgrade
    try:
        result = subprocess.run(
            ["uv", "tool", "install", "cdjeezus", "--force", "--reinstall"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "cdjeezus"],
                capture_output=True, text=True, timeout=120,
            )
        if result.returncode != 0:
            logger.error("Auto-update failed: %s", result.stderr or result.stdout)
            # Restore from backup
            for f in (ENV_FILE, STATE_FILE):
                backup = backup_dir / f.name
                if backup.exists():
                    shutil.copy2(backup, f)
            return False
        print(success("Package upgraded"))
    except subprocess.TimeoutExpired:
        logger.error("Auto-update timed out")
        return False

    # Migrate
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
            state = _migrate_state(state)
            STATE_FILE.write_text(json.dumps(state, indent=2))
            print(success("State migrated"))
        except Exception as e:
            logger.warning("State migration failed: %s", e)

    try:
        _migrate_env()
        print(success("Config migrated"))
    except Exception as e:
        logger.warning("Config migration failed: %s", e)

    # Regenerate LaunchAgent
    try:
        register_launchdaemon()
        print(success("LaunchAgent regenerated"))
    except Exception as e:
        logger.warning("Could not regenerate LaunchAgent: %s", e)

    print(success(f"Updated to v{target_version}"))
    return True


def check_for_updates() -> str | None:
    """Check PyPI for the latest version. Returns the version string or None."""
    return _get_latest_version()


def run_update(check_only: bool = False) -> None:
    """Run the full update流程:
    1. Check PyPI for latest version
    2. Compare with current version
    3. Back up config and state
    4. Stop daemon gracefully
    5. Upgrade the package
    6. Migrate data if needed
    7. Restart daemon
    """
    current = _get_installed_version()
    latest = _get_latest_version()

    if latest is None:
        print()
        print(warning("Could not check for updates."))
        print(info(f"  Current version: v{current}"))
        print(info("  Make sure you have internet connectivity and try again."))
        print()
        sys.exit(1)

    print()
    print(box(f" CDJeezus Update ", width=46))
    print(box_line(f"Current: v{current}", width=46))
    print(box_line(f"Latest:    v{latest}", width=46))
    print(box_bottom(width=46))
    print()

    if current == latest:
        print(success("Already up to date!"))
        print(info("  Your CDJs are still overpriced though."))
        print()
        return

    if check_only:
        print(info(f"  Update available: v{current} -> v{latest}"))
        print(info("  Run 'cdjeezus update' to install."))
        print()
        return

    print(info(f"  Updating v{current} -> v{latest}..."))
    print()

    # Step 1: Back up config and state
    print(step_header(1, 6, "Backing up config..."))
    backup_dir = _backup_config()
    print(success(f"Config backed up to {backup_dir}"))

    # Step 2: Stop daemon gracefully
    print(step_header(2, 6, "Stopping daemon..."))
    stopped = request_stop(timeout=60)
    if stopped:
        print(success("Daemon stopped gracefully"))
    else:
        print(warning("Daemon did not respond, force-killing..."))
        kill_running_daemon()
        print(success("Daemon force-stopped"))

    # Step 3: Unload LaunchAgent
    print(step_header(3, 6, "Unloading LaunchAgent..."))
    for plist in (INSTALLED_PLIST,):
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True, check=False)
    print(success("LaunchAgent unloaded"))

    # Step 4: Upgrade package
    print(step_header(4, 6, "Upgrading package..."))
    try:
        result = subprocess.run(
            ["uv", "tool", "install", "cdjeezus", "--force", "--reinstall"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "cdjeezus"],
                capture_output=True, text=True, timeout=120,
            )
        if result.returncode != 0:
            print(error("Upgrade failed"))
            print(info(f"  {result.stderr or result.stdout}"))
            print(info("  Restoring from backup..."))
            for f in (ENV_FILE, STATE_FILE):
                backup = backup_dir / f.name
                if backup.exists():
                    shutil.copy2(backup, f)
            sys.exit(1)
        print(success("Package upgraded"))
    except subprocess.TimeoutExpired:
        print(error("Upgrade timed out"))
        print(info("  Restoring from backup..."))
        for f in (ENV_FILE, STATE_FILE):
            backup = backup_dir / f.name
            if backup.exists():
                shutil.copy2(backup, f)
        sys.exit(1)

    # Step 5: Migrate data
    print(step_header(5, 6, "Migrating data..."))
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
            state = _migrate_state(state)
            STATE_FILE.write_text(json.dumps(state, indent=2))
            print(success("State migrated"))
        except Exception as e:
            logger.warning("State migration failed: %s", e)
            backup_state = backup_dir / "state.json"
            if backup_state.exists():
                shutil.copy2(backup_state, STATE_FILE)
            print(warning("State migration had issues, restored from backup"))

    try:
        _migrate_env()
        print(success("Config migrated"))
    except Exception as e:
        logger.warning("Config migration failed: %s", e)
        print(warning("Config migration had issues (manual review recommended)"))

    # Step 6: Regenerate LaunchAgent plist and restart
    print(step_header(6, 6, "Restarting daemon..."))
    try:
        register_launchdaemon()
        print(success("LaunchAgent regenerated and loaded"))
    except Exception as e:
        logger.warning("Could not regenerate LaunchAgent: %s", e)
        if INSTALLED_PLIST.exists():
            subprocess.run(["launchctl", "load", str(INSTALLED_PLIST)], capture_output=True, check=False)
            print(success("LaunchAgent reloaded"))
        else:
            print(warning("Could not register LaunchAgent. Run 'cdjeezus setup' to fix."))

    new_version = _get_installed_version()
    print()
    print(box(f" Update Complete! ", width=46))
    print(box_line(f"v{current} -> v{new_version}", width=46))
    if new_version != latest:
        print(box_mid(width=46))
        print(box_line(f"Installed v{new_version} != PyPI v{latest}", width=46))
        print(box_line("You may need to run update again.", width=46))
    print(box_bottom(width=46))
    print()
