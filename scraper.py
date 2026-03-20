"""Scrape team rosters from cyberscore.live and resolve player names to datdota conventions."""

import logging
import time
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from config import (
    CHROMIUM_BINARY,
    DATDOTA_NAME_OVERRIDES,
    PAGE_LOAD_WAIT,
    ROLE_MAP,
    TEAM_NAME_OVERRIDES,
    TEAMS_TO_TRACK,
)

logger = logging.getLogger(__name__)


@dataclass
class PlayerEntry:
    """A single player roster entry."""

    team: str
    role: int
    cyberscore_name: str
    datdota_name: str
    alt_names: str


def _create_driver() -> webdriver.Chrome:
    """Create a headless Chrome/Chromium driver."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    if CHROMIUM_BINARY:
        options.binary_location = CHROMIUM_BINARY
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

        if role_text and nickname:
            players.append(
                {
                    "role": role_text,
                    "role_num": ROLE_MAP.get(role_text, 0),
                    "nickname": nickname,
                    "player_id": player_id,
                }
            )

    return players


def fetch_cyberscore_roster(
    team_id: int, driver: webdriver.Chrome, retries: int = 2
) -> tuple[list[dict], str]:
    """Fetch a team's roster from cyberscore.live.

    Args:
        team_id: The cyberscore.live team ID.
        driver: Selenium WebDriver instance.
        retries: Number of retries if roster parsing fails.

    Returns:
        Tuple of (player list, team name from page title).
    """
    url = f"https://cyberscore.live/en/teams/{team_id}/"
    for attempt in range(retries + 1):
        logger.info("Fetching roster from %s (attempt %d)", url, attempt + 1)
        driver.get(url)
        wait = PAGE_LOAD_WAIT + attempt * 5
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

    return [], ""


def fetch_all_cyberscore_rosters() -> list[dict]:
    """Fetch rosters for all configured teams from cyberscore.live.

    Creates a fresh browser session for each team to avoid Cloudflare issues.

    Returns:
        List of dicts with team, role, nickname, player_id for each player.
    """
    all_players = []

    for sheet_name, team_id in TEAMS_TO_TRACK.items():
        driver = _create_driver()
        try:
            roster, cs_team_name = fetch_cyberscore_roster(team_id, driver)
            # Use override if available, otherwise use the config key
            display_name = TEAM_NAME_OVERRIDES.get(cs_team_name, sheet_name)

            for player in roster:
                player["team"] = display_name
                all_players.append(player)

            logger.info(
                "Found %d players for %s (%s)",
                len(roster),
                display_name,
                cs_team_name,
            )
        finally:
            driver.quit()

        # Brief pause between teams to be polite to the server
        time.sleep(2)

    return all_players


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
    cyberscore_nickname: str, name_lookup: dict[str, dict]
) -> str:
    """Find the datdota name for a player given their cyberscore nickname.

    Resolution order:
    1. Manual override from DATDOTA_NAME_OVERRIDES config
    2. Direct match in OpenDota pro player names (case-insensitive)
    3. Fall back to the cyberscore name as-is (usually matches datdota)

    Args:
        cyberscore_nickname: Player nickname from cyberscore.live
        name_lookup: Lookup dict from build_name_lookup()

    Returns:
        The datdota player name.
    """
    # 1. Check manual overrides first
    if cyberscore_nickname in DATDOTA_NAME_OVERRIDES:
        return DATDOTA_NAME_OVERRIDES[cyberscore_nickname]

    key = cyberscore_nickname.lower().strip()

    # 2. Check OpenDota pro player name lookup (case-insensitive)
    if key in name_lookup:
        opendota_name = name_lookup[key]["name"]
        # Only use the OpenDota name if it matches the cyberscore name
        # (case-insensitive), since OpenDota sometimes uses different
        # names than datdota (e.g., OpenDota: "AMMAR_THE_F" vs datdota: "ATF")
        if opendota_name.lower() == key:
            return opendota_name

    # 3. Fall back to cyberscore name (usually matches datdota)
    return cyberscore_nickname


def build_roster_data() -> list[PlayerEntry]:
    """Build the complete roster data by combining cyberscore and datdota data.

    Returns:
        List of PlayerEntry objects ready for Google Sheet update.
    """
    # Fetch data from both sources
    cyberscore_players = fetch_all_cyberscore_rosters()
    pro_players = fetch_opendota_pro_players()
    name_lookup = build_name_lookup(pro_players)

    entries = []
    for player in cyberscore_players:
        datdota_name = match_player_to_datdota(player["nickname"], name_lookup)

        # Build alt names: if datdota name differs from cyberscore name, note it
        alt_names = ""
        if datdota_name.lower() != player["nickname"].lower():
            alt_names = player["nickname"]

        entry = PlayerEntry(
            team=player["team"],
            role=player["role_num"],
            cyberscore_name=player["nickname"],
            datdota_name=datdota_name,
            alt_names=alt_names,
        )
        entries.append(entry)

    return entries
