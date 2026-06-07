# Release Radar Filter

Reads your Spotify Release Radar playlist, filters to full albums released in the last 7 days, and emails a digest.

## Setup

### 1. Spotify Developer App

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and create an app.
2. Add `http://127.0.0.1:8888/callback` as a Redirect URI in the app settings. (`localhost` is no longer accepted — use the IP literal.)
3. Copy the Client ID and Client Secret.

### 2. Gmail App Password

1. Enable 2-Step Verification on your Google account.
2. Go to Google Account → Security → 2-Step Verification → App passwords.
3. Generate a password for "Mail" — copy the 16-character code.

### 3. Environment variables

Copy `.env.example` to `.env` at the repo root and fill in all values:

```bash
cp .env.example .env
```

### 4. First-run authentication (Mac only)

The first run needs a browser to complete OAuth. Temporarily open [shared/spotify_auth.py](../shared/spotify_auth.py) and change `open_browser=False` to `open_browser=True`, then run:

```bash
python release_radar/run.py --dry-run
```

A browser window will open. Log in and authorize. The token is saved to `shared/.spotify_cache`. Revert `open_browser` back to `False`.

## Running

```bash
# Dry run — prints the email HTML without sending
python release_radar/run.py --dry-run

# Full run — sends the email
python release_radar/run.py
```

## Deploying to Raspberry Pi

1. Clone the repo on the Pi and copy your `.env` file.
2. Copy `shared/.spotify_cache` from your Mac to the same path on the Pi.
3. Install dependencies: `conda env create -f environment.yml`

**Cron entry** (runs every Friday at 8 AM, after Spotify regenerates Release Radar):

```cron
0 8 * * 5 /home/pi/miniconda3/envs/spotify-lab/bin/python /home/pi/spotify-lab/release_radar/run.py >> /home/pi/spotify-lab/release_radar/release_radar.log 2>&1
```

Use `crontab -e` to add the entry. The log file captures stdout and stderr for debugging.
