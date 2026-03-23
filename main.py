"""Main entry point for the Dota 2 roster updater.

Usage:
    python main.py                  # Print roster to console (no Google Sheets)
    python main.py --update-sheet   # Update the Google Sheet
    python main.py --teams Falcons Tundra MOUZ  # Only update specific teams
"""

import argparse
import logging
import sys

from config import GOOGLE_SHEET_ID, TEAMS_TO_TRACK
from scraper import build_roster_data
from sheets import print_roster_table, update_google_sheet_with_changes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update Google Sheet with Dota 2 team rosters from cyberscore.live and datdota."
    )
    parser.add_argument(
        "--update-sheet",
        action="store_true",
        help="Update the Google Sheet (requires credentials and GOOGLE_SHEET_ID in config.py)",
    )
    parser.add_argument(
        "--teams",
        nargs="+",
        help="Only process specific teams (by their config key name)",
    )
    args = parser.parse_args()

    # Filter teams if specified
    if args.teams:
        unknown = [t for t in args.teams if t not in TEAMS_TO_TRACK]
        if unknown:
            logger.error(
                "Unknown team(s): %s. Available: %s",
                ", ".join(unknown),
                ", ".join(TEAMS_TO_TRACK.keys()),
            )
            sys.exit(1)

        # Temporarily override TEAMS_TO_TRACK
        import config

        original = config.TEAMS_TO_TRACK.copy()
        config.TEAMS_TO_TRACK = {k: v for k, v in original.items() if k in args.teams}

    logger.info("Building roster data...")
    entries = build_roster_data()

    if not entries:
        logger.error("No roster data found. Check your network connection and config.")
        sys.exit(1)

    # Always print the table
    print()
    print_roster_table(entries)
    print()

    if args.update_sheet:
        if not GOOGLE_SHEET_ID:
            logger.error(
                "GOOGLE_SHEET_ID not set in config.py. "
                "Set it to your Google Sheet ID before using --update-sheet."
            )
            sys.exit(1)
        logger.info("Updating Google Sheet (with change tracking)...")
        update_google_sheet_with_changes(entries)
        logger.info("Google Sheet updated successfully!")
    else:
        logger.info(
            "Dry run complete. Use --update-sheet to push data to Google Sheets."
        )


if __name__ == "__main__":
    main()
