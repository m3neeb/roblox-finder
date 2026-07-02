import streamlit as st
import requests
import uuid
from requests.adapters import HTTPAdapter, Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Verified Roblox Scout", page_icon="🎮", layout="centered")

st.title("⚡ Verified Roblox Scout")
st.caption(
    "Sources candidates from Roblox's own Discover/Charts API (real, current games — not a "
    "third-party curated list), then verifies every one against Roblox's official games data."
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    min_players = st.number_input("Min live players", value=20, min_value=0)
    max_players = st.number_input("Max live players", value=2000, min_value=1)
    min_visits = st.number_input("Min total visits", value=750, min_value=0)
    max_visits = st.number_input("Max total visits", value=90000, min_value=1)
    max_age_days = st.number_input("Max age (days)", value=30, min_value=1)
    max_results = st.number_input("Max results", value=20, min_value=1, max_value=100)
    st.divider()
    st.subheader("Candidate sources")
    use_charts = st.checkbox("Roblox Discover/Charts (recommended)", value=True)
    use_rolimons = st.checkbox("Rolimons active-game list (supplementary)", value=True)
    max_rolimons_candidates = st.number_input(
        "Max rolimons candidates to check", value=200, min_value=10, max_value=1500,
        help="Rolimons requires one lookup call per game, so this is capped to keep runs fast."
    )

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def make_session():
    s = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retries, pool_maxsize=20))
    s.headers.update(HEADERS)
    return s


def chunk(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def parse_roblox_datetime(s):
    if not s:
        return None
    try:
        clean = s.split(".")[0].replace("Z", "")
        return datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def first_int(d, keys):
    """Return the first present, int-coercible value among the given keys."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return None


# ---------------------------------------------------------------------------
# Source 1: Roblox's own Discover/Charts backend (real, current catalog)
# ---------------------------------------------------------------------------
def get_chart_sorts(session, session_id):
    """
    Discover the available chart categories (Popular, genres, etc). Response shape
    isn't officially documented, so we parse defensively and accept several possible
    wrapper keys rather than assuming one exact schema.
    """
    url = "https://apis.roblox.com/explore-api/v1/get-sorts"
    try:
        res = session.get(url, params={"sessionId": session_id, "device": "computer", "country": "us"}, timeout=8)
        if res.status_code != 200:
            return []
        data = res.json()
        for key in ("sorts", "Sorts", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def get_sort_content(session, session_id, sort_id):
    url = "https://apis.roblox.com/explore-api/v1/get-sort-content"
    try:
        res = session.get(
            url,
            params={"sessionId": session_id, "sortId": sort_id, "device": "computer", "country": "us"},
            timeout=8,
        )
        if res.status_code != 200:
            return []
        data = res.json()
        for key in ("games", "Games", "data", "contents", "tiles"):
            if isinstance(data.get(key), list):
                return data[key]
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def collect_chart_universe_ids(session, status_placeholder):
    """
    Pull candidates from every 'games' chart category Roblox exposes on Discover.
    Each tile's underlying identifier is treated as a universe ID (that's the
    convention Roblox's own game tiles use); we verify everything downstream
    against the official games API regardless, so a wrong guess here just yields
    zero matches for that item rather than a bad result.
    """
    session_id = str(uuid.uuid4())
    sorts = get_chart_sorts(session, session_id)
    if not sorts:
        return set(), 0

    game_sort_ids = []
    for s in sorts:
        if not isinstance(s, dict):
            continue
        content_type = str(s.get("contentType") or s.get("ContentType") or "").lower()
        sort_id = s.get("sortId") or s.get("SortId") or s.get("id")
        if sort_id is None:
            continue
        if content_type in ("", "game", "games"):
            game_sort_ids.append(sort_id)

    if not game_sort_ids:
        return set(), 0

    universe_ids = set()
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(get_sort_content, session, session_id, sid): sid for sid in game_sort_ids}
        done = 0
        for fut in as_completed(futures):
            items = fut.result()
            for item in items:
                if not isinstance(item, dict):
                    continue
                uid = first_int(item, ["universeId", "UniverseId", "id", "contentId", "ContentId"])
                if uid:
                    universe_ids.add(uid)
            done += 1
            status_placeholder.write(f"Scanned {done}/{len(game_sort_ids)} Discover categories, "
                                      f"{len(universe_ids)} unique games found so far...")

    return universe_ids, len(game_sort_ids)


# ---------------------------------------------------------------------------
# Source 2: Rolimons (supplementary; requires per-game universe resolution)
# ---------------------------------------------------------------------------
def resolve_universe_id(session, place_id):
    url = f"https://apis.roblox.com/universes/v1/places/{place_id}/universe"
    try:
        res = session.get(url, timeout=6)
        if res.status_code != 200:
            return None
        return res.json().get("universeId")
    except Exception:
        return None


def collect_rolimons_universe_ids(session, cap):
    try:
        res = session.get("https://api.rolimons.com/games/v1/gamelist", timeout=8)
        if res.status_code != 200:
            return set(), 0, 0
        games_dict = res.json().get("games", {})
    except Exception:
        return set(), 0, 0

    place_ids = []
    for pid, details in games_dict.items():
        try:
            place_ids.append(int(pid))
        except Exception:
            continue
    place_ids = place_ids[:cap]

    universe_ids = set()
    failed = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(resolve_universe_id, session, pid): pid for pid in place_ids}
        for fut in as_completed(futures):
            uid = fut.result()
            if uid:
                universe_ids.add(uid)
            else:
                failed += 1

    return universe_ids, len(place_ids), failed


# ---------------------------------------------------------------------------
# Verification against Roblox's official games API (authoritative, always used)
# ---------------------------------------------------------------------------
def fetch_games_batch(session, universe_ids):
    if not universe_ids:
        return []
    url = "https://games.roblox.com/v1/games"
    try:
        res = session.get(url, params={"universeIds": ",".join(str(u) for u in universe_ids)}, timeout=8)
        if res.status_code == 200:
            return res.json().get("data", []) or []
        if res.status_code == 400 and len(universe_ids) > 1:
            mid = len(universe_ids) // 2
            return fetch_games_batch(session, universe_ids[:mid]) + fetch_games_batch(session, universe_ids[mid:])
        return []
    except Exception:
        if len(universe_ids) > 1:
            mid = len(universe_ids) // 2
            return fetch_games_batch(session, universe_ids[:mid]) + fetch_games_batch(session, universe_ids[mid:])
        return []


def fetch_thumbnails(session, place_ids):
    if not place_ids:
        return {}
    try:
        res = session.get(
            "https://thumbnails.roblox.com/v1/places/icons",
            params={
                "placeIds": ",".join(place_ids),
                "returnPolicy": "PlaceIcon",
                "size": "150x150",
                "format": "Png",
                "isCircular": "false",
            },
            timeout=8,
        )
        if res.status_code != 200:
            return {}
        return {str(i.get("targetId")): i.get("imageUrl") for i in res.json().get("data", [])}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_scan():
    session = make_session()
    all_universe_ids = set()

    if use_charts:
        with st.spinner("Pulling Roblox's own Discover/Charts catalog..."):
            status = st.empty()
            chart_ids, n_sorts = collect_chart_universe_ids(session, status)
            status.empty()
        st.write(f"📊 Discover/Charts: **{len(chart_ids)}** candidate games from {n_sorts} categories.")
        all_universe_ids |= chart_ids

    rolimons_checked = rolimons_failed = 0
    if use_rolimons:
        with st.spinner("Pulling rolimons' tracked game list as a supplementary source..."):
            rolimons_ids, rolimons_checked, rolimons_failed = collect_rolimons_universe_ids(
                session, max_rolimons_candidates
            )
        st.write(f"📋 Rolimons: **{len(rolimons_ids)}** resolved out of {rolimons_checked} checked.")
        all_universe_ids |= rolimons_ids

    if not all_universe_ids:
        st.error(
            "Couldn't get candidates from either source right now — this looks like a network "
            "or availability issue on Roblox's / rolimons' side, not a filter problem. Try again shortly."
        )
        return

    st.write(f"Verifying **{len(all_universe_ids)}** unique games against Roblox's official data...")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)
    all_universe_ids = list(all_universe_ids)

    matched_games = []
    checked = 0
    progress = st.progress(0.0, text="Verifying...")

    for batch in chunk(all_universe_ids, 40):
        games_info = fetch_games_batch(session, batch)
        checked += len(batch)
        progress.progress(min(checked / len(all_universe_ids), 1.0), text=f"Verified {checked}/{len(all_universe_ids)}...")

        for info in games_info:
            created_date = parse_roblox_datetime(info.get("created"))
            if not created_date or not (cutoff <= created_date <= now):
                continue

            visits = info.get("visits", 0)
            if not (min_visits <= visits <= max_visits):
                continue

            playing = info.get("playing", 0)
            if not (min_players <= playing <= max_players):
                continue

            root_place = info.get("rootPlaceId")
            if not root_place:
                continue

            matched_games.append({
                "place_id": str(root_place),
                "title": info.get("name", "Unknown Game"),
                "players": playing,
                "visits": visits,
                "created": created_date.strftime("%b %d, %Y"),
                "link": f"https://www.roblox.com/games/{root_place}/",
            })

            if len(matched_games) >= max_results:
                break

        if len(matched_games) >= max_results:
            break

    progress.empty()

    with st.expander("Scan diagnostics"):
        st.write(f"Total unique candidates verified: {len(all_universe_ids)}")
        if use_rolimons:
            st.write(f"Rolimons: {rolimons_checked} checked, {rolimons_failed} failed to resolve")

    if not matched_games:
        st.info(
            "No games currently satisfy every filter at once (age, visits, and live players). "
            "Try widening a filter in the sidebar, or check more rolimons candidates — the intersection "
            "of 'brand new' + a specific visit band + a specific live-player band is inherently narrow "
            "at any given moment, so an empty result is a real answer, not necessarily a bug."
        )
        return

    thumb_map = fetch_thumbnails(session, [g["place_id"] for g in matched_games])

    st.success(f"Found {len(matched_games)} verified games matching your criteria.")
    st.divider()

    for idx, game in enumerate(matched_games, 1):
        thumbnail = thumb_map.get(game["place_id"])
        col1, col2 = st.columns([1, 3])
        with col1:
            if thumbnail:
                st.image(thumbnail, width=100)
            else:
                st.write("🎮")
        with col2:
            st.subheader(f"{idx}. {game['title']}")
            st.write(f"📅 **Creation Date:** {game['created']}")
            st.write(f"👥 **Live Players:** {game['players']:,} | 📈 **Total Visits:** {game['visits']:,}")
            st.markdown(f"[👉 Click to Play Game]({game['link']})")
        st.divider()


if st.button("🚀 Run Live Scan", type="primary"):
    if not use_charts and not use_rolimons:
        st.warning("Enable at least one candidate source in the sidebar.")
    else:
        try:
            run_scan()
        except Exception as e:
            st.error(f"Something unexpected went wrong ({e}). Nothing crashed — just click Run again.")
