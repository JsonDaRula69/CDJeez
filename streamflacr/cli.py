"""CLI entry point for StreamFLACr."""

import argparse
import asyncio
import logging
import sys

from .setup import run_setup, register_launchdaemon, unregister_launchdaemon


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="streamflacr",
        description="StreamFLACr - Auto-download FLAC from Soulseek for SoundCloud playlist additions",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Default run command (no subcommand)
    parser.add_argument("-d", "--daemon", action="store_true", help="Run as persistent daemon (poll loop)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # setup subcommand
    setup_parser = subparsers.add_parser("setup", help="Run interactive setup wizard")
    setup_parser.add_argument("--uninstall", action="store_true", help="Unregister LaunchDaemon and remove config")

    args = parser.parse_args()

    if args.command == "setup":
        if args.uninstall:
            unregister_launchdaemon()
            return
        run_setup()
        return

    # Run the main daemon
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from .config import SLSK_USERNAME, SLSK_PASSWORD, SOUNDCLOUD_USER_URL
    missing = []
    if not SLSK_USERNAME or not SLSK_PASSWORD:
        missing.append("Soulseek credentials")
    if not SOUNDCLOUD_USER_URL:
        missing.append("SoundCloud user URL")

    if missing:
        logger = logging.getLogger("streamflacr")
        for m in missing:
            logger.error("Missing configuration: %s", m)
        print("\n  Run `streamflacr setup` to configure StreamFLACr.\n")
        sys.exit(1)

    from .__main__ import amain
    asyncio.run(amain(daemon=args.daemon))


if __name__ == "__main__":
    main()
