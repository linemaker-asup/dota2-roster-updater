"""Fetch roster data (alt names, stand-in status) from Liquipedia Dota 2 wiki."""

import json
import logging
import os
import re
import time

import requests

logger = logging.getLogger(__name__)

# Liquipedia API requires a descriptive User-Agent
_HEADERS = {
    "User-Agent": "Dota2RosterUpdater/1.0 (GitHub; roster-sheet-sync)",
    "Accept-Encoding": "gzip",
}

# Minimum delay between Liquipedia API requests (seconds).
# MediaWiki API requires at least 2 seconds between requests per Liquipedia TOS.
# We use action=query (not action=parse) to stay within the 2s limit.
_REQUEST_DELAY = 3.0

# Track the last request time to enforce rate limiting
_last_request_time = 0.0

# Path to the local wikitext cache file
CACHE_FILE = os.path.join(os.path.dirname(__file__), "lp_cache.json")

# Path to the parsed data cache (players + standins only, much smaller)
PARSED_CACHE_FILE = os.path.join(os.path.dirname(__file__), "lp_parsed_cache.json")

# In-memory cache loaded from file
_cache: dict[str, str] = {}
_cache_loaded = False

# Parsed data cache: page_name -> {"players": [...], "standins": [...]}
_parsed_cache: dict[str, dict] = {}
_parsed_cache_loaded = False


def _load_cache() -> None:
    """Load the wikitext cache from disk if it exists."""
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    _cache_loaded = True
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                _cache = json.load(f)
            logger.info("Loaded Liquipedia cache with %d entries", len(_cache))
        except Exception as e:
            logger.warning("Failed to load cache: %s", e)
            _cache = {}


def _save_cache() -> None:
    """Save the current cache to disk."""
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(_cache, f)
    except Exception as e:
        logger.warning("Failed to save cache: %s", e)


def _load_parsed_cache() -> None:
    """Load the parsed data cache from disk if it exists."""
    global _parsed_cache, _parsed_cache_loaded
    if _parsed_cache_loaded:
        return
    _parsed_cache_loaded = True
    if os.path.exists(PARSED_CACHE_FILE):
        try:
            with open(PARSED_CACHE_FILE) as f:
                _parsed_cache = json.load(f)
            logger.info(
                "Loaded parsed Liquipedia cache with %d entries",
                len(_parsed_cache),
            )
        except Exception as e:
            logger.warning("Failed to load parsed cache: %s", e)
            _parsed_cache = {}


def _save_parsed_cache() -> None:
    """Save the parsed data cache to disk."""
    try:
        with open(PARSED_CACHE_FILE, "w") as f:
            json.dump(_parsed_cache, f)
    except Exception as e:
        logger.warning("Failed to save parsed cache: %s", e)


def _rate_limit() -> None:
    """Enforce rate limiting between Liquipedia API requests."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < _REQUEST_DELAY:
        time.sleep(_REQUEST_DELAY - elapsed)
    _last_request_time = time.time()


def fetch_team_wikitext(page_name: str) -> str | None:
    """Fetch the wikitext of a Liquipedia Dota 2 team page.

    Uses action=query (not action=parse) to stay within the 2s rate limit
    instead of the 30s limit for action=parse.

    Args:
        page_name: The Liquipedia page name (e.g. "Team_Liquid", "Tundra_Esports").

    Returns:
        The raw wikitext string, or None if the page doesn't exist or request fails.
    """
    # Check cache first
    _load_cache()
    if page_name in _cache:
        logger.info("Using cached wikitext for %s", page_name)
        return _cache[page_name]

    _rate_limit()
    url = (
        "https://liquipedia.net/dota2/api.php"
        "?action=query"
        f"&titles={page_name}"
        "&prop=revisions&rvprop=content&rvslots=main"
        "&format=json"
    )
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=15)
            if resp.status_code == 429:
                wait_time = 30 * (attempt + 1)
                logger.warning(
                    "Liquipedia rate limited for %s, waiting %ds (attempt %d)...",
                    page_name, wait_time, attempt + 1,
                )
                time.sleep(wait_time)
                continue
            if resp.status_code != 200:
                logger.warning(
                    "Liquipedia returned status %d for %s",
                    resp.status_code, page_name,
                )
                return None
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            for page_id, page_data in pages.items():
                if page_id == "-1":
                    logger.warning("Liquipedia page not found: %s", page_name)
                    return None
                revisions = page_data.get("revisions", [])
                if revisions:
                    slots = revisions[0].get("slots", {})
                    main_slot = slots.get("main", {})
                    content = main_slot.get("*", "")
                    # Handle redirects (e.g. #REDIRECT [[HEROIC]])
                    if content.startswith("#REDIRECT"):
                        redir_match = re.search(
                            r"\[\[([^\]]+)\]\]", content
                        )
                        if redir_match:
                            target = redir_match.group(1).replace(" ", "_")
                            logger.info(
                                "Following redirect %s -> %s",
                                page_name,
                                target,
                            )
                            return fetch_team_wikitext(target)
                    # Cache the successful result
                    _cache[page_name] = content
                    _save_cache()
                    return content
            return None
        except Exception as e:
            logger.warning("Failed to fetch Liquipedia page %s: %s", page_name, e)
            if attempt < max_retries:
                time.sleep(10)
                continue
            return None
    return None


def _extract_template(wikitext: str, start_marker: str) -> str | None:
    """Extract the full content of a template using depth tracking.

    Finds the first occurrence of *start_marker* and returns everything from
    that position up to (and including) the matching closing ``}}``.
    """
    start = wikitext.find(start_marker)
    if start == -1:
        return None

    depth = 0
    i = start
    while i < len(wikitext):
        if wikitext[i : i + 2] == "{{":
            depth += 1
            i += 2
        elif wikitext[i : i + 2] == "}}":
            depth -= 1
            if depth == 0:
                return wikitext[start : i + 2]
            i += 2
        else:
            i += 1
    return None


def _extract_all_nested_templates(
    text: str, template_name: str
) -> list[str]:
    """Extract all occurrences of ``{{template_name|...}}`` from *text*.

    Uses depth tracking so that nested templates (e.g.
    ``{{LeagueIconSmall/...}}`` inside a ``{{stand-in}}`` template) are
    handled correctly.
    """
    results: list[str] = []
    marker = "{{" + template_name + "|"
    search_start = 0
    while True:
        idx = text.find(marker, search_start)
        if idx == -1:
            break
        # Walk forward with depth tracking
        depth = 0
        i = idx
        while i < len(text):
            if text[i : i + 2] == "{{":
                depth += 1
                i += 2
            elif text[i : i + 2] == "}}":
                depth -= 1
                if depth == 0:
                    # Content between {{template_name| and }}
                    inner = text[idx + len(marker) : i]
                    results.append(inner)
                    search_start = i + 2
                    break
                i += 2
            else:
                i += 1
        else:
            break  # ran off end of string
    return results


def parse_active_squad(wikitext: str) -> list[dict]:
    """Parse the active squad members from team page wikitext.

    Extracts players from the ``{{Squad|status=active}}`` section.

    Returns:
        List of dicts with keys: id, position, name, flag, captain.
    """
    players: list[dict] = []

    # Extract the full {{Squad|status=active ... }} template using depth tracking
    squad_text = _extract_template(wikitext, "{{Squad|status=active")
    if not squad_text:
        # Some teams use {{Squad without status=active (e.g. VP.Prodigy)
        # Try to match {{Squad| or {{Squad\n without status=former/inactive
        squad_text = _extract_template(wikitext, "{{Squad")
        if squad_text and ("status=former" in squad_text[:100] or "status=inactive" in squad_text[:100]):
            squad_text = None
    if not squad_text:
        return players

    # Find all Person templates within the active squad using depth tracking
    for params_str in _extract_all_nested_templates(squad_text, "Person"):
        params = _parse_template_params(params_str)

        player_id = params.get("id", "")
        position_str = params.get("position", "")
        name = params.get("name", "")
        flag = params.get("flag", "")
        captain = params.get("captain", "") == "yes"

        if player_id and position_str:
            try:
                position = int(position_str)
            except ValueError:
                continue
            players.append(
                {
                    "id": player_id,
                    "position": position,
                    "name": name,
                    "flag": flag,
                    "captain": captain,
                }
            )

    return players


def parse_standins(wikitext: str) -> list[dict]:
    """Parse current stand-in information from team page wikitext.

    Looks for ``{{stand-in}}`` templates across the entire page.
    Uses depth-tracking so that nested templates (e.g.
    ``{{LeagueIconSmall/...}}``) inside a stand-in entry do not break
    parameter extraction.

    Returns:
        List of dicts with keys: id, name, team, replacing_id, replacing_name,
        tournament.
    """
    standins: list[dict] = []

    for params_str in _extract_all_nested_templates(wikitext, "stand-in"):
        params = _parse_template_params(params_str)

        standin_id = params.get("id", "")
        standin_name = params.get("name", "")
        standin_team = params.get("team", "")
        replacing_id = params.get("for", "")
        replacing_name = params.get("forname", "")
        tournament = params.get("tournament", "")

        if standin_id:
            standins.append(
                {
                    "id": standin_id,
                    "name": standin_name,
                    "team": standin_team,
                    "replacing_id": replacing_id,
                    "replacing_name": replacing_name,
                    "tournament": tournament,
                }
            )

    return standins


def _parse_template_params(params_str: str) -> dict[str, str]:
    """Parse MediaWiki template parameters from a parameter string.

    Handles both named (key=value) and positional parameters.
    Skips nested templates (e.g. {{LeagueIconSmall/...}}).
    """
    params: dict[str, str] = {}
    # Split on | but not within nested {{ }}
    depth = 0
    current = ""
    for char in params_str:
        if char == "{":
            depth += 1
            current += char
        elif char == "}":
            depth -= 1
            current += char
        elif char == "|" and depth <= 0:
            _add_param(params, current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        _add_param(params, current.strip())

    return params


def _add_param(params: dict[str, str], param_str: str) -> None:
    """Add a single parameter to the params dict."""
    if "=" in param_str:
        key, _, value = param_str.partition("=")
        key = key.strip()
        value = value.strip()
        # Skip values that are mostly nested templates
        if not key.startswith("{"):
            params[key] = value


def get_team_liquipedia_data(
    page_name: str,
) -> dict:
    """Fetch and parse a team's Liquipedia data.

    First checks the parsed data cache, then the wikitext cache,
    and finally tries the live API.

    Returns a dict with:
        - players: list of active squad members (id, position, name)
        - standins: list of current stand-ins (id, replacing_id, etc.)
        - found: bool indicating if the page was found
    """
    # Check parsed cache first (fastest)
    _load_parsed_cache()
    if page_name in _parsed_cache:
        cached = _parsed_cache[page_name]
        logger.info("Using parsed cache for %s", page_name)
        return {
            "players": cached.get("players", []),
            "standins": cached.get("standins", []),
            "found": True,
        }

    # Fall back to wikitext cache / live API
    wikitext = fetch_team_wikitext(page_name)
    if wikitext is None:
        return {"players": [], "standins": [], "found": False}

    players = parse_active_squad(wikitext)
    standins = parse_standins(wikitext)

    # Save to parsed cache for next time
    _parsed_cache[page_name] = {
        "players": players,
        "standins": standins,
    }
    _save_parsed_cache()

    return {"players": players, "standins": standins, "found": True}


def build_liquipedia_lookup(
    teams_page_map: dict[str, str],
) -> dict[str, dict]:
    """Build a lookup of Liquipedia data for all configured teams.

    Args:
        teams_page_map: Mapping from display team name to Liquipedia page name.

    Returns:
        Dict mapping display team name to team Liquipedia data
        (players, standins, found).
    """
    lookup: dict[str, dict] = {}
    total = len(teams_page_map)
    processed = 0

    for display_name, page_name in teams_page_map.items():
        processed += 1
        data = get_team_liquipedia_data(page_name)
        lookup[display_name] = data

        if data["found"]:
            logger.info(
                "Liquipedia: %s (%s) - %d players, %d standins [%d/%d]",
                display_name,
                page_name,
                len(data["players"]),
                len(data["standins"]),
                processed,
                total,
            )
        else:
            logger.warning(
                "Liquipedia: %s (%s) - page not found [%d/%d]",
                display_name,
                page_name,
                processed,
                total,
            )

    return lookup


def get_standin_notes(
    team_data: dict, player_id_or_name: str, position: int
) -> str:
    """Determine stand-in notes for a player based on Liquipedia data.

    Checks if:
    1. The player at this position in the active squad differs from the
       cyberscore player (meaning a stand-in is playing).
    2. The player appears in the stand-ins table.

    Args:
        team_data: Liquipedia team data from get_team_liquipedia_data.
        player_id_or_name: The player name from cyberscore.
        position: The role/position number (1-5).

    Returns:
        Notes string (e.g. "Stand-In", "Stand-In (for Noticed)", or "").
    """
    if not team_data.get("found"):
        return ""

    # Check if a stand-in is listed for this position
    active_players = team_data.get("players", [])
    standins = team_data.get("standins", [])

    # Find the permanent player at this position
    permanent_player = None
    for p in active_players:
        if p["position"] == position:
            permanent_player = p
            break

    # Check if current player matches the permanent player
    if permanent_player:
        perm_id = permanent_player["id"]
        # If the cyberscore player name doesn't match the Liquipedia permanent player
        if (
            perm_id.lower() != player_id_or_name.lower()
            and perm_id.lower().replace("-", "") != player_id_or_name.lower().replace("-", "")
        ):
            # This player might be a stand-in replacing the permanent one
            # Check if there's a stand-in entry confirming this
            for si in standins:
                if si["replacing_id"].lower() == perm_id.lower():
                    return f"Stand-In (for {perm_id})"
            # Even without a stand-in table entry, the mismatch suggests a stand-in
            return "Stand-In"

    # Also check if this player appears in the stand-in table directly
    for si in standins:
        if si["id"].lower() == player_id_or_name.lower():
            replacing = si.get("replacing_id", "")
            if replacing:
                return f"Stand-In (for {replacing})"
            return "Stand-In"

    return ""


def get_alt_name(
    team_data: dict, cyberscore_name: str, position: int
) -> str:
    """Get the Liquipedia player name if it differs from the cyberscore name.

    Args:
        team_data: Liquipedia team data from get_team_liquipedia_data.
        cyberscore_name: The player name from cyberscore.live.
        position: The role/position number (1-5).

    Returns:
        The Liquipedia name if different from cyberscore_name, else empty string.
    """
    if not team_data.get("found"):
        return ""

    active_players = team_data.get("players", [])

    # Find the player at this position in the Liquipedia active squad
    for p in active_players:
        if p["position"] == position:
            lp_id = p["id"]
            # If Liquipedia name differs from cyberscore name, return it as alt
            if lp_id != cyberscore_name:
                return lp_id
            break

    return ""
