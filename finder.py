import streamlit as st
import requests

# Set up the web page title and icon
st.set_page_config(page_title="Roblox Game Finder", page_icon="🎮", layout="centered")

st.title("🎮 Roblox Game Finder")
st.write("Finds 20 games with 200–2k concurrent players.")

# Add a prominent "Search" button
if st.button("🚀 Find Games Now", type="primary"):
    with st.spinner("Scanning active games database..."):
        gamelist_url = "https://api.rolimons.com/games/v1/gamelist"
        
        try:
            response = requests.get(gamelist_url, timeout=10)
            if response.status_code != 200:
                st.error(f"Failed to fetch games list: HTTP {response.status_code}")
            else:
                data = response.json()
                games_dict = data.get("games", {})
                matched_games = []
                
                # Filter logic
                for place_id, details in games_dict.items():
                    # Safely extract and convert stats to prevent type mismatches
                    try:
                        title = str(details[0])
                        active_players = int(details[1])
                    except (ValueError, TypeError, IndexError):
                        continue # Skip this game if the data format is corrupted or missing
                    
                    # Target concurrent player range (Reliably parsed as an integer)
                    if 200 <= active_players <= 2000:
                        matched_games.append({
                            "place_id": place_id,
                            "title": title,
                            "players": active_players,
                            "link": f"https://www.roblox.com/games/{place_id}/"
                        })
                        
                        if len(matched_games) >= 20:
                            break
                
                if not matched_games:
                    st.warning("No games matched your specific player thresholds right now. Try again later!")
                else:
                    # Fetch thumbnails in a batch from official Roblox API
                    universe_ids = [g["place_id"] for g in matched_games]
                    thumb_url = f"https://thumbnails.roblox.com/v1/places/icons?placeIds={','.join(universe_ids)}&returnPolicy=PlaceIcon&size=150x150&format=Png&isCircular=false"
                    
                    thumb_map = {}
                    thumb_res = requests.get(thumb_url, timeout=10)
                    if thumb_res.status_code == 200:
                        thumb_data = thumb_res.json().get("data", [])
                        for item in thumb_data:
                            thumb_map[str(item.get("targetId"))] = item.get("imageUrl")
                    
                    st.success(f"Found {len(matched_games)} matching games!")
                    st.divider()
                    
                    # Display the games in a clean GUI layout
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
                            st.write(f"👥 **Players:** {game['players']:,}")
                            st.markdown(f"[👉 Click Here to Play Game]({game['link']})")
                        
                        st.divider()
                        
        except Exception as e:
            st.error(f"An error occurred: {e}")
