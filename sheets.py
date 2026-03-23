"""Google Sheets integration for updating roster data."""

import logging
from datetime import datetime, timezone
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from config import (
    CHANGES_WORKSHEET_NAME,
    GOOGLE_CREDENTIALS_PATH,
    GOOGLE_SHEET_ID,
    WORKSHEET_NAME,
)
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
    Expected columns: Team | Role | Player Name (datdota) | Alt. Name(s) | Notes

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
        rows.append(
            [entry.team, entry.role, entry.datdota_name, entry.alt_names, entry.notes]
        )

    # Clear existing data (keep header row)
    existing = worksheet.get_all_values()
    if len(existing) > 1:
        # Clear from row 2 onwards
        end_row = max(len(existing), len(rows) + 1)
        cell_range = f"A2:E{end_row}"
        worksheet.batch_clear([cell_range])

    # Write new data starting from row 2
    if rows:
        cell_range = f"A2:E{len(rows) + 1}"
        worksheet.update(cell_range, rows)

    logger.info("Updated Google Sheet with %d player entries", len(rows))


def _read_current_roster(worksheet: gspread.Worksheet) -> list[dict]:
    """Read the current roster data from the Google Sheet.

    Returns:
        List of dicts with keys: team, role, datdota_name, alt_names, notes.
        Each dict represents one row from the sheet (skipping the header).
    """
    rows = worksheet.get_all_values()
    if len(rows) <= 1:
        return []

    current = []
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        current.append(
            {
                "team": row[0],
                "role": str(row[1]) if len(row) > 1 else "",
                "datdota_name": row[2] if len(row) > 2 else "",
                "alt_names": row[3] if len(row) > 3 else "",
                "notes": row[4] if len(row) > 4 else "",
            }
        )
    return current


def detect_changes(
    old_roster: list[dict], new_entries: list[PlayerEntry]
) -> list[dict]:
    """Compare old and new roster data and return a list of changes.

    Detects:
    - New players added to a team
    - Players removed from a team
    - Role changes for a player
    - Stand-in status changes
    - Name changes (datdota name updates)

    Args:
        old_roster: Current roster from the sheet (list of dicts).
        new_entries: New roster data (list of PlayerEntry).

    Returns:
        List of change dicts with keys: team, player, change_type, details.
    """
    changes = []

    # Build lookup by (team, role) for old and new
    old_by_team_role: dict[tuple[str, str], dict] = {}
    for row in old_roster:
        key = (row["team"], row["role"])
        old_by_team_role[key] = row

    new_by_team_role: dict[tuple[str, str], dict] = {}
    for entry in new_entries:
        key = (entry.team, str(entry.role))
        new_by_team_role[key] = {
            "team": entry.team,
            "role": str(entry.role),
            "datdota_name": entry.datdota_name,
            "alt_names": entry.alt_names,
            "notes": entry.notes,
        }

    # Check for changes and new additions
    for key, new_row in new_by_team_role.items():
        team, role = key
        if key in old_by_team_role:
            old_row = old_by_team_role[key]
            # Player changed at this position
            if old_row["datdota_name"] != new_row["datdota_name"]:
                changes.append(
                    {
                        "team": team,
                        "player": new_row["datdota_name"],
                        "change_type": "Player Change",
                        "details": (
                            f"Pos {role}: {old_row['datdota_name']} → "
                            f"{new_row['datdota_name']}"
                        ),
                    }
                )
            # Stand-in status changed
            if old_row["notes"] != new_row["notes"]:
                old_note = old_row["notes"] or "(none)"
                new_note = new_row["notes"] or "(none)"
                changes.append(
                    {
                        "team": team,
                        "player": new_row["datdota_name"],
                        "change_type": "Status Change",
                        "details": (
                            f"Pos {role}: notes '{old_note}' → '{new_note}'"
                        ),
                    }
                )
            # Alt name changed
            if old_row["alt_names"] != new_row["alt_names"]:
                changes.append(
                    {
                        "team": team,
                        "player": new_row["datdota_name"],
                        "change_type": "Alt Name Change",
                        "details": (
                            f"Pos {role}: alt '{old_row['alt_names']}' → "
                            f"'{new_row['alt_names']}'"
                        ),
                    }
                )
        else:
            # New team+role combo
            changes.append(
                {
                    "team": team,
                    "player": new_row["datdota_name"],
                    "change_type": "New Player",
                    "details": f"Pos {role}: {new_row['datdota_name']} added",
                }
            )

    # Check for removed positions
    for key, old_row in old_by_team_role.items():
        if key not in new_by_team_role:
            team, role = key
            changes.append(
                {
                    "team": team,
                    "player": old_row["datdota_name"],
                    "change_type": "Player Removed",
                    "details": f"Pos {role}: {old_row['datdota_name']} removed",
                }
            )

    return changes


def _get_or_create_changes_worksheet(
    spreadsheet: gspread.Spreadsheet,
) -> gspread.Worksheet:
    """Get the Daily Changes worksheet, creating it if it doesn't exist."""
    try:
        return spreadsheet.worksheet(CHANGES_WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=CHANGES_WORKSHEET_NAME, rows=1000, cols=5
        )
        # Write header row
        ws.update("A1:E1", [["Date", "Team", "Player", "Change Type", "Details"]])
        logger.info("Created '%s' worksheet", CHANGES_WORKSHEET_NAME)
        return ws


def log_changes_to_sheet(
    spreadsheet: gspread.Spreadsheet, changes: list[dict]
) -> None:
    """Append detected changes to the Daily Changes worksheet.

    Args:
        spreadsheet: The gspread Spreadsheet object.
        changes: List of change dicts from detect_changes().
    """
    if not changes:
        logger.info("No roster changes detected")
        return

    ws = _get_or_create_changes_worksheet(spreadsheet)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    rows = []
    for change in changes:
        rows.append(
            [
                today,
                change["team"],
                change["player"],
                change["change_type"],
                change["details"],
            ]
        )

    # Append after the last row with data
    existing = ws.get_all_values()
    start_row = len(existing) + 1
    cell_range = f"A{start_row}:E{start_row + len(rows) - 1}"
    ws.update(cell_range, rows)

    logger.info(
        "Logged %d change(s) to '%s' worksheet", len(changes), CHANGES_WORKSHEET_NAME
    )


def update_google_sheet_with_changes(
    entries: list[PlayerEntry], scraped_teams: set[str] | None = None
) -> None:
    """Update the Google Sheet and log any roster changes to the Daily Changes tab.

    This reads the current roster, detects changes, logs them to the Daily Changes
    tab, then updates the main roster sheet. Teams that were not scraped (failed or
    returned 0 players) are preserved from the existing sheet data.

    Args:
        entries: List of PlayerEntry objects to write to the sheet.
        scraped_teams: Set of team names that were successfully scraped.
            If provided, existing rows for teams NOT in this set are preserved.
    """
    if not GOOGLE_SHEET_ID:
        raise ValueError(
            "GOOGLE_SHEET_ID is not set in config.py. "
            "Please set it to your Google Sheet ID."
        )

    client = get_gspread_client()
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
    worksheet = spreadsheet.worksheet(WORKSHEET_NAME)

    # Read current roster before updating
    old_roster = _read_current_roster(worksheet)

    # If we know which teams were scraped, preserve data for teams that weren't
    if scraped_teams is not None:
        preserved_entries = []
        for row in old_roster:
            if row["team"] not in scraped_teams:
                preserved_entries.append(
                    PlayerEntry(
                        team=row["team"],
                        role=int(row["role"]) if row["role"].isdigit() else 0,
                        cyberscore_name="",
                        datdota_name=row["datdota_name"],
                        alt_names=row["alt_names"],
                        notes=row["notes"],
                    )
                )
        if preserved_entries:
            logger.info(
                "Preserving %d rows for %d teams that were not scraped",
                len(preserved_entries),
                len({e.team for e in preserved_entries}),
            )
            entries = list(entries) + preserved_entries

    # Detect changes (only for teams that were actually scraped)
    if scraped_teams is not None:
        # Filter old roster to only include teams that were scraped
        filtered_old = [r for r in old_roster if r["team"] in scraped_teams]
        filtered_new = [e for e in entries if e.team in scraped_teams]
        changes = detect_changes(filtered_old, filtered_new)
    else:
        changes = detect_changes(old_roster, entries)

    # Log changes to Daily Changes tab
    log_changes_to_sheet(spreadsheet, changes)

    # Print changes summary
    if changes:
        print(f"\nDetected {len(changes)} change(s):")
        for change in changes:
            print(
                f"  [{change['change_type']}] {change['team']} - "
                f"{change['details']}"
            )
    else:
        print("\nNo roster changes detected since last update.")

    # Now update the main roster sheet
    entries_sorted = sorted(entries, key=lambda e: (e.team, e.role))
    rows = []
    for entry in entries_sorted:
        rows.append(
            [entry.team, entry.role, entry.datdota_name, entry.alt_names, entry.notes]
        )

    # Clear existing data (keep header row)
    existing = worksheet.get_all_values()
    if len(existing) > 1:
        end_row = max(len(existing), len(rows) + 1)
        cell_range = f"A2:E{end_row}"
        worksheet.batch_clear([cell_range])

    # Write new data starting from row 2
    if rows:
        cell_range = f"A2:E{len(rows) + 1}"
        worksheet.update(cell_range, rows)

    logger.info("Updated Google Sheet with %d player entries", len(rows))


def print_roster_table(entries: list[PlayerEntry]) -> None:
    """Print the roster data as a formatted table (for testing without Google Sheets)."""
    entries_sorted = sorted(entries, key=lambda e: (e.team, e.role))

    print(
        f"{'Team':<20} {'Role':<6} {'Player Name (datdota)':<25} "
        f"{'Alt. Name(s)':<20} {'Notes':<15}"
    )
    print("-" * 90)
    for entry in entries_sorted:
        print(
            f"{entry.team:<20} {entry.role:<6} {entry.datdota_name:<25} "
            f"{entry.alt_names:<20} {entry.notes:<15}"
        )
