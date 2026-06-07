#!/usr/bin/env python3
"""One-time OAuth setup. Run this on Mac before deploying to Pi."""
from dotenv import load_dotenv
load_dotenv()

import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import CacheFileHandler
from pathlib import Path

CACHE_PATH = Path(__file__).parent / "shared" / ".spotify_cache"
SCOPE = "playlist-read-private"

auth_manager = SpotifyOAuth(
    client_id=os.environ["SPOTIPY_CLIENT_ID"],
    client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
    redirect_uri=os.environ["SPOTIPY_REDIRECT_URI"],
    scope=SCOPE,
    cache_handler=CacheFileHandler(cache_path=str(CACHE_PATH)),
    open_browser=True,
)

sp = spotipy.Spotify(auth_manager=auth_manager)
user = sp.current_user()
print(f"Authenticated as: {user['display_name']} ({user['id']})")
print(f"Token cached at: {CACHE_PATH}")
