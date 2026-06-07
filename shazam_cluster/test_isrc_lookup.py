#!/usr/bin/env python3
"""
Diagnostic: test ISRC-based FreqBlog lookup on tracks with no features.

Reads tracks.json, picks the first TEST_N tracks where feature_source is null
and isrc is available, and calls GET /lookup?isrc=<isrc> for each.

Does NOT write to tracks.json — read-only diagnostic.
"""
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

TEST_N = 5  # number of tracks to test — controls quota usage

DATA = Path(__file__).parent / "tracks.json"
FREQBLOG_BASE = "https://api.freqblog.com"


def main():
    load_dotenv(Path(__file__).parent.parent / ".env")
    api_key = os.environ.get("FREQBLOG_API_KEY")
    if not api_key:
        print("ERROR: FREQBLOG_API_KEY not set in .env")
        return

    records = json.loads(DATA.read_text())
    candidates = [
        r for r in records
        if r.get("feature_source") is None and r.get("isrc")
    ]
    print(f"Tracks with no features + ISRC available: {len(candidates)}")
    print(f"Testing first {TEST_N}...\n")

    session = requests.Session()
    session.headers["X-Api-Key"] = api_key

    for track in candidates[:TEST_N]:
        name = track["name"]
        artist = track["artist"]
        isrc = track["isrc"]
        print(f"Track:  {name} — {artist}")
        print(f"ISRC:   {isrc}")

        r = session.get(f"{FREQBLOG_BASE}/lookup", params={"isrc": isrc})

        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", 5))
            print(f"  [rate limited] waiting {retry_after}s...")
            time.sleep(retry_after)
            r = session.get(f"{FREQBLOG_BASE}/lookup", params={"isrc": isrc})

        print(f"Status: {r.status_code}")

        if r.status_code == 200:
            data = r.json()
            print(f"  feature_source: {data.get('feature_source')}")
            print(f"  backfill_status: {data.get('backfill_status')}")
            print(f"  bpm={data.get('bpm')}  energy={data.get('energy')}  mood={data.get('mood')}")
        elif r.status_code == 202:
            print("  [202] ingest queued — check back in 1–2 min")
        elif r.status_code == 404:
            print("  [404] not in FreqBlog catalog via ISRC")
        else:
            print(f"  [unexpected] {r.text[:200]}")

        print()


if __name__ == "__main__":
    main()
