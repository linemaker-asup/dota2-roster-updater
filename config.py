"""Configuration for the Dota 2 roster updater."""

# Cyberscore.live team IDs to track
# Add or remove teams as needed. Format: "Team Name": cyberscore_team_id
TEAMS_TO_TRACK = {
    "Falcons": 43595,
    "Tundra": 672,
    "MOUZ": 44380,
    "Team Spirit": 646,
    "Team Liquid": 674,
    "PARIVISION": 46254,
    "Team Yandex": 48780,
    "Aurora Gaming": 43734,
    "BetBoom Team": 14124,
    "Natus Vincere": 6779,
    "Xtreme Gaming": 7029,
    "Heroic": 43931,
    "1WIN Team": 44348,
    "OG": 3740,
}

# Mapping from cyberscore.live role names to role numbers
ROLE_MAP = {
    "Carry": 1,
    "Mid": 2,
    "Offlaner": 3,
    "Soft Support": 4,
    "Hard Support": 5,
}

# Mapping from cyberscore team display names to the short names used in the sheet
# Cyberscore uses full names like "Team Falcons", but the sheet may use "Falcons"
TEAM_NAME_OVERRIDES = {
    "Team Falcons": "Falcons",
    "Tundra Esports": "Tundra",
}

# Manual overrides for player names that differ between cyberscore.live and datdota.
# Format: "cyberscore_name": "datdota_name"
# Only add entries where the names actually differ.
DATDOTA_NAME_OVERRIDES = {
    "yamich": "Yamich",
}

# Google Sheet ID (from the sheet URL)
# Example: https://docs.google.com/spreadsheets/d/SHEET_ID/edit
GOOGLE_SHEET_ID = "1wWeavQ02B6NLqpN6KTCvglIYtpWvnPlrm_3dMDd-GNY"

# Google Sheet worksheet name (tab name)
WORKSHEET_NAME = "Sheet1"

# Path to Google Service Account credentials JSON file
GOOGLE_CREDENTIALS_PATH = "credentials.json"

# Selenium settings
CHROMIUM_BINARY = "/usr/bin/chromium-browser"
PAGE_LOAD_WAIT = 10  # seconds to wait for page to load
