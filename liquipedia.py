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
_REQUEST_DELAY = 5.0

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


def _scrub_cached_alt_ids() -> None:
    """Remove HTML comments from any alt_ids already stored in the cache.

    This is a one-time migration for caches written before the
    comment-stripping fix was added to ``_parse_player_alt_ids``.

    The old code split on commas *before* stripping comments, so a comment
    like ``<!--DPC2021, 2023-->`` got broken across multiple list items.
    To handle this we rejoin the list into a single string, strip comments,
    then re-split — exactly like ``_parse_player_alt_ids`` does now.
    """
    dirty = False
    for team_data in _parsed_cache.values():
        for p in team_data.get("players", []):
            raw = p.get("alt_ids")
            if not raw:
                continue
            # Rejoin into a single string so the regex can match comments
            # that were split across list items by commas.
            joined = ", ".join(raw)
            joined = re.sub(r"<!--.*?-->", "", joined)
            cleaned = []
            for aid in joined.split(","):
                aid = aid.strip()
                if aid and re.search(r"\w", aid, flags=re.UNICODE):
                    cleaned.append(aid)
            if cleaned != raw:
                p["alt_ids"] = cleaned
                dirty = True
    if dirty:
        _save_parsed_cache()
        logger.info("Scrubbed HTML comments from cached alt_ids")


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
            # Scrub any HTML comments from cached alt_ids (one-time cleanup
            # for caches written before the comment-stripping fix).
            _scrub_cached_alt_ids()
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
    max_retries = 4
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=15)
            if resp.status_code == 429:
                wait_time = 60 * (attempt + 1)
                logger.warning(
                    "Liquipedia rate limited for %s, waiting %ds (attempt %d/%d)...",
                    page_name, wait_time, attempt + 1, max_retries + 1,
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

        link = params.get("link", "")

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
                    "link": link,
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


def _parse_player_alt_ids(wikitext: str) -> list[str]:
    """Extract alternate IDs from a Liquipedia player page's Infobox.

    Looks for the ``|ids=`` field in ``{{Infobox player}}``.

    Returns:
        List of alternate ID strings (may be empty).
    """
    # Handle redirects
    if wikitext.startswith("#REDIRECT"):
        return []

    # Find |ids= in the Infobox player template
    match = re.search(r"\|ids\s*=\s*([^\n|}{]+)", wikitext)
    if not match:
        return []

    ids_str = match.group(1).strip()
    if not ids_str:
        return []

    # Strip HTML comments (e.g. <!--DPC2021-->)
    ids_str = re.sub(r"<!--.*?-->", "", ids_str)

    # Split on comma, clean up, and filter out punctuation-only artifacts
    result = []
    for aid in ids_str.split(","):
        aid = aid.strip()
        # Skip empty or punctuation-only strings (artifacts from comment stripping)
        if aid and re.search(r"\w", aid, flags=re.UNICODE):
            result.append(aid)
    return result


def _resolve_player_page_name(player: dict) -> str:
    """Determine the Liquipedia page name for a player.

    Uses the ``link`` field if present (for disambiguation),
    otherwise capitalises the first letter of the ``id``.
    """
    link = player.get("link", "")
    if link:
        return link.replace(" ", "_")
    pid = player["id"]
    # Liquipedia page names have the first letter capitalised
    return pid[0].upper() + pid[1:] if pid else pid


def fetch_player_alt_ids_batch(
    players: list[dict],
) -> dict[str, list[str]]:
    """Fetch alternate IDs for a batch of players from their Liquipedia pages.

    Uses the MediaWiki multi-title query API to fetch up to 50 pages at once.
    Falls back to web_get_contents if direct API calls are rate-limited.

    Args:
        players: List of player dicts (must have ``id`` and optionally ``link``).

    Returns:
        Dict mapping player id -> list of alternate IDs.
    """
    result: dict[str, list[str]] = {}
    if not players:
        return result

    # Build page_name -> player_id mapping
    page_to_ids: dict[str, list[str]] = {}
    for p in players:
        page_name = _resolve_player_page_name(p)
        page_to_ids.setdefault(page_name, []).append(p["id"])

    def _fetch_pages_batch(page_names_to_fetch: list[str]) -> list[str]:
        """Fetch a list of pages and return any redirect targets found."""
        redirect_targets: list[str] = []
        for batch_start in range(0, len(page_names_to_fetch), 50):
            batch = page_names_to_fetch[batch_start : batch_start + 50]
            titles_param = "|".join(batch)
            url = (
                "https://liquipedia.net/dota2/api.php"
                "?action=query"
                f"&titles={titles_param}"
                "&prop=revisions&rvprop=content&rvslots=main"
                "&rvsection=0&format=json"
            )

            _rate_limit()
            try:
                resp = requests.get(url, headers=_HEADERS, timeout=30)

                # Retry up to 3 times on rate limit with exponential backoff
                for retry in range(1, 4):
                    if resp.status_code != 429:
                        break
                    wait_time = 10 * retry  # 10s, 20s, 30s
                    logger.warning(
                        "Rate limited fetching player pages, retrying in %ds "
                        "(attempt %d/3)...",
                        wait_time,
                        retry,
                    )
                    time.sleep(wait_time)
                    resp = requests.get(url, headers=_HEADERS, timeout=30)

                if resp.status_code == 429:
                    logger.warning(
                        "Still rate limited after 3 retries, skipping batch"
                    )
                    continue
                if resp.status_code != 200:
                    logger.warning(
                        "Player page batch returned %d", resp.status_code
                    )
                    continue

                data = resp.json()
                pages = data.get("query", {}).get("pages", {})

                # Build a normalised title lookup
                normalised = {}
                for n in data.get("query", {}).get("normalized", []):
                    normalised[n["to"]] = n["from"]

                for page_id_str, page_data in pages.items():
                    if page_id_str == "-1" or "missing" in page_data:
                        continue
                    title = page_data.get("title", "")
                    # Map back to our page_name key
                    original_key = normalised.get(title, title).replace(
                        " ", "_"
                    )
                    revisions = page_data.get("revisions", [])
                    if not revisions:
                        continue
                    content = (
                        revisions[0]
                        .get("slots", {})
                        .get("main", {})
                        .get("*", "")
                    )
                    # Handle redirects — collect targets for a second pass
                    if content.startswith("#REDIRECT"):
                        redir_match = re.search(
                            r"\[\[([^\]]+)\]\]", content
                        )
                        if redir_match:
                            target = redir_match.group(1).replace(" ", "_")
                            page_to_ids.setdefault(target, []).extend(
                                page_to_ids.get(original_key, [])
                            )
                            redirect_targets.append(target)
                        continue

                    alt_ids = _parse_player_alt_ids(content)
                    for pid in page_to_ids.get(original_key, []):
                        result[pid] = alt_ids

            except Exception as e:
                logger.warning("Failed to fetch player alt IDs batch: %s", e)

        return redirect_targets

    # First pass: fetch all player pages
    page_names = list(page_to_ids.keys())
    redirects = _fetch_pages_batch(page_names)

    # Second pass: fetch redirect targets that weren't already resolved
    unresolved = [t for t in redirects if t not in result and t in page_to_ids]
    if unresolved:
        logger.info("Fetching %d redirect target pages...", len(unresolved))
        _fetch_pages_batch(unresolved)

    return result


def get_team_liquipedia_data(
    page_name: str,
) -> dict:
    """Fetch and parse a team's Liquipedia data.

    First checks the parsed data cache, then the wikitext cache,
    and finally tries the live API.

    Returns a dict with:
        - players: list of active squad members (id, position, name, alt_ids)
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

    # Carry over cached alt_ids for players that haven't changed.
    # This avoids re-fetching alt IDs from individual player pages
    # when only the team page is refreshed.
    if page_name in _parsed_cache:
        old_players = _parsed_cache[page_name].get("players", [])
        old_by_id = {p["id"]: p for p in old_players}
        for p in players:
            old_p = old_by_id.get(p["id"])
            if old_p and old_p.get("alt_ids"):
                p["alt_ids"] = old_p["alt_ids"]

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

    Also fetches player alt IDs from individual player pages and
    populates the ``alt_ids`` field on each player dict.

    Args:
        teams_page_map: Mapping from display team name to Liquipedia page name.

    Returns:
        Dict mapping display team name to team Liquipedia data
        (players, standins, found).
    """
    lookup: dict[str, dict] = {}
    total = len(teams_page_map)
    processed = 0

    # Collect all players that need alt ID lookups
    all_players_needing_alt_ids: list[dict] = []

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
            # Queue players that don't have alt_ids yet.
            for p in data["players"]:
                if not p.get("alt_ids"):
                    all_players_needing_alt_ids.append(p)
        else:
            logger.warning(
                "Liquipedia: %s (%s) - page not found [%d/%d]",
                display_name,
                page_name,
                processed,
                total,
            )

    # Batch-fetch player alt IDs from their individual pages
    if all_players_needing_alt_ids:
        logger.info(
            "Fetching alt IDs for %d players from Liquipedia player pages...",
            len(all_players_needing_alt_ids),
        )
        alt_ids_map = fetch_player_alt_ids_batch(all_players_needing_alt_ids)

        # Populate alt_ids on each player dict (mutates in place)
        for p in all_players_needing_alt_ids:
            pid = p["id"]
            if pid in alt_ids_map:
                p["alt_ids"] = alt_ids_map[pid]

        # Update the parsed cache with alt_ids
        _load_parsed_cache()
        for display_name, page_name in teams_page_map.items():
            data = lookup[display_name]
            if data["found"] and page_name in _parsed_cache:
                _parsed_cache[page_name]["players"] = data["players"]
        _save_parsed_cache()

        logger.info(
            "Fetched alt IDs for %d/%d players",
            len(alt_ids_map),
            len(all_players_needing_alt_ids),
        )

    return lookup


def _names_match(name_a: str, name_b: str) -> bool:
    """Check if two player names refer to the same player.

    Handles case differences, punctuation, and common transliteration
    patterns (e.g. Cyrillic vs Latin).
    """
    if not name_a or not name_b:
        return False

    a = name_a.lower().strip()
    b = name_b.lower().strip()

    if a == b:
        return True

    # Strip common suffixes/prefixes: `, -, ~, ', ♠, ^, etc.
    strip_chars = "`-~'^♠ ♡_"
    a_stripped = a.rstrip(strip_chars).lstrip(strip_chars)
    b_stripped = b.rstrip(strip_chars).lstrip(strip_chars)
    if a_stripped and b_stripped and a_stripped == b_stripped:
        return True

    # Remove all non-alphanumeric (keeps unicode letters)
    a_clean = re.sub(r"[^\w]", "", a, flags=re.UNICODE)
    b_clean = re.sub(r"[^\w]", "", b, flags=re.UNICODE)
    if a_clean and b_clean and a_clean == b_clean:
        return True

    return False


def _player_matches_any_id(
    cyberscore_name: str, player: dict
) -> bool:
    """Check if a cyberscore name matches any of a player's known IDs.

    Compares against the primary ID and all alternate IDs.
    """
    # Check primary ID
    if _names_match(cyberscore_name, player["id"]):
        return True
    # Check alternate IDs from Liquipedia player page
    for alt_id in player.get("alt_ids", []):
        if _names_match(cyberscore_name, alt_id):
            return True
    return False


def get_standin_notes(
    team_data: dict, player_id_or_name: str, position: int
) -> str:
    """Determine stand-in notes for a player based on Liquipedia data.

    Checks if:
    1. The player appears in the stand-ins table (most reliable).
    2. The player at this position in the active squad differs from the
       cyberscore player (meaning a stand-in is playing), checking against
       all known alternate IDs.

    Args:
        team_data: Liquipedia team data from get_team_liquipedia_data.
        player_id_or_name: The player name from cyberscore.
        position: The role/position number (1-5).

    Returns:
        Notes string (e.g. "Stand-In", "Stand-In (for flyfly)", or "").
    """
    if not team_data.get("found"):
        return ""

    active_players = team_data.get("players", [])
    standins = team_data.get("standins", [])

    # First, check if this player appears in the stand-in table directly
    for si in standins:
        if _names_match(si["id"], player_id_or_name):
            replacing = si.get("replacing_id", "")
            if replacing:
                return f"Stand-In (for {replacing})"
            return "Stand-In"

    # Find the permanent player at this position
    permanent_player = None
    for p in active_players:
        if p["position"] == position:
            permanent_player = p
            break

    # Check if cyberscore player matches permanent player (using all known IDs)
    if permanent_player:
        if _player_matches_any_id(player_id_or_name, permanent_player):
            # Player matches the permanent roster — not a stand-in
            return ""

        # Mismatch: the cyberscore player is not the permanent one.
        # Check if there's a stand-in entry for this position.
        perm_id = permanent_player["id"]
        for si in standins:
            if _names_match(si["replacing_id"], perm_id):
                return f"Stand-In (for {perm_id})"
        # No explicit stand-in entry but names don't match — likely a stand-in
        return "Stand-In"

    return ""


def get_lp_player_name(
    team_data: dict, cyberscore_name: str, position: int
) -> str:
    """Get the Liquipedia primary name for a player.

    Finds the player matching the cyberscore name (by primary ID or alt IDs)
    and returns their Liquipedia primary ID (the name used on the Person
    template on the team page).

    Args:
        team_data: Liquipedia team data from get_team_liquipedia_data.
        cyberscore_name: The player name from cyberscore.live.
        position: The role/position number (1-5).

    Returns:
        The Liquipedia player name, or empty string if not found.
    """
    if not team_data.get("found"):
        return ""

    active_players = team_data.get("players", [])

    # First try to match by name across all players (not position-dependent)
    for p in active_players:
        if _player_matches_any_id(cyberscore_name, p):
            return p["id"]

    # Fall back to position-based matching.  This is needed when a player's
    # cyberscore name is in a different script (e.g. Latin "mister moral" vs
    # Cyrillic "мистер мораль") and alt_ids haven't been fetched yet.
    for p in active_players:
        if p["position"] == position:
            return p["id"]

    return ""


def get_alt_name(
    team_data: dict, cyberscore_name: str, lp_name: str, position: int
) -> str:
    """Get Liquipedia alternate names for a player.

    Returns the alt IDs from the player's Liquipedia page that differ from
    the Liquipedia primary name. This ensures alt names accurately reflect
    what's on the Liquipedia page.

    Args:
        team_data: Liquipedia team data from get_team_liquipedia_data.
        cyberscore_name: The player name from cyberscore.live.
        lp_name: The Liquipedia primary name for this player.
        position: The role/position number (1-5).

    Returns:
        Comma-separated Liquipedia alt names, or empty string.
    """
    if not team_data.get("found"):
        return ""

    active_players = team_data.get("players", [])

    # Find the matching player
    matched_player = None
    for p in active_players:
        if _player_matches_any_id(cyberscore_name, p):
            matched_player = p
            break

    # Fall back to position-based matching
    if not matched_player:
        for p in active_players:
            if p["position"] == position:
                matched_player = p
                break

    if not matched_player:
        return ""

    # Return alt IDs that differ from the LP primary name.
    # Use exact case-insensitive comparison (not fuzzy _names_match) so that
    # variants like "мистермораль" vs "мистер мораль" are kept as alt names.
    alt_parts: list[str] = []
    lp_primary = lp_name or matched_player["id"]
    lp_primary_lower = lp_primary.lower().strip()

    for alt_id in matched_player.get("alt_ids", []):
        if alt_id.lower().strip() != lp_primary_lower:
            alt_parts.append(alt_id)

    return ", ".join(alt_parts)
