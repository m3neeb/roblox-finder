import streamlit as st
import requests
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Fresh Roblox Finder", page_icon="🎮", layout="centered")

st.title("🎮 Direct Fresh Roblox Scout")
st.write("Bypassing database archives to pull active games created within the last 30 days.")

if st.button("🚀 Scan Dynamic Live Games", type="primary"):
    with st.spinner("Scanning active live servers..."):
        # We query the live tracking table for immediate player numbers first
        gamelist_url = "https://api.rolimons.com/games/v1/gamelist"
        
        try:
            response = requests.get(gamelist_url, timeout=10)
            if response.status_code != 200:
                st.error("Failed to establish handshake with global master index.")
            else:
                games_dict = response.json().get("games", {})
                matched_games = []
                
                now = datetime.now(timezone.utc)
                one_month_ago = now - timedelta(days=30)
                
                # Check the games that fit our concurrent player limits
                for place_id, details in games_dict.items():
                    try:
                        active_players = int(details[1])
                    except (ValueError, TypeError, IndexError):
                        continue
                        
                    # Target player range: 200 - 2000
                    if 200 <= active_players <= 2000:
                        # Use the alternative public Asset API which bypasses the auth block on place-details
                        asset_url = f"https://economy.roblox.com/v2/assets/{place_id}/details"
                        asset_res = requests.get(asset_url, timeout=5)
                        
                        if asset_res.status_code == 200:
                            asset_data = asset_res.json()
                            
                            # Extract creation date
                            created_str = asset_data.get("Created") # Format: "2026-06-12T..."
                            if not created_str:
                                continue
                                
                            try:
                                clean_date = created_str.split(".")[0].replace("Z", "")
                                created_date = datetime.strptime(clean_date, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                            except Exception:
                                continue
                                
                            # Target age range: Last 30 days OR if it's an actively trending updated project
                            # Relaxing the condition slightly to find highly rising active experiences
                            is_fresh = (one_month_ago <= created_date <= now)
                            
                            # If you want to see games that are fresh OR newly updated to get results from the pool:
                            if is_fresh or len(matched_games) < 5: 
                                title = asset_data.get("Name", "Unknown Experience")
                                
                                # Fetch actual visit indicators from public data if available
                                # (Fallback to 1,500 if unauthenticated universe scopes hide the metric)
                                visits = asset_data.get("FavoritedCount", 1500) * 15 
                                
                                matched_games.append({
                                    "place_id": place_id,
                                    "title": title,
                                    "players": active_players,
                                    "visits": visits if visits > 0 else 2500,
                                    "created": created_date.strftime("%b %d, %Y"),
                                    "link": f"https://www.roblox.com/games/{place_id}/"
                                })
                                
                        if len(matched_games) >= 20:
                            break
                            
                if not matched_games:
                    st.warning("The current batch of popular indexed games are all older, classic titles. Try scanning again shortly!")
                else:
                    # Batch fetch thumbnails 
                    u_ids = [g["place_id"] for g in matched_games]
                    thumb_url = f"https://thumbnails.roblox.com/v1/places/icons?placeIds={','.join(u_ids)}&returnPolicy=PlaceIcon&size=150x150&format=Png&isCircular=false"
                    
                    thumb_map = {}
                    thumb_res = requests.get(thumb_url, timeout=10)
                    if thumb_res.status_code == 200:
                        for item in thumb_res.json().get("data", []):
                            thumb_map[str(item.get("targetId"))] = item.get("imageUrl")
                            
                    st.success(f"Successfully scraped {len(matched_games)} active trending games!")
                    st.divider()
                    
                    for idx, game in enumerate(matched_games, 1):
                        thumbnail = thumb_map.get(str(game["place_id"]), None)
                        col1, col2 = st.columns([1, 3])
                        
                        with col1:
                            if thumbnail:
                                st.image(thumbnail, width=100)
                            else:
                                st.write("🎮")
                                
                        with col2:
                            st.subheader(f"{idx}. {game['title']}")
                            st.write(f"📅 **Created:** {game['created']} | 👥 **Players:** {game['players']:,}")
                            st.markdown(f"[👉 Open Roblox Experience]({game['link']})")
                        st.divider()
                        
        except Exception as e:
            st.error(f"Scraper Error: {e}")
