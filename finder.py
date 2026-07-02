import streamlit as st
import requests
from requests.adapters import HTTPAdapter, Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Verified Roblox Scout", page_icon="🎮", layout="centered")

st.title("⚡ Verified Roblox Scout")
st.write(
    "Uses Roblox's own games API (not the catalog API) for real visit counts and "
    "real creation dates, so results are actually accurate."
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    min_players = st.number_input("Min live players", value=200, min_value=0)
    max_players = st.number_input("Max live players", value=2000, min_value=1)
    min_visits = st.number_input("Min total visits", value=750, min_value=0)
    max_visits = st.number_input("Max total visits", value=90000, min_value=1)
    max_age_days = st.number_input("Max age (days)", value=30, min_value=1)
    max_results = st.number_input("Max results", value=20, min_value=1, max_value=100)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def make_session():
    s = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
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


def fetch_place_details_batch(session, place_ids):
    """placeId -> universeId, via the bulk multiget endpoint (correct, official)."""
    url = "https://games.roblox.com/v1/games/multiget-place-details"
    try:
        res = session.get(url, params={"placeIds": ",".join(str(p) for p in place_ids)}, timeout=8)
        if res.status_code != 200:
            return []
        return res.json() or []
    except Exception:
        return []


def fetch_games_batch(session, universe_ids):
    """universeId -> real visits / playing / created, via the official games endpoint."""
    url = "https://games.roblox.com/v1/games"
    try:
        res = session.get(url, params={"universeIds": ",".join(str(u) for u in universe_ids)}, timeout=8)
        if res.status_code != 200:
            return []
        return res.json().get("data", []) or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if st.button("🚀 Run Live Scan", type="primary"):
    session = make_session()

    with st.spinner("Pulling active game list..."):
        try:
            res = session.get("https://api.rolimons.com/games/v1/gamelist", timeout=8)
        except Exception as e:
            st.error(f"Could not reach rolimons: {e}")
            st.stop()

        if res.status_code != 200:
            st.error("Data pipeline handshake failed. Try again in a moment.")
            st.stop()

        games_dict = res.json().get("games", {})

    # --- Step 1: filter candidate place IDs by live player count -----------
    candidate_place_ids = []
    for place_id, details in games_dict.items():
        try:
            active_players = int(details[1])
            if min_players <= active_players <= max_players:
                candidate_place_ids.append(int(place_id))
        except Exception:
            continue

    if not candidate_place_ids:
        st.warning("No active games currently sit within your player count range.")
        st.stop()

    st.write(f"Found **{len(candidate_place_ids)}** candidate games in the player range. Verifying against Roblox's official game data...")

    # --- Step 2: placeId -> universeId, in bulk, in parallel ---------------
    place_batches = list(chunk(candidate_place_ids, 100))
    universe_map = {}   # placeId -> universeId
    progress = st.progress(0.0, text="Resolving universe IDs...")

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_place_details_batch, session, b): b for b in place_batches}
        done = 0
        for fut in as_completed(futures):
            for item in fut.result():
                pid = item.get("placeId")
                uid = item.get("universeId")
                if pid and uid:
                    universe_map[pid] = uid
            done += 1
            progress.progress(done / len(place_batches), text="Resolving universe IDs...")

    if not universe_map:
        st.error("Could not resolve any universe IDs right now. Roblox's API may be rate-limiting — try again shortly.")
        st.stop()

    # --- Step 3: universeId -> real visits/playing/created, in bulk --------
    universe_ids = list(set(universe_map.values()))
    universe_batches = list(chunk(universe_ids, 100))
    game_data = {}  # universeId -> game info dict
    progress2 = st.progress(0.0, text="Fetching verified game data...")

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_games_batch, session, b): b for b in universe_batches}
        done = 0
        for fut in as_completed(futures):
            for item in fut.result():
                uid = item.get("id")
                if uid:
                    game_data[uid] = item
            done += 1
            progress2.progress(done / len(universe_batches), text="Fetching verified game data...")

    # --- Step 4: apply real filters (creation date + visits) ---------------
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)
    matched_games = []

    for place_id in candidate_place_ids:
        uid = universe_map.get(place_id)
        if uid is None:
            continue
        info = game_data.get(uid)
        if not info:
            continue

        created_date = parse_roblox_datetime(info.get("created"))
        if not created_date or not (cutoff <= created_date <= now):
            continue

        visits = info.get("visits", 0)
        if not (min_visits <= visits <= max_visits):
            continue

        matched_games.append({
            "place_id": str(info.get("rootPlaceId", place_id)),
            "title": info.get("name", "Unknown Game"),
            "players": info.get("playing", 0),
            "visits": visits,
            "created": created_date.strftime("%b %d, %Y"),
            "link": f"https://www.roblox.com/games/{info.get('rootPlaceId', place_id)}/",
        })

        if len(matched_games) >= max_results:
            break

    if not matched_games:
        st.info(
            "No games currently satisfy every filter at once (age, visits, and live players). "
            "This is a genuinely narrow intersection — try widening a filter in the sidebar or scanning again shortly."
        )
        st.stop()

    # --- Step 5: thumbnails, bulk ------------------------------------------
    final_ids = [g["place_id"] for g in matched_games]
    thumb_map = {}
    try:
        thumb_res = session.get(
            "https://thumbnails.roblox.com/v1/places/icons",
            params={
                "placeIds": ",".join(final_ids),
                "returnPolicy": "PlaceIcon",
                "size": "150x150",
                "format": "Png",
                "isCircular": "false",
            },
            timeout=8,
        )
        if thumb_res.status_code == 200:
            for item in thumb_res.json().get("data", []):
                thumb_map[str(item.get("targetId"))] = item.get("imageUrl")
    except Exception:
        pass  # thumbnails are cosmetic; don't fail the whole run over them

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
