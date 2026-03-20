"""Google Sheets integration for updating roster data."""

import logging
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_CREDENTIALS_PATH, GOOGLE_SHEET_ID, WORKSHEET_NAME
from scraper import PlayerEntry

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_gspread_client() -> gspread.Client:
    """Create an authenticated gspread client using service account credentials."""
    creds_path = Path(GOOGLE_CREDENTIALS_PATH)
    if not creds_path.exists():
        raise FileNotFoundError(
            f"Google credentials file not found at '{creds_path}'. "
            "Please create a Google Service Account and download the JSON key file. "
            "See README.md for instructions."
        )

    credentials = Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
    return gspread.authorize(credentials)


def update_google_sheet(entries: list[PlayerEntry]) -> None:
    """Update the Google Sheet with roster data.

    Replaces all data below the header row with the new roster entries.
    Expected columns: Team | Role | Player Name (datdota) | Alt. Name(s)

    Args:
        entries: List of PlayerEntry objects to write to the sheet.
    """
    if not GOOGLE_SHEET_ID:
        raise ValueError(
            "GOOGLE_SHEET_ID is not set in config.py. "
            "Please set it to your Google Sheet ID."
        )

    client = get_gspread_client()
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
    worksheet = spreadsheet.worksheet(WORKSHEET_NAME)

    # Build rows sorted by team then role
    entries_sorted = sorted(entries, key=lambda e: (e.team, e.role))
    rows = []
    for entry in entries_sorted:
        rows.append([entry.team, entry.role, entry.datdota_name, entry.alt_names])

    # Clear existing data (keep header row)
    existing = worksheet.get_all_values()
    if len(existing) > 1:
        # Clear from row 2 onwards
        end_row = max(len(existing), len(rows) + 1)
        cell_range = f"A2:D{end_row}"
        worksheet.batch_clear([cell_range])

    # Write new data starting from row 2
    if rows:
        cell_range = f"A2:D{len(rows) + 1}"
        worksheet.update(cell_range, rows)

    logger.info("Updated Google Sheet with %d player entries", len(rows))


def print_roster_table(entries: list[PlayerEntry]) -> None:
    """Print the roster data as a formatted table (for testing without Google Sheets)."""
    entries_sorted = sorted(entries, key=lambda e: (e.team, e.role))

    print(
        f"{'Team':<20} {'Role':<6} {'Player Name (datdota)':<25} {'Alt. Name(s)':<20}"
    )
    print("-" * 75)
    for entry in entries_sorted:
        print(
            f"{entry.team:<20} {entry.role:<6} {entry.datdota_name:<25} {entry.alt_names:<20}"
        )
