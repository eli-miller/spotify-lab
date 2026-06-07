# spotify-lab

Personal Spotify API project collection. Developed and tested on macOS, deployed to Raspberry Pi for scheduled automation.

## Projects

### 1. Release Radar Filter (`release_radar/`)
Reads the Spotify Release Radar playlist, filters to full albums only (excluding singles and EPs), and emails a weekly digest with new albums and Spotify links. Runs weekly on the Pi after Spotify regenerates Release Radar.

### 2. Shazam Cluster (`shazam_cluster/`)
Reads a Shazam-auto-populated playlist, clusters tracks by audio features/genre into sub-playlists. Runs on a ~weekly cadence to sort new shazamed songs.

## Setup

- Python 3.x
- Spotify Developer App credentials stored in `.env` (never committed)
- See each project's README for setup instructions

## Environment

- Dev: macOS
- Prod: Raspberry Pi (headless — no browser for OAuth, use client credentials or authorization code with PKCE + cached token)

## Conventions

- Each project lives in its own subdirectory
- Shared Spotify auth/client logic goes in `shared/`
- Secrets in `.env`, never hardcoded
- Scripts should be runnable standalone (cron-friendly)
