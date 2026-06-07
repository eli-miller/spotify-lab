#!/usr/bin/env python3
"""
Fetch Shazam playlist tracks from Spotify + enrich with FreqBlog audio features.
Saves full dataset to tracks.json and tracks.csv.

SUBSET_NUM controls how many tracks to process during development to conserve
FreqBlog API quota (1,000 requests/month free). Set to None for a full run.
"""
import csv
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.spotify_auth import get_spotify_client

PLAYLIST_ID = "7DS6WcZdNiykC0BvWlt0Ul"
SCOPE = "playlist-read-private"
OUTPUT_JSON = Path(__file__).parent / "tracks.json"
OUTPUT_CSV = Path(__file__).parent / "tracks.csv"

# Conservative subset for development — set to None for a full run.
# FreqBlog free tier: 1,000 requests/month. Full playlist is 306 tracks.
SUBSET_NUM = 10

FREQBLOG_BASE = "https://api.freqblog.com"

# Fixed field order matching /track/{id}/embedding — reconstructed locally.
EMBEDDING_FIELDS = [
    "bpm", "bpm_confidence", "key_int", "mode", "key_confidence",
    "energy", "loudness_db", "danceability", "valence", "speechiness",
    "instrumentalness", "liveness", "acousticness", "time_signature",
    "onset_rate", "dynamic_complexity", "tuning_frequency", "average_loudness",
]


def fetch_playlist_tracks(sp, playlist_id):
    # Use /items (not deprecated /tracks) — spotipy's playlist_items() calls /tracks and gets 403
    # /items returns item["item"] for the track object, not item["track"]
    tracks = []
    offset = 0
    while True:
        results = sp._get(f"playlists/{playlist_id}/items", limit=100, offset=offset)
        for item in results["items"]:
            track = item.get("item")
            if track and track.get("type") == "track" and not track.get("is_local"):
                tracks.append({
                    "spotify_id": track["id"],
                    "name": track["name"],
                    "artist": track["artists"][0]["name"] if track.get("artists") else "Unknown",
                    "album": track.get("album", {}).get("name"),
                    "album_type": track.get("album", {}).get("album_type"),
                    "release_date": track.get("album", {}).get("release_date"),
                    "duration_ms": track.get("duration_ms"),
                    "explicit": track.get("explicit"),
                    "isrc": track.get("external_ids", {}).get("isrc"),
                    "added_at": item.get("added_at"),
                })
        offset += len(results["items"])
        if results["next"] is None:
            break
    return tracks


def build_embedding(features: dict) -> dict:
    """Reconstruct the FreqBlog embedding vector locally from a /lookup response."""
    embedding = []
    mask = []
    for field in EMBEDDING_FIELDS:
        val = features.get(field)
        if val is not None:
            embedding.append(val)
            mask.append(True)
        else:
            embedding.append(0.0)
            mask.append(False)
    return {"embedding": embedding, "embedding_mask": mask, "embedding_fields": EMBEDDING_FIELDS}


def freqblog_lookup(session: requests.Session, track_name: str, artist: str) -> dict | None:
    try:
        r = session.get(
            f"{FREQBLOG_BASE}/lookup",
            params={"track": track_name, "artist": artist},
        )
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", 5))
            print(f"  [rate limited] waiting {retry_after}s...")
            time.sleep(retry_after)
            r = session.get(
                f"{FREQBLOG_BASE}/lookup",
                params={"track": track_name, "artist": artist},
            )
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        print(f"  [FreqBlog error] {e}")
        return None


def main():
    load_dotenv()
    api_key = os.environ.get("FREQBLOG_API_KEY")
    if not api_key:
        print("ERROR: FREQBLOG_API_KEY not set in .env")
        sys.exit(1)

    sp = get_spotify_client(SCOPE)

    print(f"Fetching tracks from Spotify playlist {PLAYLIST_ID}...")
    all_tracks = fetch_playlist_tracks(sp, PLAYLIST_ID)
    print(f"Fetched {len(all_tracks)} tracks total.")

    subset = all_tracks[:SUBSET_NUM] if SUBSET_NUM else all_tracks
    if SUBSET_NUM:
        print(f"SUBSET_NUM={SUBSET_NUM} — processing first {len(subset)} tracks only.\n")

    session = requests.Session()
    session.headers["X-Api-Key"] = api_key

    records = []
    quota_used = 0
    for i, track in enumerate(subset, 1):
        print(f"[{i}/{len(subset)}] {track['name']} — {track['artist']}")
        features = freqblog_lookup(session, track["name"], track["artist"])
        quota_used += 1

        record = {**track}
        if features:
            for field in [
                "bpm", "bpm_alt", "bpm_confidence",
                "key", "key_int", "mode", "camelot", "open_key", "key_confidence",
                "energy", "loudness_db", "danceability", "valence",
                "speechiness", "instrumentalness", "liveness", "acousticness",
                "time_signature", "mood", "genre",
                "mood_vector",
                "representative_segment_start",
                "onset_rate", "dynamic_complexity", "tuning_frequency", "average_loudness",
                "itunes_track_id", "mbid", "feature_source", "backfill_status",
            ]:
                record[field] = features.get(field)
            record.update(build_embedding(features))
            status = f"mood={features.get('mood')} energy={features.get('energy')} bpm={features.get('bpm')}"
        else:
            record.update({f: None for f in EMBEDDING_FIELDS})
            record["embedding"] = None
            record["embedding_mask"] = None
            record["embedding_fields"] = EMBEDDING_FIELDS
            status = "no data"
        print(f"         {status}")
        records.append(record)

    print(f"\nFreqBlog quota used this run: {quota_used} requests")

    OUTPUT_JSON.write_text(json.dumps(records, indent=2))
    print(f"Saved JSON → {OUTPUT_JSON}")

    if records:
        flat_fields = [k for k in records[0] if k not in ("mood_vector", "embedding", "embedding_mask", "embedding_fields")]
        with OUTPUT_CSV.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=flat_fields + ["mood_vector_happy", "mood_vector_sad", "mood_vector_aggressive", "mood_vector_relaxed", "mood_vector_party"] + [f"emb_{field}" for field in EMBEDDING_FIELDS])
            writer.writeheader()
            for r in records:
                row = {k: r.get(k) for k in flat_fields}
                mv = r.get("mood_vector") or {}
                for axis in ["happy", "sad", "aggressive", "relaxed", "party"]:
                    row[f"mood_vector_{axis}"] = mv.get(axis)
                emb = r.get("embedding") or [None] * len(EMBEDDING_FIELDS)
                for field, val in zip(EMBEDDING_FIELDS, emb):
                    row[f"emb_{field}"] = val
                writer.writerow(row)
        print(f"Saved CSV  → {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
