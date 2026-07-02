import streamlit as st
import requests
from datetime import datetime, timedelta, timezone

# Set up the web page title and configuration
st.set_page_config(page_title="New Roblox Game Finder", page_icon="🎮", layout="centered")

st.title("🎮 Fresh Roblox Game Finder")
st.write("Scouting games created within the last month matching strict player and visit thresholds.")

if st.button("🚀 Scan & Filter Real-Time Games", type="primary"):
    with st.spinner("Analyzing active global listings & tracking dates..."):
        # Step 1: Grab the live activity dictionary
        gamelist_url = "https://api.rolimons.com/games/v1/gamelist"
        
        try:
            response = requests.get(gamelist_url, timeout=10)
            if response.status_code != 200:
                st.error(f"Failed to fetch master dictionary: HTTP {response.status_code}")
            else:
                games_dict = response.json().get("games", {})
                potential_place_ids = []
                
                # Pre-filter by concurrent players first to find active targets
                for place_id, details in games_dict.items():
                    try:
                        active_players = int(details[1])
                        if 200 <= active_players <= 2000:
                            potential_place_ids.append((place_id, active_players))
                    except (ValueError, TypeError, IndexError):
                        continue
                
                if not potential_place_ids:
                    st.warning("No active games match the player filter right now.")
                else:
                    matched_games = []
                    now = datetime.now(timezone.utc)
                    one_month_ago = now - timedelta(days=30)
                    
                    # Batch lookups in groups of 20 to check official details (Visits & Creation dates)
                    # We continue checking until we hit 20 true matches or run out of candidates
                    for i in range(0, len(potential_place_ids), 20):
                        if len(matched_games) >= 20:
                            break
                            
                        batch = potential_place_ids[i:i+20]
                        batch_ids = [item[0] for item in batch]
                        
                        # Request strict structural details directly from Roblox games endpoint
                        details_url = f"https://games.roblox.com/v1/games/multiget-place-details?placeIds={','.join(batch_ids)}"
                        det_res = requests.get(details_url, timeout=10)
                        
                        if det_res.status_code == 200:
                            details_data = det_res.json()
                            for game_info in details_data:
                                p_id = str(game_info.get("placeId"))
                                title = game_info.get("name", "Unknown Game")
                                
                                # Fetch actual true totals directly reported by Roblox
                                universe_id = game_info.get("universeId")
                                
                                # To protect bandwidth and performance on mobile, we can cross-validate parameters
                                # Roblox stores the structural ISO timestamps on creation dates
                                created_str = game_info.get("created") # Format: "2026-06-15T..."
                                
                                # Fallback dummy assignment if API response strips properties on unauthorized scopes
                                if not created_str:
                                    continue
                                    
                                try:
                                    # Clean up ISO timestamp to standard python datetime
                                    clean_date_str = created_str.split(".")[0].replace("Z", "")
                                    created_date = datetime.strptime(clean_date_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                                except Exception:
                                    continue
                                
                                # Query the Universe data endpoint for exact global visits
                                universe_url = f"https://games.roblox.com/v1/games?universes={universe_id}"
                                uni_res = requests.get(universe_url, timeout=5)
                                visits = 0
                                if uni_res.status_code == 200:
                                    uni_data = uni_res.json().get("data", [])
                                    if uni_data:
                                        visits = uni_data[0].get("visits", 0)
                                
                                # Read player count mapped back from initial tracking dictionary
                                p_count = next(item[1] for item in batch if item[0] == p_id)
                                
                                # Apply the absolute full criteria matrix requested
                                if (one_month_ago <= created_date <= now) and (750 <= visits <= 90000):
                                    matched_games.append({
                                        "place_id": p_id,
                                        "title": title,
                                        "players": p_count,
                                        "visits": visits,
                                        "created": created_date.strftime("%b %d, %Y"),
                                        "link": f"https://www.roblox.com/games/{p_id}/"
                                    })
                                    if len(matched_games) >= 20:
                                        break
                                        
                    if not matched_games:
                        st.warning("No newly created games match both your active player AND visit limits right now.")
                    else:
                        # Grab official thumbnails in bulk
                        u_ids = [g["place_id"] for g in matched_games]
                        thumb_url = f"https://thumbnails.roblox.com/v1/places/icons?placeIds={','.join(u_ids)}&returnPolicy=PlaceIcon&size=150x150&format=Png&isCircular=false"
                        
                        thumb_map = {}
                        thumb_res = requests.get(thumb_url, timeout=10)
                        if thumb_res.status_code == 200:
                            for item in thumb_res.json().get("data", []):
                                thumb_map[str(item.get("targetId"))] = item.get("imageUrl")
                        
                        st.success(f"Successfully tracked {len(matched_games)} brand new games!")
                        st.divider()
                        
                        for idx, game in enumerate(matched_games, 1):
                            thumbnail = thumb_map.get(str(game["place_id"]), None)
                            col1, col2 = st.columns([1, 3])
                            
                            with col1:
                                if thumbnail:
                                    st.image(thumbnail, width=100)
                                else:
                                    st.write("No Image")
                                    
                            with col2:
                                st.subheader(f"{idx}. {game['title']}")
                                st.write(f"📅 **Created:** {game['created']} | 👥 **Players:** {game['players']:,} | 📈 **Total Visits:** {game['visits']:,}")
                                st.markdown(f"[👉 Click Here to Play Game]({game['link']})")
                            st.divider()
                            
        except Exception as e:
            st.error(f"System Error: {e}")
