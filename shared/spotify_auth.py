import os
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import CacheFileHandler

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_CACHE = _REPO_ROOT / "shared" / ".spotify_cache"


def get_spotify_client(scope: str, cache_path: str | None = None) -> spotipy.Spotify:
    """Return an authenticated Spotify client using a cached OAuth token."""
    resolved_cache = str(cache_path) if cache_path else str(_DEFAULT_CACHE)
    auth_manager = SpotifyOAuth(
        client_id=os.environ["SPOTIPY_CLIENT_ID"],
        client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
        redirect_uri=os.environ["SPOTIPY_REDIRECT_URI"],
        scope=scope,
        cache_handler=CacheFileHandler(cache_path=resolved_cache),
        open_browser=False,
    )
    # retries=0 disables urllib3's built-in retry-on-429 behavior, which would
    # otherwise silently sleep for the full Retry-After duration (up to 24h).
    # Our own _get_with_retry handles 429s explicitly instead.
    return spotipy.Spotify(auth_manager=auth_manager, retries=0)
