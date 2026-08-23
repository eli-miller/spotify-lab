#!/usr/bin/env python3
"""Quick dataset quality report for tracks.json."""

import json
from collections import Counter
from pathlib import Path

DATA = Path(__file__).parent / "tracks.json"

KEY_FIELDS = [
    "bpm",
    "energy",
    "valence",
    "danceability",
    "acousticness",
    "instrumentalness",
    "speechiness",
    "liveness",
    "loudness_db",
    "mood",
    "genre",
    "mood_vector",
    "onset_rate",
]


def pct(n, total):
    return f"{n/total*100:.0f}%"


def main():
    records = json.loads(DATA.read_text())
    n = len(records)
    print(f"Total records: {n}\n")

    sources = Counter(r.get("feature_source") for r in records)
    print("feature_source breakdown:")
    for src, count in sources.most_common():
        print(f"  {str(src):<20} {count:>3}  ({pct(count, n)})")

    backfills = Counter(r.get("backfill_status") for r in records)
    print("\nbackfill_status breakdown:")
    for bs, count in backfills.most_common():
        print(f"  {str(bs):<20} {count:>3}  ({pct(count, n)})")

    print("\nField coverage (non-null %) across all records:")
    for f in KEY_FIELDS:
        filled = sum(1 for r in records if r.get(f) is not None)
        print(f"  {f:<25} {filled/n*100:5.1f}%")

    print("\nField coverage by source:")
    for src in [None, "essentia_preview", "acousticbrainz", "msd"]:
        grp = [r for r in records if r.get("feature_source") == src]
        if not grp:
            continue
        print(f"  source={src} (n={len(grp)}):")
        for f in [
            "bpm",
            "energy",
            "valence",
            "danceability",
            "mood",
            "genre",
            "instrumentalness",
            "acousticness",
        ]:
            filled = sum(1 for r in grp if r.get(f) is not None)
            print(f"    {f:<20} {filled/len(grp)*100:5.1f}%")

    ep = [r for r in records if r.get("feature_source") == "essentia_preview"]
    print(f"\nMood distribution (essentia_preview only, n={len(ep)}):")
    moods = Counter(r.get("mood") for r in ep)
    for mood, count in moods.most_common():
        bar = "#" * count
        print(f"  {str(mood):<15} {count:>3}  {bar}")


if __name__ == "__main__":
    main()
