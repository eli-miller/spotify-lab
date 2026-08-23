#!/usr/bin/env python3
"""Cell-by-cell sandbox for poking at the Spotify Web API by hand.

Run in VS Code's Python Interactive mode (each `# %%` block is its own cell).
Nothing here writes files or touches production state — just print/inspect.
"""
# %% Setup — auth + imports
import sys
import json
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.spotify_auth import get_spotify_client
import spotipy

# Swap to a friend's cached token instead of your own — matches the --cache
# convention in new_releases.py. Set to None to use your own default cache.
CACHE = str(Path(__file__).parent.parent / "shared" / ".spotify_cache_tucker")
# CACHE = None

SCOPE = "user-follow-read"
sp = get_spotify_client(SCOPE, cache_path=CACHE)

me = sp._get("me")
print(f"Authenticated as {me.get('display_name')} ({me['id']})")

# %% Raw response: first page of followed artists
# sp._get bypasses spotipy's high-level wrapper methods and hits the endpoint
# directly — same pattern used everywhere in this project (see CLAUDE.md).
raw = sp._get("me/following", type="artist", limit=5)
print(json.dumps(raw, indent=2))

# %% Pull the pieces out of that response by hand
artists = raw["artists"]["items"]
for a in artists:
    print(a["name"], "-", a["id"])

cursor = raw["artists"]["cursors"]["after"]
print("\nnext cursor:", cursor)

# %% Manually paginate one page forward using that cursor
raw2 = sp._get("me/following", type="artist", limit=5, after=cursor)
print(json.dumps(raw2["artists"]["cursors"], indent=2))

# %% Pick one artist and look at their albums
artist_id = artists[0]["id"]
albums_raw = sp._get(f"artists/{artist_id}/albums", include_groups="album", limit=10)
print(json.dumps(albums_raw, indent=2))

# %% Single artist fetch — compare to the batch call below.
# CLAUDE.md notes this response is stripped in Dev Mode: no genres,
# popularity, or followers. See for yourself:
artist_raw = sp._get(f"artists/{artist_id}")
print(json.dumps(artist_raw, indent=2))

# %% Batch artist fetch — this one is documented as 403 in Dev Mode.
# Trigger it yourself and inspect the real exception shape.
try:
    sp.artists([artist_id])
except spotipy.SpotifyException as e:
    print("http_status:", e.http_status)
    print("msg:", e.msg)
    print("headers:", dict(e.headers or {}))

# %% Playlist items — the /items vs /tracks quirk from CLAUDE.md.
# sp.playlist_items() calls the deprecated /tracks endpoint (403 in Dev Mode).
# Calling /items directly works, but the response shape is different:
# track data lives under item["item"], not item["track"].
SHAZAM_PLAYLIST_ID = "7DS6WcZdNiykC0BvWlt0Ul"
items_raw = sp._get(f"playlists/{SHAZAM_PLAYLIST_ID}/items", limit=3)
print(json.dumps(items_raw["items"][0], indent=2))

# %% (Optional, costs real requests) Trigger a 429 on purpose to see the
# headers Spotify actually sends back. Only uncomment if you want to burn
# some quota to see it firsthand — retries=0 is set on this client so it'll
# surface immediately instead of urllib3 silently sleeping.
# for i in range(50):
#     try:
#         sp._get(f"artists/{artist_id}/albums", limit=1)
#     except spotipy.SpotifyException as e:
#         print("Hit 429 after", i, "calls. Retry-After:", e.headers.get("Retry-After"))
#         break
