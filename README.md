# Dota 2 Roster Updater

Automatically updates a Google Sheet with Dota 2 team rosters by combining data from:
- **[cyberscore.live](https://cyberscore.live/en/)** — Current team rosters and player roles
- **[datdota.com](https://datdota.com/)** — Player name conventions (verified via [OpenDota API](https://api.opendota.com/))

## Features

- Scrapes cyberscore.live for up-to-date team rosters (team name, role, player nickname)
- Resolves player names to match datdota.com conventions
- Updates a Google Sheet with columns: `Team | Role | Player Name (datdota) | Alt. Name(s)`
- Configurable team list and name override mappings
- Headless browser scraping (Selenium + Chromium) to handle Cloudflare protection

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Chromium (for headless scraping)

```bash
# Ubuntu/Debian
sudo apt-get install -y chromium-browser
```

### 3. Configure teams

Edit `config.py` to set which teams to track:

```python
TEAMS_TO_TRACK = {
    "Falcons": 43595,    # cyberscore.live team ID
    "Tundra": 672,
    "MOUZ": 44380,
}
```

To find a team's cyberscore ID, visit their page on cyberscore.live — the ID is in the URL:
`https://cyberscore.live/en/teams/{TEAM_ID}/`

### 4. Google Sheets setup (optional)

To enable automatic Google Sheet updates:

1. Create a [Google Cloud Service Account](https://console.cloud.google.com/iam-admin/serviceaccounts)
2. Download the JSON key file and save it as `credentials.json` in the project root
3. Share your Google Sheet with the service account email (as Editor)
4. Set `GOOGLE_SHEET_ID` in `config.py`

## Usage

### Dry run (print to console)

```bash
python main.py
```

### Update Google Sheet

```bash
python main.py --update-sheet
```

### Process specific teams only

```bash
python main.py --teams Falcons Tundra MOUZ
```

### Update specific teams in the sheet

```bash
python main.py --update-sheet --teams Falcons Tundra
```

## Name Resolution

Player names are resolved in this order:
1. **Manual overrides** — `DATDOTA_NAME_OVERRIDES` in `config.py`
2. **OpenDota verification** — Cross-checked against the OpenDota pro players API
3. **Cyberscore name** — Used as-is (usually matches datdota)

If a name differs between cyberscore and datdota, add it to `DATDOTA_NAME_OVERRIDES`:

```python
DATDOTA_NAME_OVERRIDES = {
    "yamich": "Yamich",  # cyberscore uses lowercase, datdota uses capital Y
}
```

## Adding Teams

1. Find the team on [cyberscore.live/en/teams/](https://cyberscore.live/en/teams/)
2. Note the team ID from the URL
3. Add it to `TEAMS_TO_TRACK` in `config.py`
4. If the cyberscore display name differs from what you want in the sheet, add an entry to `TEAM_NAME_OVERRIDES`
