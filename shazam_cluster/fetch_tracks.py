#!/usr/bin/env python3
"""
Fetch Shazam playlist tracks from Spotify + enrich with FreqBlog audio features.
Saves full dataset to tracks.json and tracks.csv.

SUBSET_NUM controls how many tracks to process during development to conserve
FreqBlog API quota (1,000 requests/month free). Set to None for a full run.

Incremental: tracks.json is the cache. On each run, tracks already in the cache
with backfill_status=null are skipped. Tracks with backfill_status="queued" are
retried (FreqBlog is still analyzing them). New tracks are always fetched.
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
SUBSET_NUM = None

FREQBLOG_BASE = "https://api.freqblog.com"

# Fixed field order matching /track/{id}/embedding — reconstructed locally.
EMBEDDING_FIELDS = [
    "bpm", "bpm_confidence", "key_int", "mode", "key_confidence",
    "energy", "loudness_db", "danceability", "valence", "speechiness",
    "instrumentalness", "liveness", "acousticness", "time_signature",
    "onset_rate", "dynamic_complexity", "tuning_frequency", "average_loudness",
]


def load_existing(path: Path) -> dict:
    """Load tracks.json indexed by spotify_id. Returns {} if file absent."""
    if path.exists():
        records = json.loads(path.read_text())
        return {r["spotify_id"]: r for r in records}
    return {}


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


def _freqblog_get(session: requests.Session, params: dict) -> requests.Response:
    r = session.get(f"{FREQBLOG_BASE}/lookup", params=params)
    if r.status_code == 429:
        retry_after = int(r.headers.get("Retry-After", 5))
        print(f"  [rate limited] waiting {retry_after}s...")
        time.sleep(retry_after)
        r = session.get(f"{FREQBLOG_BASE}/lookup", params=params)
    return r


def freqblog_lookup(session: requests.Session, track_name: str, artist: str, isrc: str | None = None) -> dict | None:
    # Try ISRC first — exact catalog match, no name-formatting ambiguity.
    # 404 on miss (unlike name lookup which returns 202), so fall through to name.
    if isrc:
        try:
            r = _freqblog_get(session, {"isrc": isrc})
            if r.status_code == 200:
                return r.json()
            if r.status_code != 404:
                print(f"  [FreqBlog ISRC error] {r.status_code}")
        except Exception as e:
            print(f"  [FreqBlog ISRC error] {e}")

    try:
        r = _freqblog_get(session, {"track": track_name, "artist": artist})
        r.raise_for_status()
        try:
            return r.json()
        except ValueError:
            # 202 body is empty — ingest queued, retry on next run
            return {"backfill_status": "queued"}
    except requests.HTTPError as e:
        print(f"  [FreqBlog error] {e}")
        return None


def enrich_record(track: dict, features: dict | None) -> dict:
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
    else:
        for field in [
            "bpm", "bpm_alt", "bpm_confidence", "key", "key_int", "mode", "camelot",
            "open_key", "key_confidence", "energy", "loudness_db", "danceability",
            "valence", "speechiness", "instrumentalness", "liveness", "acousticness",
            "time_signature", "mood", "genre", "mood_vector", "representative_segment_start",
            "onset_rate", "dynamic_complexity", "tuning_frequency", "average_loudness",
            "itunes_track_id", "mbid", "feature_source", "backfill_status",
        ]:
            record[field] = None
        record["embedding"] = None
        record["embedding_mask"] = None
        record["embedding_fields"] = EMBEDDING_FIELDS
    return record


def save(records: list[dict]) -> None:
    OUTPUT_JSON.write_text(json.dumps(records, indent=2))
    print(f"Saved JSON → {OUTPUT_JSON}")

    flat_fields = [k for k in records[0] if k not in ("mood_vector", "embedding", "embedding_mask", "embedding_fields")]
    mv_fields = [f"mood_vector_{a}" for a in ("happy", "sad", "aggressive", "relaxed", "party")]
    emb_fields = [f"emb_{f}" for f in EMBEDDING_FIELDS]
    with OUTPUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=flat_fields + mv_fields + emb_fields)
        writer.writeheader()
        for r in records:
            row = {k: r.get(k) for k in flat_fields}
            mv = r.get("mood_vector") or {}
            for axis in ("happy", "sad", "aggressive", "relaxed", "party"):
                row[f"mood_vector_{axis}"] = mv.get(axis)
            emb = r.get("embedding") or [None] * len(EMBEDDING_FIELDS)
            for field, val in zip(EMBEDDING_FIELDS, emb):
                row[f"emb_{field}"] = val
            writer.writerow(row)
    print(f"Saved CSV  → {OUTPUT_CSV}")


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

    existing = load_existing(OUTPUT_JSON)
    print(f"Cache: {len(existing)} tracks already in tracks.json\n")

    subset = all_tracks[:SUBSET_NUM] if SUBSET_NUM else all_tracks
    if SUBSET_NUM:
        print(f"SUBSET_NUM={SUBSET_NUM} — processing first {len(subset)} tracks only.\n")

    session = requests.Session()
    session.headers["X-Api-Key"] = api_key

    records = []
    n_new = n_retried = n_skipped = 0

    for i, track in enumerate(subset, 1):
        sid = track["spotify_id"]
        cached = existing.get(sid)

        if cached and cached.get("backfill_status") != "queued" and cached.get("feature_source") is not None:
            records.append(cached)
            n_skipped += 1
            print(f"[{i}/{len(subset)}] SKIP            {track['name']} — {track['artist']}")
            continue

        if not cached:
            reason = "NEW            "
        elif cached.get("backfill_status") == "queued":
            reason = "RETRY (queued) "
        else:
            reason = "RETRY (no feat)"
        print(f"[{i}/{len(subset)}] {reason} {track['name']} — {track['artist']}")
        features = freqblog_lookup(session, track["name"], track["artist"], isrc=track.get("isrc"))

        if cached:
            n_retried += 1
        else:
            n_new += 1

        record = enrich_record(track, features)
        records.append(record)

        status = f"mood={record.get('mood')} energy={record.get('energy')} bpm={record.get('bpm')} source={record.get('feature_source')} backfill={record.get('backfill_status')}"
        print(f"         {status}")

    print(f"\nFreqBlog quota used this run: {n_new + n_retried} requests "
          f"({n_new} new, {n_retried} retried, {n_skipped} skipped)")

    if records:
        save(records)


if __name__ == "__main__":
    main()
