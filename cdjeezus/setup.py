"""Interactive setup wizard for CDJeezus.

Because paying $2000 for a deck without Stems is a lifestyle choice,
and we're here to make it slightly less painful.

Detects DJ software, SoundCloud login, and Soulseek installation,
configures playlist monitoring and library backups, writes .env,
and registers the launchd daemon.
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import (
    CONFIG_DIR, DOWNLOAD_DIR, SERATO_DIR, REKORDBOX_DIR,
    STAGING_DIR, BACKUP_DIR, PID_FILE, STOP_FILE, LOG_FILE,
)
from .style import (
    c, dim, bold, italic, success, warning, error, info, accent,
    header, separator, box, box_bottom, box_mid, box_line, kv_line,
    step_header, format_kv_box, countdown,
    MENU_CURSOR, MULTI_SELECT_ON, MULTI_SELECT_OFF,
    MENU_CURSOR_STYLE, MENU_HIGHLIGHT_STYLE,
    MULTI_SELECT_CURSOR_STYLE, MULTI_SELECT_BRACKETS_STYLE,
    SEARCH_HIGHLIGHT_STYLE, STATUS_BAR_STYLE,
    MULTI_SELECT_HINT, SEARCH_HINT,
    CYAN, BRIGHT_CYAN, BRIGHT_AMBER, BRIGHT_RED, BRIGHT_GREEN,
    DIM_WHITE, RST,
)

logger = logging.getLogger(__name__)

ENV_FILE = CONFIG_DIR / ".env"
INSTALLED_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.cdjeezus.plist"
LEGACY_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.djtchill.cdjeezus.plist"
# Old StreamFLACr plists from before the rename
STREAMFLACR_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.streamflacr.plist"
STREAMFLACR_LEGACY_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.djtchill.streamflacr.plist"


def kill_running_daemon() -> bool:
    """Kill any stale cdjeezus daemon from a previous run."""
    import signal
    for plist in (INSTALLED_PLIST, LEGACY_PLIST, STREAMFLACR_PLIST, STREAMFLACR_LEGACY_PLIST):
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True, check=False)

    my_pid = os.getpid()
    parent_pid = os.getppid()
    killed = False
    try:
        result = subprocess.run(
            ["pgrep", "-f", "python.*(cdjeezus|streamflacr)"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for pid_str in result.stdout.strip().split("\n"):
                try:
                    pid = int(pid_str.strip())
                    if pid in (my_pid, parent_pid):
                        continue
                    os.kill(pid, signal.SIGTERM)
                    killed = True
                except (ValueError, ProcessLookupError, PermissionError):
                    pass
    except Exception:
        pass
    if killed:
        import time
        time.sleep(1)
    return killed


# ── DJ Software Detection ────────────────────────────────────────────

def detect_serato() -> bool:
    return SERATO_DIR.exists()


def detect_rekordbox() -> bool:
    return REKORDBOX_DIR.exists() and (REKORDBOX_DIR / "master.db").exists()


def detect_fpcalc() -> bool:
    try:
        result = subprocess.run(["fpcalc", "-version"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def detect_soulseek_installation() -> bool:
    for path in [Path("/Applications/SoulseekQt.app"), Path.home() / "Applications" / "SoulseekQt.app"]:
        if path.exists():
            return True
    return False


def detect_soulseek_data() -> bool:
    data_dir = Path.home() / ".SoulseekQt"
    return data_dir.exists() and any(data_dir.iterdir())


# ── SoundCloud Detection ──────────────────────────────────────────────

def detect_soundcloud_login() -> bool:
    from .soundcloud import has_oauth
    return has_oauth()


def extract_soundcloud_user_url() -> str | None:
    from .soundcloud import _api_get
    try:
        me = _api_get("me")
        if me:
            return me.get("permalink_url")
    except Exception as e:
        logger.debug("Could not get SoundCloud user URL: %s", e)
    return None


def prompt_soundcloud_login() -> None:
    print()
    print(warning("SoundCloud login not detected in Chrome."))
    print(info("  Opening SoundCloud login page in your browser..."))
    subprocess.run(["open", "https://soundcloud.com/signin"], check=False)
    input(dim("  Press Enter once you've logged into SoundCloud in Chrome... "))


# ── TUI Helpers ───────────────────────────────────────────────────────

def _menu_select(options: list[str], title: str = "", status_bar: str | None = None) -> int:
    """Single-select menu using arrow keys and Enter. CDJeezus-themed."""
    from simple_term_menu import TerminalMenu
    kwargs = dict(
        menu_entries=options,
        title=title,
        menu_cursor=MENU_CURSOR,
        menu_cursor_style=MENU_CURSOR_STYLE,
        menu_highlight_style=MENU_HIGHLIGHT_STYLE,
        search_highlight_style=SEARCH_HIGHLIGHT_STYLE,
        status_bar_style=STATUS_BAR_STYLE,
        show_search_hint=True,
        show_search_hint_text=SEARCH_HINT,
    )
    if status_bar:
        kwargs["status_bar"] = status_bar
    menu = TerminalMenu(**kwargs)
    return menu.show()


def _multi_select(options: list[str], title: str = "", status_bar: str | None = None) -> list[int]:
    """Multi-select menu using arrow keys, spacebar, and Enter. CDJeezus-themed."""
    from simple_term_menu import TerminalMenu
    kwargs = dict(
        menu_entries=options,
        title=title,
        multi_select=True,
        multi_select_cursor=f"{MULTI_SELECT_ON} ",
        multi_select_cursor_brackets_style=MULTI_SELECT_BRACKETS_STYLE,
        multi_select_cursor_style=MULTI_SELECT_CURSOR_STYLE,
        menu_cursor=MENU_CURSOR,
        menu_cursor_style=MENU_CURSOR_STYLE,
        menu_highlight_style=MENU_HIGHLIGHT_STYLE,
        search_highlight_style=SEARCH_HIGHLIGHT_STYLE,
        status_bar_style=STATUS_BAR_STYLE,
        show_multi_select_hint=True,
        show_multi_select_hint_text=MULTI_SELECT_HINT,
        show_search_hint=True,
        show_search_hint_text=SEARCH_HINT,
    )
    if status_bar:
        kwargs["status_bar"] = status_bar
    menu = TerminalMenu(**kwargs)
    result = menu.show()
    if result is None:
        return []
    return result if isinstance(result, list) else [result]


# ── Soulseek Prompt ─────────────────────────────────────────────────

def prompt_soulseek_setup() -> dict[str, str]:
    """Prompt for Soulseek credentials. You need an account. Yes, really."""
    print()
    print(info("  Soulseek credentials required. Yes, you need an account."))
    print(info("  If you don't have one, visit https://www.slsknet.org"))
    print()
    username = input(f"  {c(BRIGHT_CYAN, 'Soulseek username')}: ").strip()
    password = input(f"  {c(BRIGHT_CYAN, 'Soulseek password')}: ").strip()
    return {"username": username, "password": password}


# ── LaunchAgent Management ───────────────────────────────────────────

def register_launchdaemon() -> None:
    """Register the CDJeezus LaunchAgent for auto-start on login."""
    python = sys.executable
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cdjeezus</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>cdjeezus</string>
        <string>--daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_FILE}</string>
</dict>
</plist>
"""
    INSTALLED_PLIST.parent.mkdir(parents=True, exist_ok=True)
    INSTALLED_PLIST.write_text(plist_content)
    subprocess.run(["launchctl", "load", str(INSTALLED_PLIST)], capture_output=True, check=False)


# ── Env File Writer ───────────────────────────────────────────────────

def write_env_file(config: dict) -> None:
    """Write the .env config file from the setup wizard results."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    primary = config.get("primary_dj", "serato")
    download_dir = str(DOWNLOAD_DIR) if primary == "serato" else str(
        Path.home() / "Music" / "rekordbox_auto_import"
    )
    env_content = f"""# CDJeezus configuration — generated by setup wizard
# Edit at your own risk. Or don't. I'm a config file, not a cop.

SLSK_USERNAME={config.get("slsk_username", "")}
SLSK_PASSWORD={config.get("slsk_password", "")}
SOUNDCLOUD_USER_URL={config.get("user_url", "")}
PRIMARY_DJ={primary}
TWO_WAY_SYNC={"1" if config.get("two_way_sync") else "0"}
DOWNLOAD_DIR={download_dir}
PLAYLIST_MODE={config.get("playlist_mode", "all")}
MONITORED_PLAYLISTS={",".join(config.get("monitored_playlists", []))}
BACKUP_ENABLED={"1" if config.get("backup_enabled") else "0"}
BACKUP_SERATO={"1" if config.get("backup_serato") else "0"}
BACKUP_REKORDBOX={"1" if config.get("backup_rekordbox") else "0"}
ACOUSTID_API_KEY={config.get("acoustid_api_key", "")}
FINGERPRINT_VERIFY={"1" if config.get("fingerprint_verify", True) else "0"}
UPSCALE_ENABLED={"1" if config.get("upscale_enabled", False) else "0"}
AUTO_UPDATE_INTERVAL=14400
SOUNDCLOUD_POLL_INTERVAL=300
SEARCH_TIMEOUT=30
SERATO_CHECK_INTERVAL=30
"""
    ENV_FILE.write_text(env_content)


# ── Uninstall ─────────────────────────────────────────────────────────

def full_uninstall() -> None:
    """Remove all CDJeezus artifacts. Music files, libraries, and backups stay."""
    from . import __version__

    print()
    print(box(f" CDJeezus v{__version__} — Uninstall ", width=46))
    print(box_line("Time to cleanse the temple.", width=46))
    print(box_bottom(width=46))
    print()

    # Stop daemon
    from .daemon import request_stop, is_running
    if is_running():
        print(info("  Stopping daemon..."))
        stopped = request_stop(timeout=60)
        if stopped:
            print(success("Daemon stopped gracefully"))
        else:
            kill_running_daemon()
            print(success("Daemon force-stopped"))

    # Remove LaunchAgent plists
    removed_plist = False
    for plist in (INSTALLED_PLIST, LEGACY_PLIST, STREAMFLACR_PLIST, STREAMFLACR_LEGACY_PLIST):
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True, check=False)
            plist.unlink()
            removed_plist = True
    if removed_plist:
        print(success("LaunchAgent removed"))
    else:
        print(info("  No LaunchAgent found"))

    # Remove legacy plist
    if LEGACY_PLIST.exists():
        subprocess.run(["launchctl", "unload", str(LEGACY_PLIST)], capture_output=True, check=False)
        LEGACY_PLIST.unlink()
        print(success("Legacy LaunchAgent removed"))

    # Remove config and staging
    if CONFIG_DIR.exists():
        shutil.rmtree(CONFIG_DIR, ignore_errors=True)
        print(success("Config and staging removed"))
    else:
        print(info("  No config directory found"))

    # Remove PID/log files if they exist outside config_dir
    for f in (PID_FILE, LOG_FILE):
        if f.exists() and not str(f).startswith(str(CONFIG_DIR)):
            f.unlink(missing_ok=True)

    print()
    print(separator(width=46))
    print(info("  Music files, DJ libraries, and backups were NOT modified."))
    print(info("  As it should be. We're not monsters."))
    print(separator(width=46))
    print()


# ── Setup Wizard ──────────────────────────────────────────────────────

def run_setup(*, non_interactive: bool = False) -> None:
    """Run the interactive setup wizard. 8 steps to DJ salvation."""
    from . import __version__

    config: dict = {}

    print()
    print(box(" CDJeezus Setup Wizard ", width=46))
    print(box_line(f"v{__version__} — 8 steps to DJ salvation", width=46))
    print(box_bottom(width=46))
    print()

    # Migrate from StreamFLACr if needed
    if _OLD_STREAMFLACR_CONFIG.exists() and not CONFIG_DIR.exists():
        print(info("  Migrating config from StreamFLACr to CDJeezus..."))
        try:
            _OLD_STREAMFLACR_CONFIG.rename(CONFIG_DIR)
            print(success("Migrated config from StreamFLACr to CDJeezus"))
        except Exception as e:
            logger.warning("Could not auto-migrate: %s", e)
        print()

    # ── Step 1: Primary DJ ──
    serato_found = detect_serato()
    rekordbox_found = detect_rekordbox()
    print(step_header(1, 8, "Choosing your religion..."))

    if serato_found and rekordbox_found:
        print(info("  Both detected. Pick your primary (the one you actually mix on):"))
        if not non_interactive:
            choice = _menu_select(
                ["Serato DJ", "Rekordbox"],
                title="  Which one do you suffer with most?",
                status_bar="arrow keys + enter — no judgment",
            )
            config["primary_dj"] = "serato" if choice == 0 else "rekordbox"
        else:
            config["primary_dj"] = "serato"
    elif serato_found:
        print(success("Serato DJ auto-detected"))
        config["primary_dj"] = "serato"
    elif rekordbox_found:
        print(success("Rekordbox auto-detected"))
        config["primary_dj"] = "rekordbox"
    else:
        print(warning("No DJ software detected"))
        print(info("  CDJs and laptops don't count. Install Serato or Rekordbox first."))
        if not non_interactive:
            choice = _menu_select(
                ["Serato DJ", "Rekordbox"],
                title="  Which are you installing?",
            )
            config["primary_dj"] = "serato" if choice == 0 else "rekordbox"
        else:
            config["primary_dj"] = "serato"
    print()

    # ── Step 2: Secondary DJ / 2-way sync ──
    print(step_header(2, 8, "Checking for the other cult..."))
    secondary = "rekordbox" if config["primary_dj"] == "serato" else "serato"
    secondary_found = detect_rekordbox() if config["primary_dj"] == "serato" else detect_serato()

    if secondary_found:
        print(success(f"{secondary.title()} detected!"))
        if not non_interactive:
            answer = input(
                f"  {c(BRIGHT_CYAN, f'Enable 2-way sync with {secondary.title()}?')} [y/N]: "
            ).strip().lower()
            config["two_way_sync"] = answer in ("y", "yes")
        else:
            config["two_way_sync"] = False

        if config["two_way_sync"]:
            print(success(f"2-way sync with {secondary.title()} enabled"))
        else:
            print(info("  2-way sync disabled. More crates, more problems."))
    else:
        print(warning(f"{secondary.title()} not detected!"))
        print(info("  Library sync disabled. Different club, same cult."))
        print(info("  Press Enter to keep going."))
        config["two_way_sync"] = False
        if not non_interactive:
            input()
    print()

    # ── Step 3: Soulseek ──
    print(step_header(3, 8, "Soulseek setup..."))
    if detect_soulseek_installation():
        print(success("SoulseekQt.app found"))
    else:
        print(warning("SoulseekQt.app not found"))
        print(info("  It's recommended but not required. The built-in client works too."))
        if not non_interactive:
            answer = input("  Install SoulseekQt? [y/N]: ").strip().lower()
            if answer == "y":
                print(info("  Downloading from slsknet.org..."))
                try:
                    subprocess.run(
                        ["open", "https://www.slsknet.org/download"],
                        check=False,
                    )
                except Exception:
                    pass
                input("  Press Enter once you've installed it... ")

    if detect_soulseek_data():
        print(success("SoulseekQt data found (you've logged in before)"))
    else:
        print(info("  No Soulseek data found"))

    slsk_creds = prompt_soulseek_setup()
    config["slsk_username"] = slsk_creds["username"]
    config["slsk_password"] = slsk_creds["password"]
    print()

    # ── Step 4: AcoustID ──
    print(step_header(4, 8, "Audio fingerprinting..."))
    fpcalc_available = detect_fpcalc()
    if fpcalc_available:
        print(success("fpcalc (chromaprint) found — audio fingerprinting enabled"))
    else:
        print(warning("fpcalc not found"))
        print(info("  Run `brew install chromaprint` unless you enjoy guessing"))
    if not non_interactive:
        acoustid_key = input(
            f"  {c(BRIGHT_CYAN, 'AcoustID API key')} {dim('(press Enter to skip)')}: "
        ).strip()
        if acoustid_key:
            config["acoustid_api_key"] = acoustid_key
            config["fingerprint_verify"] = True
        else:
            config["acoustid_api_key"] = ""
            config["fingerprint_verify"] = fpcalc_available
    else:
        config["acoustid_api_key"] = ""
        config["fingerprint_verify"] = fpcalc_available
    print()

    # ── Step 5: SoundCloud ──
    print(step_header(5, 8, "SoundCloud connection..."))
    if detect_soundcloud_login():
        user_url = extract_soundcloud_user_url()
        if user_url:
            print(success(f"SoundCloud login detected in Chrome"))
            print(info(f"  Profile: {user_url}"))
            config["user_url"] = user_url
        else:
            print(warning("Could not extract SoundCloud profile from Chrome"))
            if not non_interactive:
                config["user_url"] = input(
                    f"  {c(BRIGHT_CYAN, 'SoundCloud profile URL')}: "
                ).strip()
            else:
                config["user_url"] = ""
    else:
        if not non_interactive:
            prompt_soundcloud_login()
            user_url = extract_soundcloud_user_url()
            if not user_url:
                user_url = input(
                    f"  {c(BRIGHT_CYAN, 'SoundCloud profile URL')}: "
                ).strip()
            config["user_url"] = user_url
        else:
            config["user_url"] = ""
    print()

    # ── Step 6: Playlists ──
    print(step_header(6, 8, "Playlist selection..."))
    if not non_interactive:
        choice = _menu_select(
            ["All playlists", "Custom selection"],
            title="  All playlists or just the ones you actually use?",
            status_bar="the more you select, the longer this takes",
        )
        if choice == 0:
            config["playlist_mode"] = "all"
            config["monitored_playlists"] = []
            print(success("All playlists will be monitored"))
        else:
            from .soundcloud import discover_user_playlists
            playlists = discover_user_playlists()
            if playlists:
                playlist_names = [p.title for p in playlists]
                selected = _multi_select(
                    playlist_names,
                    title="  Select playlists to monitor:",
                    status_bar="space to toggle, enter to confirm",
                )
                config["playlist_mode"] = "custom"
                config["monitored_playlists"] = [playlists[i].url for i in selected]
                print(success(f"{len(selected)} playlist(s) selected"))
            else:
                print(warning("No playlists found"))
                config["playlist_mode"] = "all"
                config["monitored_playlists"] = []
    else:
        config["playlist_mode"] = "all"
        config["monitored_playlists"] = []
        print(info("  Monitoring all playlists (non-interactive mode)"))
    print()

    # ── Step 7: Backups ──
    print(step_header(7, 8, "Library backups..."))
    if not non_interactive:
        answer = input(
            f"  {c(BRIGHT_CYAN, 'Enable library backups?')} [y/N]: "
        ).strip().lower()
        config["backup_enabled"] = answer in ("y", "yes")
    else:
        config["backup_enabled"] = False

    if config["backup_enabled"]:
        backup_options = []
        if detect_serato():
            backup_options.append("Serato")
        if detect_rekordbox():
            backup_options.append("Rekordbox")

        if backup_options and not non_interactive:
            selected = _multi_select(
                backup_options,
                title="  Which libraries to back up?",
                status_bar="your crates are precious. back them up.",
            )
            config["backup_serato"] = "Serato" in [backup_options[i] for i in selected]
            config["backup_rekordbox"] = "Rekordbox" in [backup_options[i] for i in selected]
        else:
            config["backup_serato"] = detect_serato()
            config["backup_rekordbox"] = detect_rekordbox()

        print(success(f"Backups enabled"))
    else:
        config["backup_serato"] = False
        config["backup_rekordbox"] = False
        config["backup_dir"] = str(BACKUP_DIR)
        print(info("  Backups disabled. Live dangerously, I guess."))
    print()

    # ── Step 8: Config Summary & Confirm ──
    while True:
        print(step_header(8, 8, "Here's what you're signing up for:"))
        print()

        summary_pairs = [
            ("Primary DJ", config.get("primary_dj", "serato").title()),
            ("2-way sync", "Yes" if config.get("two_way_sync") else "No"),
            ("Soulseek", config.get("slsk_username", "")),
            ("AcoustID", "Yes" if config.get("acoustid_api_key") else "No"),
            ("SoundCloud", config.get("user_url", "")),
            ("Playlists", config.get("playlist_mode", "all").title()),
            ("Backups", "Yes" if config.get("backup_enabled") else "No"),
        ]
        print(format_kv_box(" Config Summary ", summary_pairs, width=46))
        print()

        if not non_interactive:
            answer = input(
                f"  {c(BRIGHT_AMBER, 'Look good?')} [Y/n]: "
            ).strip().lower()
            if answer in ("", "y", "yes"):
                break

            edit_options = [
                "Primary DJ",
                "2-way sync",
                "Soulseek",
                "SoundCloud",
                "Playlist selection",
                "Library backups",
                "Never mind, let's just go",
            ]
            choice = _menu_select(
                edit_options,
                title="  Which config to edit?",
                status_bar="we all make mistakes. fix yours here.",
            )
            if choice == 6:
                break
            _edit_config_step(choice, config)
            # Re-render summary
            print()
        else:
            break

    # ── Disclaimer ──
    print()
    print(box(" Legal Disclaimer (yeah, I know) ", width=46))
    print(box_line("Alright, real talk: you're only supposed to", width=46))
    print(box_line("use this for music you have rights to, on a", width=46))
    print(box_line("private SoulSeek server that also belongs to", width=46))
    print(box_line("you. This is for backup and syncing only.", width=46))
    print(box_mid(width=46))
    print(box_line("Also SoundCloud might get pissy if you don't", width=46))
    print(box_line("have Artist Pro, so use at your own risk.", width=46))
    print(box_line("I worked around it but idk ask Naveen to", width=46))
    print(box_line("do better.", width=46))
    print(box_bottom(width=46))
    print()

    if not non_interactive:
        disclaimer_choice = _menu_select(
            ["Agreed", "Wait, what?"],
            title="  Last chance to back out:",
            status_bar="no really, read it",
        )
        if disclaimer_choice == 1:
            print()
            print(box("", width=46))
            print(box_line("lol. fuck off. Closing this window will", width=46))
            print(box_line("uninstall automatically. Or press Enter to", width=46))
            print(box_line("stay and accept your fate.", width=46))
            print(box_bottom(width=46))
            input()
    print()

    # ── Write config ──
    write_env_file(config)
    print(info(f"  Config written to {ENV_FILE}"))

    primary = config.get("primary_dj", "serato")
    download_dir = str(DOWNLOAD_DIR) if primary == "serato" else str(
        Path.home() / "Music" / "rekordbox_auto_import"
    )
    print(success(f"Download directory: {download_dir}"))
    print(success(f"Staging directory: {STAGING_DIR}"))

    # Run initial backup if enabled
    if config.get("backup_enabled"):
        from .backup import run_backups
        results = run_backups(
            backup_serato=config.get("backup_serato", False),
            backup_rekordbox=config.get("backup_rekordbox", False),
        )
        if results:
            print(success(f"Initial backup created ({len(results)} archive(s))"))

    # Register daemon
    if not non_interactive:
        answer = input(
            f"  {c(BRIGHT_CYAN, 'Start CDJeezus automatically on login?')} [Y/n]: "
        ).strip().lower()
        if answer in ("", "y", "yes"):
            register_launchdaemon()
            print(success("LaunchDaemon registered"))
        else:
            print(info("  Skipping daemon. Run `cdjeezus --daemon` to start manually."))
    else:
        register_launchdaemon()

    print()
    print(box(" Setup Complete! ", width=46))
    print(box_line("Deploying the daemon in 3...", width=46))
    print(box_bottom(width=46))

    import time
    time.sleep(3)
    print()


def _edit_config_step(step: int, config: dict) -> None:
    """Re-run a specific setup step to edit config."""
    if step == 0:  # Primary DJ
        serato_found = detect_serato()
        rekordbox_found = detect_rekordbox()
        options = []
        if serato_found:
            options.append("Serato DJ (detected)")
        else:
            options.append("Serato DJ (not found)")
        if rekordbox_found:
            options.append("Rekordbox (detected)")
        else:
            options.append("Rekordbox (not found)")
        choice = _menu_select(
            options,
            title="  Select your primary DJ software:",
            status_bar="the one you actually mix on",
        )
        config["primary_dj"] = "serato" if choice == 0 else "rekordbox"
    elif step == 1:  # 2-way sync
        secondary = "rekordbox" if config["primary_dj"] == "serato" else "serato"
        answer = input(
            f"  {c(BRIGHT_CYAN, f'Enable 2-way sync with {secondary.title()}?')} [y/N]: "
        ).strip().lower()
        config["two_way_sync"] = answer in ("y", "yes")
    elif step == 2:  # Soulseek
        slsk_creds = prompt_soulseek_setup()
        config["slsk_username"] = slsk_creds["username"]
        config["slsk_password"] = slsk_creds["password"]
    elif step == 3:  # AcoustID
        fpcalc_available = detect_fpcalc()
        if fpcalc_available:
            print(success("fpcalc (chromaprint) is installed"))
        else:
            print(warning("fpcalc not found"))
            print(info("  Run `brew install chromaprint` unless you enjoy guessing"))
        acoustid_key = input(
            f"  {c(BRIGHT_CYAN, 'AcoustID API key')} {dim('(press Enter to skip)')}: "
        ).strip()
        config["acoustid_api_key"] = acoustid_key
    elif step == 4:  # SoundCloud
        if not detect_soundcloud_login():
            prompt_soundcloud_login()
        user_url = extract_soundcloud_user_url()
        if not user_url:
            user_url = input(
                f"  {c(BRIGHT_CYAN, 'SoundCloud profile URL')}: "
            ).strip()
        config["user_url"] = user_url
    elif step == 5:  # Playlists
        choice = _menu_select(
            ["All playlists", "Custom selection"],
            title="  All playlists or just the ones you actually use?",
            status_bar="the more you select, the longer this takes",
        )
        if choice == 0:
            config["playlist_mode"] = "all"
            config["monitored_playlists"] = []
        else:
            from .soundcloud import discover_user_playlists
            playlists = discover_user_playlists()
            if playlists:
                playlist_names = [p.title for p in playlists]
                selected = _multi_select(
                    playlist_names,
                    title="  Select playlists:",
                    status_bar="space to toggle, enter to confirm",
                )
                config["playlist_mode"] = "custom"
                config["monitored_playlists"] = [playlists[i].url for i in selected]
    elif step == 6:  # Backups
        answer = input(
            f"  {c(BRIGHT_CYAN, 'Enable library backups?')} [y/N]: "
        ).strip().lower()
        config["backup_enabled"] = answer in ("y", "yes")
        if config["backup_enabled"]:
            backup_options = []
            if detect_serato():
                backup_options.append("Serato")
            if detect_rekordbox():
                backup_options.append("Rekordbox")
            if backup_options:
                selected = _multi_select(
                    backup_options,
                    title="  Which libraries to back up?",
                    status_bar="your crates are precious. back them up.",
                )
                config["backup_serato"] = "Serato" in [backup_options[i] for i in selected]
                config["backup_rekordbox"] = "Rekordbox" in [backup_options[i] for i in selected]


def _launch_soundcloud_app() -> None:
    """Launch SoundCloud PWA app to refresh OAuth token."""
    sc_app = Path.home() / "Applications" / "Chrome Apps.localized" / "SoundCloud.app"
    if sc_app.exists():
        subprocess.run(["open", str(sc_app)], check=False)
    else:
        subprocess.run(["open", "-a", "Google Chrome", "https://soundcloud.com"], check=False)


# Old StreamFLACr config directory (for migration)
_OLD_STREAMFLACR_CONFIG = Path.home() / ".config" / "streamflacr"
