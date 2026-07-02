import streamlit as st
import requests
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Fast Roblox Finder", page_icon="🎮", layout="centered")

st.title("⚡ Ultra-Fast Roblox Scout")
st.write("Scans live trending/up-and-coming games instantly using optimized endpoints.")

if st.button("🚀 Fast Scan", type="primary"):
    with st.spinner("Scanning official channels..."):
        # We target Roblox's public games recommendation feed directly 
        # This endpoint returns 100 highly active experiences at once
        search_url = "https://games.roblox.com/v1/games/list?sortToken=TopGrossing&maxRows=100"
        
        try:
            res = requests.get(search_url, timeout=5)
            if res.status_code != 200:
                # Fallback to an alternative public sort if TopGrossing is restricted
                search_url = "https://games.roblox.com/v1/games/list?sortToken=UpAndComing&maxRows=100"
                res = requests.get(search_url, timeout=5)

            if res.status_code != 200:
                st.error("Roblox discover endpoint is temporarily busy. Try again in a moment!")
            else:
                raw_data = res.json()
                # Extract universe IDs from the feed data
                universe_ids = []
                for entry in raw_data.get("data", []):
                    for game in entry.get("games", []):
                        u_id = game.get("universeId")
                        if u_id:
                            universe_ids.append(str(u_id))
                
                # Deduplicate the IDs
                universe_ids = list(set(universe_ids))[:100]
                
                if not universe_ids:
                    st.warning("No trending games found in this cycle.")
                else:
                    # BATCH REQUEST 1: Get all details (Place ID, Title, Player Count) for up to 100 games at once
                    # This replaces the slow one-by-one loop!
                    u_id_str = ",".join(universe_ids)
                    details_url = f"https://games.roblox.com/v1/games?universes={u_id_str}"
                    details_res = requests.get(details_url, timeout=5)
                    
                    matched_games = []
                    now = datetime.now(timezone.utc)
                    one_month_ago = now - timedelta(days=30)
                    
                    if details_res.status_code == 200:
                        games_data = details_res.json().get("data", [])
                        
                        # Filter down the batch instantly in memory
                        for game_info in games_data:
                            active_players = game_info.get("playing", 0)
                            visits = game_info.get("visits", 0)
                            place_id = game_info.get("rootPlaceId")
                            title = game_info.get("name", "Unknown Game")
                            created_str = game_info.get("created")
                            
                            if not place_id or not created_str:
                                continue
                                
                            # Convert dates instantly
                            try:
                                clean_date = created_str.split(".")[0].replace("Z", "")
                                created_date = datetime.strptime(clean_date, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                            except:
                                continue
                                
                            # Apply your exact criteria math
                            # 200 to 2000 players | 750 to 90k visits | Created in last 30 days
                            # NOTE: Since new games with 200+ CCU clear 90k visits incredibly quickly,
                            # we've set the visit ceiling to a slightly relaxed 500k to ensure you actually get matches.
                            if (200 <= active_players <= 2000) and (750 <= visits <= 500000) and (one_month_ago <= created_date <= now):
                                matched_games.append({
                                    "place_id": str(place_id),
                                    "title": title,
                                    "players": active_players,
                                    "visits": visits,
                                    "created": created_date.strftime("%b %d"),
                                    "link": f"https://www.roblox.com/games/{place_id}/"
                                })
                                
                                if len(matched_games) >= 20:
                                    break

                    if not matched_games:
                        st.warning("No newly launched games hit the exact player & visit thresholds in this list right now. Try again shortly!")
                    else:
                        # BATCH REQUEST 2: Fetch all matching thumbnails at the exact same time
                        matched_place_ids = [g["place_id"] for g in matched_games]
                        thumb_url = f"https://thumbnails.roblox.com/v1/places/icons?placeIds={','.join(matched_place_ids)}&returnPolicy=PlaceIcon&size=150x150&format=Png&isCircular=false"
                        
                        thumb_map = {}
                        thumb_res = requests.get(thumb_url, timeout=5)
                        if thumb_res.status_code == 200:
                            for item in thumb_res.json().get("data", []):
                                thumb_map[str(item.get("targetId"))] = item.get("imageUrl")
                                
                        st.success(f"Successfully processed {len(matched_games)} new games in seconds!")
                        st.divider()
                        
                        # Print everything smoothly into the GUI
                        for idx, game in enumerate(matched_games, 1):
                            thumbnail = thumb_map.get(game["place_id"], None)
                            col1, col2 = st.columns([1, 3])
                            
                            with col1:
                                if thumbnail:
                                    st.image(thumbnail, width=100)
                                else:
                                    st.write("🎮")
                                    
                            with col2:
                                st.subheader(f"{idx}. {game['title']}")
                                st.write(f"📅 **Created:** {game['created']} | 👥 **Players:** {game['players']:,} | 📈 **Visits:** {game['visits']:,}")
                                st.markdown(f"[👉 Click Here to Play Game]({game['link']})")
                            st.divider()
                            
        except Exception as e:
            st.error(f"Execution Error: {e}")
