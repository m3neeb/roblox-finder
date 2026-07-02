import streamlit as st
import requests
from requests.adapters import HTTPAdapter, Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Verified Roblox Scout", page_icon="🎮", layout="centered")

st.title("⚡ Verified Roblox Scout")
st.caption(
    "Uses Roblox's real games API for visits/creation dates (not the catalog API, "
    "which was returning unrelated data), with retries and graceful fallbacks throughout."
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
    st.divider()
    max_candidates = st.number_input(
        "Max candidates to check", value=250, min_value=10, max_value=2000,
        help="Caps how many games get probed per run, so a run always finishes in a reasonable time."
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


def resolve_universe_id(session, place_id):
    """
    placeId -> universeId using the PUBLIC, no-auth endpoint.
    (games.roblox.com/v1/games/multiget-place-details requires a login cookie and
    will 401 for every single request from a server -- that was the earlier bug.)
    Returns None on any failure; never raises.
    """
    url = f"https://apis.roblox.com/universes/v1/places/{place_id}/universe"
    try:
        res = session.get(url, timeout=6)
        if res.status_code != 200:
            return None
        data = res.json()
        return data.get("universeId")
    except Exception:
        return None


def fetch_games_batch(session, universe_ids):
    """
    universeIds -> real visits / playing / created, in bulk (public, no auth).
    Roblox's batch limit here is flaky above ~40-50 ids, so on a 400 we
    automatically split the batch in half and retry, rather than losing the
    whole batch.
    """
    if not universe_ids:
        return []
    url = "https://games.roblox.com/v1/games"
    try:
        res = session.get(url, params={"universeIds": ",".join(str(u) for u in universe_ids)}, timeout=8)
        if res.status_code == 200:
            return res.json().get("data", []) or []
        if res.status_code == 400 and len(universe_ids) > 1:
            mid = len(universe_ids) // 2
            return (
                fetch_games_batch(session, universe_ids[:mid])
                + fetch_games_batch(session, universe_ids[mid:])
            )
        return []
    except Exception:
        if len(universe_ids) > 1:
            mid = len(universe_ids) // 2
            return (
                fetch_games_batch(session, universe_ids[:mid])
                + fetch_games_batch(session, universe_ids[mid:])
            )
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

    with st.spinner("Pulling active game list from rolimons..."):
        try:
            res = session.get("https://api.rolimons.com/games/v1/gamelist", timeout=8)
        except Exception as e:
            st.error(f"Could not reach rolimons ({e}). This is usually temporary — try again in a moment.")
            return

        if res.status_code != 200:
            st.error(f"Rolimons returned status {res.status_code}. Try again shortly.")
            return

        try:
            games_dict = res.json().get("games", {})
        except Exception:
            st.error("Rolimons returned unreadable data. Try again shortly.")
            return

    candidate_place_ids = []
    for place_id, details in games_dict.items():
        try:
            active_players = int(details[1])
            if min_players <= active_players <= max_players:
                candidate_place_ids.append(int(place_id))
        except Exception:
            continue

    if not candidate_place_ids:
        st.warning("No active games currently sit within your player count range. Try widening it in the sidebar.")
        return

    candidate_place_ids = candidate_place_ids[:max_candidates]
    st.write(f"Checking **{len(candidate_place_ids)}** candidate games against Roblox's official game data...")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)

    matched_games = []
    resolved_count = 0
    failed_count = 0
    checked_count = 0

    progress = st.progress(0.0, text="Scanning...")
    BATCH_SIZE = 25  # resolve + check candidates in adaptive batches, stop early once we have enough matches

    for batch in chunk(candidate_place_ids, BATCH_SIZE):
        # Step 1: resolve universe IDs for this batch (public endpoint, one call per place, threaded)
        universe_for_place = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(resolve_universe_id, session, pid): pid for pid in batch}
            for fut in as_completed(futures):
                pid = futures[fut]
                uid = fut.result()
                if uid:
                    universe_for_place[pid] = uid
                    resolved_count += 1
                else:
                    failed_count += 1

        checked_count += len(batch)
        progress.progress(
            min(checked_count / len(candidate_place_ids), 1.0),
            text=f"Scanned {checked_count}/{len(candidate_place_ids)} games..."
        )

        if not universe_for_place:
            continue

        # Step 2: pull real visits/playing/created for the resolved universe IDs, in bulk
        universe_ids = list(set(universe_for_place.values()))
        games_info = fetch_games_batch(session, universe_ids)
        info_by_universe = {g.get("id"): g for g in games_info if g.get("id")}

        # Step 3: apply real filters
        for pid, uid in universe_for_place.items():
            info = info_by_universe.get(uid)
            if not info:
                continue

            created_date = parse_roblox_datetime(info.get("created"))
            if not created_date or not (cutoff <= created_date <= now):
                continue

            visits = info.get("visits", 0)
            if not (min_visits <= visits <= max_visits):
                continue

            root_place = info.get("rootPlaceId", pid)
            matched_games.append({
                "place_id": str(root_place),
                "title": info.get("name", "Unknown Game"),
                "players": info.get("playing", 0),
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
        st.write(f"Universe IDs resolved: {resolved_count}  |  Failed to resolve: {failed_count}")
        st.write(f"Candidates checked: {checked_count} / {len(candidate_place_ids)}")

    if not matched_games:
        if resolved_count == 0 and failed_count > 0:
            st.error(
                "Every universe-ID lookup failed. This usually means Roblox's public API is "
                "temporarily unreachable from this network, or you're being rate-limited. "
                "Wait a minute and try again — no need to change anything."
            )
        else:
            st.info(
                "No games currently satisfy every filter at once (age, visits, and live players). "
                "This is a genuinely narrow intersection — try widening a filter in the sidebar, "
                "raising 'Max candidates to check', or scanning again shortly."
            )
        return

    # --- Thumbnails (cosmetic only, never fatal) ----------------------------
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
    try:
        run_scan()
    except Exception as e:
        st.error(f"Something unexpected went wrong ({e}). Nothing crashed — just click Run again.")
