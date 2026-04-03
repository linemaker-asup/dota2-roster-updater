"""Scrape team rosters from cyberscore.live and resolve player names to datdota conventions."""

import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from config import (
    DATDOTA_NAME_OVERRIDES,
    LIQUIPEDIA_PAGE_NAMES,
    ROLE_MAP,
    TEAM_NAME_OVERRIDES,
    TEAMS_TO_TRACK,
)
from liquipedia import build_liquipedia_lookup, get_alt_name, get_lp_player_name

logger = logging.getLogger(__name__)


@dataclass
class PlayerEntry:
    """A single player roster entry."""

    team: str
    role: int
    lp_name: str
    cyberscore_name: str
    datdota_name: str
    alt_names: str
    notes: str


def _kill_zombie_chrome() -> None:
    """Kill any leftover Chrome/Chromium processes to prevent resource exhaustion."""
    try:
        subprocess.run(
            ["pkill", "-f", "chromium"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["pkill", "-f", "chrome"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
    except Exception:
        pass


def _create_driver() -> webdriver.Chrome:
    """Create a headless Chrome/Chromium driver."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--single-process")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    # Try to find chromium binary
    for binary in ["/usr/bin/chromium-browser", "/usr/bin/chromium", "/usr/bin/google-chrome"]:
        if os.path.exists(binary):
            options.binary_location = binary
            break
    return webdriver.Chrome(options=options)


def _parse_roster_from_html(html: str) -> list[dict]:
    """Parse the main roster from a cyberscore.live team page HTML.

    Returns a list of dicts with keys: role, nickname, player_id
    """
    soup = BeautifulSoup(html, "html.parser")
    items = soup.find_all("div", class_="single-page-item")

    # Find the roster section (contains "Main roster" text)
    roster_item = None
    for item in items:
        text = item.get_text(strip=True).lower()
        if "main roster" in text or "carry" in text:
            roster_item = item
            break

    if not roster_item:
        logger.warning("Could not find main roster section")
        return []

    players = []
    player_anchors = roster_item.find_all("a", class_="item")

    for anchor in player_anchors:
        href = anchor.get("href", "")
        if "/en/players/" not in href:
            continue

        player_id = href.rstrip("/").split("/")[-1]

        # Parse role from div.role > span.truncate
        role_div = anchor.find("div", class_="role")
        role_text = ""
        if role_div:
            role_span = role_div.find("span", class_="truncate")
            if role_span:
                role_text = role_span.get_text(strip=True)

        # Parse nickname from div.nickname
        nick_div = anchor.find("div", class_="nickname")
        nickname = nick_div.get_text(strip=True) if nick_div else ""

        # Check for Stand-In label (div.player-type containing "Stand-In")
        is_standin = "Stand-In" in anchor.get_text()

        if role_text and nickname:
            players.append(
                {
                    "role": role_text,
                    "role_num": ROLE_MAP.get(role_text, 0),
                    "nickname": nickname,
                    "player_id": player_id,
                    "is_standin": is_standin,
                }
            )

    return players


def fetch_cyberscore_roster(
    team_id: int, retries: int = 2
) -> tuple[list[dict], str]:
    """Fetch a team's roster from cyberscore.live.

    Creates a fresh browser for each call and cleans up afterward to avoid
    Chrome process accumulation.

    Args:
        team_id: The cyberscore.live team ID.
        retries: Number of retries if roster parsing fails.

    Returns:
        Tuple of (player list, team name from page title).
    """
    url = f"https://cyberscore.live/en/teams/{team_id}/"
    for attempt in range(retries + 1):
        logger.info("Fetching roster from %s (attempt %d)", url, attempt + 1)
        driver = _create_driver()
        try:
            driver.get(url)
            wait = 10 + attempt * 5
            time.sleep(wait)

            html = driver.page_source
            title = driver.title

            # Check if we got past Cloudflare
            if "Just a moment" in title or len(html) < 5000:
                logger.warning("Cloudflare challenge detected, retrying...")
                time.sleep(5)
                continue

            roster = _parse_roster_from_html(html)
            team_name = ""
            if "Dota 2" in title:
                team_name = title.split("Dota 2")[0].strip()

            if roster:
                return roster, team_name

            logger.warning("No roster found on attempt %d", attempt + 1)
        finally:
            try:
                driver.quit()
            except Exception:
                pass
            _kill_zombie_chrome()

    return [], ""


def fetch_all_cyberscore_rosters() -> tuple[list[dict], set[str]]:
    """Fetch rosters for all configured teams from cyberscore.live.

    Creates a fresh browser session for each team and kills zombie Chrome
    processes between teams to prevent resource exhaustion.

    Returns:
        Tuple of (player list, set of team display names that were successfully scraped).
    """
    all_players = []
    scraped_teams: set[str] = set()
    teams_processed = 0

    # Kill any existing Chrome processes before starting
    _kill_zombie_chrome()

    for sheet_name, team_id in TEAMS_TO_TRACK.items():
        try:
            roster, cs_team_name = fetch_cyberscore_roster(team_id)
        except Exception as e:
            logger.error(
                "Failed to fetch %s (ID %d): %s",
                sheet_name,
                team_id,
                e,
            )
            _kill_zombie_chrome()
            roster, cs_team_name = [], ""

        # Use override if available, otherwise use the config key
        display_name = TEAM_NAME_OVERRIDES.get(cs_team_name, sheet_name)

        if roster:
            scraped_teams.add(display_name)

        for player in roster:
            player["team"] = display_name
            all_players.append(player)

        teams_processed += 1
        logger.info(
            "Found %d players for %s (%s) [%d/%d]",
            len(roster),
            display_name,
            cs_team_name,
            teams_processed,
            len(TEAMS_TO_TRACK),
        )

        # Brief pause between teams
        time.sleep(2)

    return all_players, scraped_teams


def fetch_datdota_player_names() -> dict[str, str]:
    """Fetch canonical player names from the datdota API.

    Calls the datdota performances endpoint to get player names exactly
    as datdota displays them (e.g. 'No!ob' without the trademark symbol
    that OpenDota appends).

    Returns:
        Dict mapping lowercase player name -> canonical datdota name.
        Returns empty dict if the API is unavailable.
    """
    url = (
        "https://api.datdota.com/api/players/performances"
        "?tier=1,2,3"
        "&threshold=1"
        "&after=2024-01-01"
        "&before=2030-01-01"
    )
    logger.info("Fetching player names from datdota API")
    lookup: dict[str, str] = {}
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            logger.warning(
                "datdota API returned %d, falling back to OpenDota",
                response.status_code,
            )
            return {}
        data = response.json()
        # The performances endpoint returns a list of player rows.
        # Each row has a "name" (or "player") field with the canonical name.
        rows = data if isinstance(data, list) else data.get("data", data.get("rows", []))
        for row in rows:
            name = (
                row.get("name")
                or row.get("player")
                or row.get("Player")
                or row.get("playerName")
            )
            if name and isinstance(name, str):
                lookup[name.lower().strip()] = name
        logger.info("Loaded %d player names from datdota", len(lookup))
    except Exception as e:
        logger.warning("Failed to fetch datdota player names: %s", e)
    return lookup


def fetch_opendota_pro_players() -> list[dict]:
    """Fetch all pro players from the OpenDota API.

    Returns:
        List of player dicts from OpenDota /api/proPlayers endpoint.
    """
    url = "https://api.opendota.com/api/proPlayers"
    logger.info("Fetching pro players from OpenDota API")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def build_name_lookup(pro_players: list[dict]) -> dict[str, dict]:
    """Build a lookup from lowercase nickname to OpenDota player data.

    This handles the fact that cyberscore and datdota may use slightly
    different capitalizations or spellings for player names.

    Returns:
        Dict mapping lowercase nickname -> OpenDota player dict
    """
    lookup = {}
    for player in pro_players:
        name = player.get("name")
        if name:
            key = name.lower().strip()
            # Keep the first match (most relevant)
            if key not in lookup:
                lookup[key] = player
            # Also index by personaname
        persona = player.get("personaname")
        if persona:
            pkey = persona.lower().strip()
            if pkey not in lookup:
                lookup[pkey] = player
    return lookup


def match_player_to_datdota(
    cyberscore_nickname: str,
    name_lookup: dict[str, dict],
    datdota_names: dict[str, str],
) -> str:
    """Find the datdota name for a player given their cyberscore nickname.

    Resolution order:
    1. Manual override from DATDOTA_NAME_OVERRIDES config
    2. Direct match in datdota API names (case-insensitive)
    3. Direct match in OpenDota pro player names (case-insensitive)
    4. Fall back to the cyberscore name as-is (usually matches datdota)

    Args:
        cyberscore_nickname: Player nickname from cyberscore.live
        name_lookup: Lookup dict from build_name_lookup() (OpenDota)
        datdota_names: Lookup dict from fetch_datdota_player_names()

    Returns:
        The datdota player name.
    """
    # 1. Check manual overrides first
    if cyberscore_nickname in DATDOTA_NAME_OVERRIDES:
        return DATDOTA_NAME_OVERRIDES[cyberscore_nickname]

    key = cyberscore_nickname.lower().strip()

    # 2. Check datdota API names (canonical source)
    if key in datdota_names:
        return datdota_names[key]

    # 3. Check OpenDota pro player name lookup (case-insensitive)
    if key in name_lookup:
        opendota_name = name_lookup[key]["name"]
        # Only use the OpenDota name if it matches the cyberscore name
        # (case-insensitive), since OpenDota sometimes uses different
        # names than datdota (e.g., OpenDota: "AMMAR_THE_F" vs datdota: "ATF")
        if opendota_name.lower() == key:
            return opendota_name

    # 4. Fall back to cyberscore name (usually matches datdota)
    return cyberscore_nickname


def build_roster_data() -> tuple[list[PlayerEntry], set[str]]:
    """Build the complete roster data by combining cyberscore, datdota, and Liquipedia.

    Data sources:
    - Cyberscore.live: team rosters (who is currently playing)
    - datdota API: canonical datdota player names (primary)
    - OpenDota: fallback for datdota player names
    - Liquipedia: alt names and stand-in status

    Returns:
        Tuple of (list of PlayerEntry objects, set of successfully scraped team names).
    """
    # Fetch data from all sources
    cyberscore_players, scraped_teams = fetch_all_cyberscore_rosters()
    datdota_names = fetch_datdota_player_names()
    pro_players = fetch_opendota_pro_players()
    name_lookup = build_name_lookup(pro_players)

    # Build Liquipedia lookup for alt names and stand-in status
    # Only fetch for teams that have a Liquipedia page configured
    lp_teams_map = {
        display_name: page_name
        for display_name, page_name in LIQUIPEDIA_PAGE_NAMES.items()
    }
    logger.info("Fetching Liquipedia data for %d teams...", len(lp_teams_map))
    lp_lookup = build_liquipedia_lookup(lp_teams_map)

    entries = []
    for player in cyberscore_players:
        team_name = player["team"]
        role_num = player["role_num"]
        cs_name = player["nickname"]
        datdota_name = match_player_to_datdota(cs_name, name_lookup, datdota_names)

        lp_team_data = lp_lookup.get(team_name)

        # Player Name column: prefer Liquipedia page name, fall back to
        # cyberscore name, then datdota name.
        lp_name = ""
        if lp_team_data and lp_team_data.get("found"):
            lp_name = get_lp_player_name(lp_team_data, cs_name, role_num)
        if not lp_name:
            lp_name = cs_name or datdota_name

        # Alt. Name(s): Liquipedia alt IDs from the player's page
        alt_names = ""
        if lp_team_data and lp_team_data.get("found"):
            alt_names = get_alt_name(lp_team_data, cs_name, lp_name, role_num)

        # Notes: stand-in status from cyberscore only
        notes = ""
        if player.get("is_standin", False):
            notes = "Stand-In"

        entry = PlayerEntry(
            team=team_name,
            role=role_num,
            lp_name=lp_name,
            cyberscore_name=player["nickname"],
            datdota_name=datdota_name,
            alt_names=alt_names,
            notes=notes,
        )
        entries.append(entry)

    return entries, scraped_teams
