# %%
from dotenv import load_dotenv

load_dotenv()
from shared.spotify_auth import get_spotify_client

sp = get_spotify_client("playlist-read-private")

# %%
all_playlists = []
results = sp.current_user_playlists(limit=50)
while True:
    all_playlists.extend(results["items"])
    if results["next"] is None:
        break
    results = sp.next(results)

print(f"Total playlists: {len(all_playlists)}")
for p in all_playlists:
    print(f"{p['owner']['id']:30} {p['name']}")

# %%
