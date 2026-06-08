# Ideas / running backlog

## Save plots (per-cluster directory)
Write each `plt.savefig()` to `shazam_cluster/plots/k{K}/` alongside the model artifacts so runs are reproducible and comparable across K values.

## Shazam Other playlist doesn't change with the number of clusters, but gets re-created every time
`ensure_playlist` unconditionally POSTs — Spotify allows duplicate names and silently creates a second playlist. Fix: check `playlist_ids["other"]` before creating, or look up existing playlists by name before POSTing.

## Validate approach and feature selection
Are the 7 chosen features (energy, valence, danceability, bpm, speechiness, instrumentalness, release_year) actually separating what matters? Cross-check cluster membership against FreqBlog `mood` and `genre` labels. Consider drop/add experiments (e.g. `acousticness`, `liveness`).

## What's happening with negative silhouette scores? What do these tracks have in common?
Tracks with silhouette < 0 are closer to a neighboring cluster's centroid than their own. Pull these tracks from `feat_clean`, inspect mood/genre/artist, and listen — are they genuinely ambiguous or is k=3 too coarse?

## Other classifiers? Tree-based? Try a few things.
K-means assumes spherical clusters and equal variance. Try: DBSCAN (density-based, no k needed), Gaussian Mixture Models (soft assignment), or a decision tree post-hoc to interpret cluster boundaries in human-readable rules.

## Automate the whole pipeline end-to-end with batch scripts? Toward putting on Pi and running at ~weekly frequency.
Three-step sequence: `fetch_tracks.py` → run Save cell in `cluster.py` (needs headless execution — refactor out of Jupyter cells) → `create_playlists.py`. OAuth token refresh on Pi requires pre-cached token or PKCE device flow.

## Send an email and summarize every week?
Weekly digest: new tracks added since last run, which cluster they landed in, any notable shifts in cluster composition. Builds on the Release Radar email skeleton in `release_radar/run.py`.

## How can I encourage myself to explore and dig into these tracks rather than passively consuming?
Ideas: surface the full album for a Shazam track and link to it; pull a Bandcamp/AllMusic write-up for the artist; highlight tracks where FreqBlog `mood` disagrees with the cluster label as a "worth a closer listen" signal.

## Is this doing what I want it to?
Step back periodically: listen to each playlist end-to-end and ask whether the clusters feel coherent and distinct. Adjust K or features based on that subjective gut-check, not just silhouette score.
