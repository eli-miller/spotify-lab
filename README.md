# spotify-lab

A collection of personal Spotify automation scripts. Developed on macOS, deployed to a Raspberry Pi for weekly scheduled runs.

## Projects

### Release Radar Filter
Spotify's Release Radar surfaces new music from artists you follow — but it mixes full albums, EPs, and singles together. This script:
- Reads your Release Radar playlist
- Filters to full **albums only** released in the past week
- Sends you an email digest with album names and Spotify links

**Goal:** Get a clean weekly email of new albums only, no single/EP noise.

### Shazam Playlist Clusterer
Automatically sorts your Shazam playlist into genre-based sub-playlists using Spotify audio features (energy, danceability, valence, etc.) and clustering.

**Goal:** Automatically organize shazam'd tracks into coherent genre buckets on a weekly cadence.

## Setup

```bash
# Clone the repo
git clone <repo-url>
cd spotify-lab

# Install dependencies (per project)
pip install -r requirements.txt

# Copy and fill in your credentials
cp .env.example .env
```

You'll need a [Spotify Developer App](https://developer.spotify.com/dashboard) — client ID and secret go in `.env`.

## Deployment

Scripts are designed to run headlessly on a Raspberry Pi via cron. See each project directory for specific cron setup instructions.

## Structure

```
spotify-lab/
├── release_radar/      # Release Radar filter + email digest
├── shazam_cluster/     # Shazam playlist auto-clustering
├── shared/             # Shared Spotify auth and client helpers
├── .env.example        # Template for credentials
└── requirements.txt    # Top-level dependencies
```
