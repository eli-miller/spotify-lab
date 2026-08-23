#!/usr/bin/env python3
"""Authorize a friend's Spotify account for use with new_releases.py.

Usage:
    python setup_auth_for_friend.py <name>

Example:
    python setup_auth_for_friend.py alice
    -> saves token to shared/.spotify_cache_alice
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
load_dotenv()

from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import CacheFileHandler

SCOPE = "user-follow-read"
REPO_ROOT = Path(__file__).parent

if len(sys.argv) != 2:
    print("Usage: python setup_auth_for_friend.py <name>")
    print("Example: python setup_auth_for_friend.py alice")
    sys.exit(1)

name = sys.argv[1].lower()
cache_path = REPO_ROOT / "shared" / f".spotify_cache_{name}"

auth_manager = SpotifyOAuth(
    client_id=os.environ["SPOTIPY_CLIENT_ID"],
    client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
    redirect_uri=os.environ["SPOTIPY_REDIRECT_URI"],
    scope=SCOPE,
    cache_handler=CacheFileHandler(cache_path=str(cache_path)),
    open_browser=False,
)

auth_url = auth_manager.get_authorize_url()

print(f"\n=== Authorizing {name} ===\n")
print(f"Send them this URL (works in any browser, no install needed):\n")
print(f"  {auth_url}\n")
print("Tell them to:")
print("  1. Open the link")
print("  2. Log into Spotify if prompted, then click Allow")
print("  3. The page will show an error or refuse to connect — that's expected")
print("  4. Copy the full URL from their browser's address bar and send it back to you\n")

callback_url = input("Paste their callback URL here: ").strip()

parsed = urlparse(callback_url)
params = parse_qs(parsed.query)
code = params.get("code", [None])[0]

if not code:
    print("\nERROR: No code found in that URL.", file=sys.stderr)
    print("Make sure they copied the full address bar URL (it should contain '?code=').", file=sys.stderr)
    sys.exit(1)

auth_manager.get_access_token(code)

print(f"\nDone! Token saved to: {cache_path}")
print(f"\nTo run the weekly digest for {name}:")
print(f"  python release_radar/new_releases.py --cache shared/.spotify_cache_{name}")
