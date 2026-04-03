"""Configuration for the Dota 2 roster updater."""

# Cyberscore.live team IDs to track
# Add or remove teams as needed. Format: "Team Name": cyberscore_team_id
TEAMS_TO_TRACK = {
    # Tier 1 teams (rank 1-14)
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
    # Tier 2 teams (rank 15-20)
    "Power Rangers": 48077,
    "Nigma Galaxy": 6702,
    "GamerLegion": 49148,
    "Vici Gaming": 283,
    "Most Wanted": 49024,
    "Pipsqueak+4": 48855,
    # Tier 2-3 teams (rank 21-40)
    "Virtus Pro": 651,
    "L1GA TEAM": 43932,
    "Zero Tenacity": 46898,
    "Execration": 214,
    "Yellow Submarine": 43443,
    "Yakult Brothers": 46467,
    "Avulus": 44855,
    "Rottwelias Latam": 41777,
    "REKONIX": 48810,
    "Team Lynx": 47603,
    "Rune Eaters": 344,
    "PlayTime": 49328,
    "Inner Circle": 17229,
    "Team Nemesis": 47908,
    "Nemiga Gaming": 309,
    "VP Prodigy": 47115,
    # Tier 3 teams (rank 41-60+)
    "1000 Reasons": 41699,
    "Game Master": 41690,
    "Amaru Gaming": 41380,
    "YB.Tearlaments": 47943,
    "Valinor": 41857,
    "Trailer Park Boys": 47984,
    "BTC Gaming": 41648,
    "Ivory Team": 45030,
    "Yangon Galacticos": 1811,
    "X5 Gaming": 41865,
    # Other teams from original sheet
    "4Pirates": 46896,
    "Red Submarine": 48011,
    "Kukuysv2": 46156,
    "Strongboys": 41963,
    "Looking for Org PE": 41718,
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
    "Xtreme Gaming": "Xtreme",
    "Team Yandex": "Yandex",
    "1WIN Team": "1WIN",
    "Heroic": "HEROIC",
    "Virtus.pro": "Virtus Pro",
    "VP.Prodigy": "VP Prodigy",
    "Air Defence": "Looking for Org PE",
    "1000 reasons": "1000 Reasons",
    "YB.Tearlaments": "YB.Tearlaments",
    "Rottweilas Latam": "Rottwelias Latam",
}

# Manual overrides for player names that differ between cyberscore.live and datdota.
# Format: "cyberscore_name": "datdota_name"
# Only add entries where the names actually differ.
# Verified against datdota.com team/player pages.
DATDOTA_NAME_OVERRIDES = {
    # MOUZ
    "yamich": "Yamich",
    # Team Liquid
    "m1CKe": "MiCKe",
    "Ace \u2660": "Ace",
    # OG
    "Yopaj-": "Yopaj",
    "Nikko": "Force",
    "TIMS": "Tims",
    "skem": "Skem",
    # PARIVISION
    "No[o]ne-": "Noone",
    # BetBoom Team
    "Kataomi": "kataomi",
    "MieRo": "MieRo'",
    # Natus Vincere
    "pma": "Pma",
    # Aurora Gaming
    "kaori": "Kaori",
    "Ws": "Ws`",
    # Team Spirit
    "panto": "pantomem",
    "rue": "Rue",
    # Tundra
    "Bzm": "bzm",
    # Xtreme Gaming
    "xNova": "Xnova",
    # Team Yandex
    "watson": "Watson",
    "CHIRA_JUNIOR": "CHIRA JUNIOR",
    # Nigma Galaxy
    "OmaR": "Omar",
    # Capitalization fixes: OpenDota uses different casing than datdota
    # Verified against datdota.com/players/performances page
    "Elmisho": "elmisho",
    "fy": "Fy",
    "nefrit": "Nefrit",
    "sanctity-": "Sanctity-",
}

# Mapping from display team name (config key) to Liquipedia page name.
# Used to fetch alt names and stand-in status from Liquipedia.
# Teams not listed here will be skipped for Liquipedia data.
LIQUIPEDIA_PAGE_NAMES: dict[str, str] = {
    # Tier 1 teams
    "Falcons": "Team_Falcons",
    "Tundra": "Tundra_Esports",
    "MOUZ": "MOUZ",
    "Team Spirit": "Team_Spirit",
    "Team Liquid": "Team_Liquid",
    "PARIVISION": "PARIVISION",
    "Yandex": "Team_Yandex",
    "Aurora Gaming": "Aurora_Gaming",
    "BetBoom Team": "BetBoom_Team",
    "Natus Vincere": "Natus_Vincere",
    "Xtreme": "Xtreme_Gaming",
    "HEROIC": "HEROIC",
    "1WIN": "1w_Team",
    "OG": "OG",
    # Tier 2 teams
    "Power Rangers": "Power_Rangers",
    "Nigma Galaxy": "Nigma_Galaxy",
    "GamerLegion": "GamerLegion",
    "Vici Gaming": "Vici_Gaming",
    # Tier 2-3 teams
    "Virtus Pro": "Virtus.pro",
    "L1GA TEAM": "L1GA_TEAM",
    "Zero Tenacity": "Zero_Tenacity",
    "Execration": "Execration",
    "Yakult Brothers": "Yakult_Brothers",
    "Nemiga Gaming": "Nemiga_Gaming",
    "VP Prodigy": "VP.Prodigy",
    "Team Nemesis": "Team_Nemesis",
    "REKONIX": "REKONIX",
    "Rune Eaters": "Rune_Eaters",
    "Yangon Galacticos": "Yangon_Galacticos",
    "X5 Gaming": "X5_Gaming",
    "Power Rangers": "Power_Rangers",
}

# Google Sheet ID (from the sheet URL)
# Example: https://docs.google.com/spreadsheets/d/SHEET_ID/edit
GOOGLE_SHEET_ID = "1wWeavQ02B6NLqpN6KTCvglIYtpWvnPlrm_3dMDd-GNY"

# Google Sheet worksheet name (tab name)
WORKSHEET_NAME = "7.40"

# Worksheet name for daily change tracking
CHANGES_WORKSHEET_NAME = "Daily Changes"

# Path to Google Service Account credentials JSON file
GOOGLE_CREDENTIALS_PATH = "credentials.json"
