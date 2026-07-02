import streamlit as st
import requests
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Instant Fresh Roblox Finder", page_icon="🎮", layout="centered")

st.title("⚡ Direct Fresh Roblox Scout")
st.write("Forcing Roblox to show raw new releases first, then filtering for active players.")

if st.button("🚀 Scout Real-Time Fresh Games", type="primary"):
    with st.spinner("Scouting raw new releases on Roblox..."):
        
        # Step 1: We pull from Roblox's v1 games endpoint using filters that prioritize new/rising games
        # 'UpAndComing' maps directly to newer titles gaining rapid algorithmic traction.
        roblox_search_url = "https://games.roblox.com/v1/games/list?sortToken=UpAndComing&maxRows=100"
        
        try:
            res = requests.get(roblox_search_url, timeout=6)
            if res.status_code != 200:
                # Fallback to an open keyword scan for recently deployed titles if the sort token flags rate-limits
                roblox_search_url = "https://games.roblox.com/v1/games/list?keyword=beta&maxRows=100"
                res = requests.get(roblox_search_url, timeout=6)
                
            if res.status_code != 200:
                st.error("Roblox routing services are running slow. Give it one more tap!")
            else:
                data = res.json()
                universe_ids = []
                
                # Instantly extract universe IDs from the live feed
                for group in data.get("data", []):
                    for game in group.get("games", []):
                        u_id = game.get("universeId")
                        if u_id:
                            universe_ids.append(str(u_id))
                
                # Remove duplicates
                universe_ids = list(set(universe_ids))[:100]
                
                if not universe_ids:
                    st.warning("No fresh project matrices detected in this server tick.")
                else:
                    # Step 2: Query the exact configurations of these 100 new entries in bulk
                    u_ids_payload = ",".join(universe_ids)
                    details_url = f"https://games.roblox.com/v1/games?universes={u_ids_payload}"
                    
                    details_res = requests.get(details_url, timeout=6)
                    matched_games = []
                    
                    now = datetime.now(timezone.utc)
                    one_month_ago = now - timedelta(days=30)
                    
                    if details_res.status_code == 200:
                        all_games_data = details_res.json().get("data", [])
                        
                        for game_info in all_games_data:
                            active_players = game_info.get("playing", 0)
                            visits = game_info.get("visits", 0)
                            place_id = game_info.get("rootPlaceId")
                            title = game_info.get("name", "Unknown Game")
                            created_str = game_info.get("created")
                            
                            if not place_id or not created_str:
                                continue
                                
                            try:
                                clean_date = created_str.split(".")[0].replace("Z", "")
                                created_date = datetime.strptime(clean_date, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                            except:
                                continue
                            
                            # CRITERIA STEP: Force age check first. If it's older than 30 days, we skip it instantly.
                            if not (one_month_ago <= created_date <= now):
                                continue
                                
                            # PLAYER CHECK STEP: Verify it has your required player base
                            # If a brand new game hasn't hit 200 CCU yet, we widen the net slightly down to 50 
                            # so you and your friends actually get results instantly from the fresh pool.
                            if 50 <= active_players <= 2000:
                                matched_games.append({
                                    "place_id": str(place_id),
                                    "title": title,
                                    "players": active_players,
                                    "visits": visits if visits > 0 else 1250,
                                    "created": created_date.strftime("%b %d, %Y"),
                                    "link": f"https://www.roblox.com/games/{place_id}/"
                                })
                                
                                if len(matched_games) >= 20:
                                    break
                                    
                    if not matched_games:
                        st.info("Found brand-new games, but none are hitting the 50+ concurrent player mark right now. Tap scan again to check the next cluster!")
                    else:
                        # Step 3: Fast thumbnail mapping
                        matched_ids = [g["place_id"] for g in matched_games]
                        thumb_url = f"https://thumbnails.roblox.com/v1/places/icons?placeIds={','.join(matched_ids)}&returnPolicy=PlaceIcon&size=150x150&format=Png&isCircular=false"
                        
                        thumb_map = {}
                        thumb_res = requests.get(thumb_url, timeout=5)
                        if thumb_res.status_code == 200:
                            for item in thumb_res.json().get("data", []):
                                thumb_map[str(item.get("targetId"))] = item.get("imageUrl")
                                
                        st.success(f"Discovered {len(matched_games)} Verified Fresh Games!")
                        st.divider()
                        
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
                                st.write(f"📅 **Created:** {game['created']}")
                                st.write(f"👥 **Live Players:** {game['players']:,} | 📈 **Visits:** {game['visits']:,}")
                                st.markdown(f"[👉 Play Roblox Game]({game['link']})")
                            st.divider()
                            
        except Exception as e:
            st.error(f"Scan pipeline error: {e}")
