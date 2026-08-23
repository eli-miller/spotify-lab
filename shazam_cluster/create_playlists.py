#!/usr/bin/env python3
"""
Incrementally create/update Shazam cluster playlists on Spotify.

First run: creates K+1 public playlists (Shazam Cluster 0..N + Shazam Other)
           and adds all tracks from cluster_assignments.json.

Subsequent runs: only new tracks (not yet in assignments) are predicted and appended.
                 Existing playlist contents are never touched, so manual reordering is preserved.

Run after:
  1. fetch_tracks.py  — refreshes tracks.json
  2. cluster.py Save cell — refreshes cluster_assignments.json + model/
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import joblib
import spotipy
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.spotify_auth import get_spotify_client

SCOPE = "playlist-modify-public playlist-read-private"
K = 3  # must match the K used when running cluster.py Save cell
DATA = Path(__file__).parent / "tracks.json"
ASSIGNMENTS = Path(__file__).parent / f"cluster_assignments_k{K}.json"
MODEL_DIR = Path(__file__).parent / f"model_k{K}"

# Must match cluster.py FEATURE_COLS exactly
FEATURE_COLS = [
    "energy",
    "valence",
    "danceability",
    "bpm",
    "speechiness",
    "instrumentalness",
    "release_year",
]


def build_feature_row(track: dict) -> list[float] | None:
    release_year = None
    if track.get("release_date"):
        release_year = float(str(track["release_date"])[:4])
    vals = []
    for col in FEATURE_COLS:
        v = release_year if col == "release_year" else track.get(col)
        if v is None:
            return None
        vals.append(float(v))
    return vals


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def fetch_user_playlist_names(sp) -> dict[str, str]:
    """Map of {playlist name: id} for playlists owned by the current user.

    Spotify is the source of truth for playlist existence, not the local
    JSON state file — that file can be lost, reset, or stale (e.g. a
    cluster.py Save-cell re-run wipes it), so ensure_playlist() must always
    reconcile against what's actually live before creating anything.
    """
    me_id = sp.current_user()["id"]
    names: dict[str, str] = {}
    offset = 0
    while True:
        results = sp._get("me/playlists", limit=50, offset=offset)
        for pl in results["items"]:
            if pl.get("owner", {}).get("id") == me_id:
                names[pl["name"]] = pl["id"]
        offset += len(results["items"])
        if results["next"] is None:
            break
    return names


def fetch_playlist_track_ids(sp, playlist_id: str) -> set[str]:
    """Track IDs currently live in a playlist, for dedup before adding."""
    ids: set[str] = set()
    offset = 0
    while True:
        results = sp._get(f"playlists/{playlist_id}/items", limit=100, offset=offset)
        for item in results["items"]:
            track = item.get("item")
            if track and track.get("id"):
                ids.add(track["id"])
        offset += len(results["items"])
        if results["next"] is None:
            break
    return ids


def ensure_playlist(sp, existing_names: dict[str, str], name: str, description: str) -> str:
    if name in existing_names:
        print(f"  Reusing existing playlist: {name}")
        return existing_names[name]
    # sp.user_playlist_create() calls deprecated POST /users/{id}/playlists → 403
    pl = sp._post(
        "me/playlists",
        payload={"name": name, "public": True, "description": description},
    )
    print(f"  Created: {name}")
    return pl["id"]


def main():
    load_dotenv(Path(__file__).parent.parent / ".env")

    if not ASSIGNMENTS.exists():
        print(
            "ERROR: cluster_assignments.json not found. Run the Save cell in cluster.py first."
        )
        sys.exit(1)
    if not (MODEL_DIR / "kmeans.joblib").exists():
        print("ERROR: model/ not found. Run the Save cell in cluster.py first.")
        sys.exit(1)

    state = json.loads(ASSIGNMENTS.read_text())
    assert (
        state["cluster_meta"]["k"] == K
    ), f"K mismatch: file has k={state['cluster_meta']['k']}, script has K={K}"
    km = joblib.load(MODEL_DIR / "kmeans.joblib")
    scaler = joblib.load(MODEL_DIR / "scaler.joblib")

    tracks = json.loads(DATA.read_text())
    existing_assignments = state["assignments"]

    # --- Assign any new tracks not yet in assignments ---
    new_by_cluster: dict[str | int, list[str]] = defaultdict(list)
    n_new = 0

    for track in tracks:
        sid = track["spotify_id"]
        if sid in existing_assignments:
            continue

        if track.get("feature_source") == "essentia_preview":
            row = build_feature_row(track)
            if row is None:
                cluster_key = "other"
                print(
                    f"  NEW → Other (missing features): {track['name']} — {track['artist']}"
                )
            else:
                cluster_key = int(km.predict(scaler.transform([row]))[0])
                print(
                    f"  NEW → Cluster {cluster_key}: {track['name']} — {track['artist']}"
                )
        else:
            cluster_key = "other"
            print(f"  NEW → Other: {track['name']} — {track['artist']}")

        existing_assignments[sid] = cluster_key
        new_by_cluster[cluster_key].append(sid)
        n_new += 1

    if n_new == 0:
        print("No new tracks to assign.")
    else:
        print(f"\n{n_new} new track(s) assigned.")

    # --- Ensure playlists exist ---
    try:
        sp = get_spotify_client(SCOPE)
    except spotipy.oauth2.SpotifyOauthError as e:
        print(f"ERROR: Spotify auth failed — {e}", file=sys.stderr)
        print("Re-run on Mac to re-authenticate, then copy shared/.spotify_cache to the Pi.", file=sys.stderr)
        sys.exit(1)

    playlist_ids = state["cluster_meta"]["playlist_ids"]
    descriptions = state["cluster_meta"]["descriptions"]
    # populated: set of cluster keys whose Spotify playlists have been fully seeded
    populated: set[str] = set(state["cluster_meta"].get("populated", []))

    print("\nChecking playlists...")
    existing_names = fetch_user_playlist_names(sp)
    for c in range(K):
        key = str(c)
        playlist_ids[key] = ensure_playlist(
            sp, existing_names, f"Shazam Cluster {c+1}/{K}", descriptions.get(key, "")
        )

    playlist_ids["other"] = ensure_playlist(
        sp,
        existing_names,
        "Shazam Other",
        "Shazam tracks without sufficient audio features for clustering",
    )

    # --- Build tracks to add ---
    # Unpopulated playlists (created but not yet seeded) get ALL assigned tracks.
    # Populated playlists get only tracks newly assigned this run.
    to_add: dict[str, list[str]] = defaultdict(list)

    unpopulated = {k for k in playlist_ids if k not in populated}
    if unpopulated:
        for sid, cluster_key in existing_assignments.items():
            key = str(cluster_key)
            if key in unpopulated:
                to_add[key].append(sid)

    for cluster_key, sids in new_by_cluster.items():
        key = str(cluster_key)
        if key not in unpopulated:  # already included above if unpopulated
            to_add[key].extend(sids)

    # --- Add tracks to playlists ---
    if not to_add:
        print("All tracks already in playlists. Nothing to add.")
    else:
        print("\nAdding tracks to playlists...")
        for key, sids in to_add.items():
            pl_id = playlist_ids[key]
            label = f"Cluster {key}" if key != "other" else "Other"

            # Reconcile against Spotify's live contents, not just local
            # populated/assignments bookkeeping — that state can be stale
            # (e.g. reset by a cluster.py Save-cell re-run), so re-checking
            # here is what actually prevents duplicate track entries.
            live_ids = fetch_playlist_track_ids(sp, pl_id)
            new_sids = [sid for sid in sids if sid not in live_ids]
            skipped = len(sids) - len(new_sids)
            if skipped:
                print(f"  Shazam {label}: skipping {skipped} track(s) already in playlist")

            if not new_sids:
                print(f"  Shazam {label}: nothing to add")
                populated.add(key)
                continue

            uris = [f"spotify:track:{sid}" for sid in new_sids]
            for batch in chunks(uris, 100):
                # /tracks is deprecated and 403s in Dev Mode — use /items
                sp._post(f"playlists/{pl_id}/items", payload={"uris": batch})
            print(f"  Shazam {label}: added {len(uris)} track(s)")
            populated.add(key)

    # --- Save updated state ---
    state["assignments"] = existing_assignments
    state["cluster_meta"]["playlist_ids"] = playlist_ids
    state["cluster_meta"]["populated"] = sorted(populated)
    ASSIGNMENTS.write_text(json.dumps(state, indent=2))
    print(f"\nSaved → {ASSIGNMENTS}")


if __name__ == "__main__":
    main()
