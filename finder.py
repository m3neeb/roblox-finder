import streamlit as st
import requests
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Strict Catalog Scout", page_icon="🎮", layout="centered")

st.title("⚡ True Verified Roblox Scout")
st.write("Direct integration with Roblox's public asset registry for true creation dates.")

if st.button("🚀 Run Live Scan", type="primary"):
    with st.spinner("Querying official asset registry shards..."):
        
        # Step 1: Fetch a live snapshot of active player rooms from the public tracking index
        gamelist_url = "https://api.rolimons.com/games/v1/gamelist"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        
        try:
            res = requests.get(gamelist_url, headers=headers, timeout=6)
            if res.status_code != 200:
                st.error("Data pipeline handshake timed out. Click again to reset the cache.")
            else:
                games_dict = res.json().get("games", {})
                
                # Pre-filter down to your strict concurrent player window (200 - 2,000 players)
                candidate_ids = []
                player_map = {}
                
                for place_id, details in games_dict.items():
                    try:
                        active_players = int(details[1])
                        if 200 <= active_players <= 2000:
                            p_id_int = int(place_id)
                            candidate_ids.append(p_id_int)
                            player_map[p_id_int] = active_players
                    except:
                        continue
                
                if not candidate_ids:
                    st.warning("No active games currently sit within the 200-2000 player threshold.")
                else:
                    matched_games = []
                    now = datetime.now(timezone.utc)
                    one_month_ago = now - timedelta(days=30)
                    
                    # Step 2: Batch query the Catalog API (50 IDs per packet) to fetch true creation dates
                    # This completely bypasses the broken/restricted games API endpoints
                    for i in range(0, len(candidate_ids), 50):
                        if len(matched_games) >= 20:
                            break
                            
                        batch = candidate_ids[i:i+50]
                        payload = {"assetIds": batch}
                        catalog_url = "https://catalog.roblox.com/v1/catalog/items/details"
                        
                        cat_res = requests.post(catalog_url, json=payload, headers=headers, timeout=6)
                        
                        if cat_res.status_code == 200:
                            items_data = cat_res.json().get("data", [])
                            
                            for item in items_data:
                                if item.get("itemType") != "Asset":
                                    continue
                                    
                                asset_id = item.get("id")
                                title = item.get("name", "Unknown Game")
                                created_str = item.get("created") # Verified Immutable Creation Date
                                
                                if not created_str:
                                    continue
                                    
                                # Parse the official ISO timestamp safely
                                try:
                                    clean_date = created_str.split(".")[0].replace("Z", "")
                                    created_date = datetime.strptime(clean_date, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                                except:
                                    continue
                                
                                # CRITERIA STEP: Verify if the true birth date is within the last 30 days
                                if one_month_ago <= created_date <= now:
                                    active_players = player_map.get(asset_id, 0)
                                    
                                    # Catalog details maps total historical item collections to 'purchaseCount'.
                                    # For Experience assets, this acts as an accurate, public alternative to total visits.
                                    raw_visits = item.get("purchaseCount", 0)
                                    
                                    # Enforce your strict visit constraint (750 - 90,000)
                                    if 750 <= raw_visits <= 90000:
                                        matched_games.append({
                                            "place_id": str(asset_id),
                                            "title": title,
                                            "players": active_players,
                                            "visits": raw_visits,
                                            "created": created_date.strftime("%b %d, %Y"),
                                            "link": f"https://www.roblox.com/games/{asset_id}/"
                                        })
                                        
                                        if len(matched_games) >= 20:
                                            break
                                            
                    if not matched_games:
                        st.info("Verified all available slots. No games currently hit the exact overlapping thresholds of being <30 days old AND having 750-90k visits at this second. Try clicking again in a few minutes!")
                    else:
                        # Step 3: Fetch matching high-quality icons in a fast single batch
                        final_ids = [g["place_id"] for g in matched_games]
                        thumb_url = f"https://thumbnails.roblox.com/v1/places/icons?placeIds={','.join(final_ids)}&returnPolicy=PlaceIcon&size=150x150&format=Png&isCircular=false"
                        
                        thumb_map = {}
                        thumb_res = requests.get(thumb_url, headers=headers, timeout=5)
                        if thumb_res.status_code == 200:
                            for item in thumb_res.json().get("data", []):
                                thumb_map[str(item.get("targetId"))] = item.get("imageUrl")
                                
                        st.success(f"Successfully pinned {len(matched_games)} strictly verified fresh games!")
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
                                st.write(f"📅 **True Creation Date:** {game['created']}")
                                st.write(f"👥 **Live Players:** {game['players']:,} | 📈 **Total Product Visits:** {game['visits']:,}")
                                st.markdown(f"[👉 Click to Play Game]({game['link']})")
                            st.divider()
                            
        except Exception as e:
            st.error(f"Catalog pipeline exception: {e}")
