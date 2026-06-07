# spotify-lab

Personal Spotify API project collection. Developed and tested on macOS, deployed to Raspberry Pi for scheduled automation.

## Projects

### 1. Release Radar Filter (`release_radar/`)
**Status: Tabled.** See "Spotify API Restrictions" section below before resuming.

Original goal: read Release Radar, filter to full albums, email a weekly digest.

The script skeleton exists in `release_radar/run.py` with auth, filtering, deduplication, and Gmail SMTP email logic. It is blocked at the Spotify API layer, not a code bug.
7DS6WcZdNiykC0BvWlt0Ul
### 2. Shazam Cluster (`shazam_cluster/`)
**Status: In progress.**

Reads the native "My Shazam Tracks" playlist (ID: `7DS6WcZdNiykC0BvWlt0Ul`, owner: user, confirmed native — description is Shazam-injected), enriches each track with FreqBlog audio features, and clusters by vibe/mood for sub-playlist creation.

**Current state:**
- `shazam_cluster/fetch_tracks.py` — fetches all 306 tracks from Spotify, looks up each via FreqBlog `/lookup`, builds an 18D embedding vector locally (no extra quota), and saves to `tracks.json` + `tracks.csv` (ML-ready, flat columns)
- 43 fields per record: Spotify metadata (spotify_id, added_at, album, release_date, isrc, explicit) + FreqBlog audio features (bpm, energy, valence, danceability, mood, genre, camelot, mood_vector, etc.) + 18D embedding
- `SUBSET_NUM = 10` at the top of the script — set to `None` for a full run. Full run costs 306/1,000 monthly FreqBlog requests.
- Tracks with `backfill_status = "queued"` have partial data; re-running after a few minutes fills them in as FreqBlog analyzes them.
- **Next step**: clustering logic (vibe/mood-based) + Spotify sub-playlist creation.

## Spotify API Restrictions (as of June 2026)

Spotify's November 2024 API changes ([blog post](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api), [Feb 2026 follow-up](https://developer.spotify.com/documentation/web-api/references/changes/february-2026)) permanently blocked Development Mode apps from reading algorithmic/Spotify-owned playlists. This includes Release Radar, Discover Weekly, and Daily Mixes.

**What we tried:**
- `current_user_playlists()` — Release Radar does not appear even when followed in-app; Spotify filters it from the API response
- Direct playlist fetch by ID (`37i9dQZEVXbxciCqnnnGLO`) — returns 403 Forbidden
- The playlist ID in the Spotify web player URL is the same generic ID and is also blocked

**Extended Quota Mode** (which would unblock this) now requires a legally registered business with 250K+ monthly active users. Not available to hobbyist developers.

**Viable alternatives explored:**
1. **Followed artists → recent albums**: `GET /me/following` + `GET /artists/{id}/albums?include_groups=album`, filter by release date. Works in Dev Mode. Tabled because the user doesn't actively follow artists on Spotify.
2. **Copy-to-owned-playlist via a third-party extended-access service**: e.g. [Better-Release-Radar](https://github.com/PaulMcInnis/Better-Release-Radar). Requires trusting an external service or running one with extended access.
3. **Third-party release APIs** (MusicBrainz, etc.): More complex, less reliable for smaller artists.

**What IS accessible in Dev Mode (confirmed working):**
- `GET /playlists/{id}` — metadata only (name, owner, description). Works.
- `GET /playlists/{id}/items` — track items. Works. **Must call directly** — see spotipy workaround below.
- `GET /artists/{id}` — single artist. Works, but response is stripped: only id, name, uri, images, external_urls, href, type. No `genres`, no `popularity`, no `followers` (removed Feb 2026).
- `GET /me/playlists`, `GET /me/following`, `GET /artists/{id}/albums` — work.
- Playback control, search.

**Confirmed broken in Dev Mode:**
- `GET /artists?ids=...` (batch) — 403 Forbidden, even for public artist data.
- `GET /artists/{id}` genres/popularity fields — silently absent from response.

**Spotipy 2.25.2 workarounds:**
- `sp.playlist_items()` silently calls the deprecated `/tracks` endpoint, which now returns 403. Use `sp._get(f"playlists/{playlist_id}/items", limit=100, offset=offset)` directly.
- The `/items` endpoint response schema differs from `/tracks`: track data lives in `item["item"]`, not `item["track"]`. Filter with `item["item"].get("type") == "track"`.
- `sp.artists()` (batch) also hits a 403-returning endpoint. Do not use it.

**Relevant community discussion:** [Spotify SDK GitHub issue #159](https://github.com/spotify/spotify-web-api-ts-sdk/issues/159), [State of Spotify Web API Report 2025](https://spotify.leemartin.com/)

## Spotify Web API Rules

- **OpenAPI spec**: Always refer to https://developer.spotify.com/reference/web-api/open-api-schema.yaml for all endpoint paths, parameters, and response schemas. Do not guess endpoints or field names — fetch the spec if uncertain.
- **Authorization**: Use Authorization Code with PKCE for any user-specific data. Use Client Credentials only for public, non-user data. Never use the deprecated Implicit Grant flow.
- **Deprecated endpoints**: Do not use deprecated endpoints. Use `/playlists/{id}/items` instead of `/playlists/{id}/tracks`, and prefer `/me/library` over type-specific library endpoints.
- **Scopes**: Request only the minimum scopes needed. Do not request broad scopes preemptively.
- **Token management**: Never expose the Client Secret in client-side code. Always implement token refresh so the app does not break when access tokens expire.
- **Rate limits**: Handle HTTP 429 responses with exponential backoff using the `Retry-After` header. Never retry in a tight loop.
- **Error handling**: Handle all HTTP error codes in the OpenAPI schema. Surface error messages to the user meaningfully.

## FreqBlog Music API Rules

- **OpenAPI spec**: Always refer to https://api.freqblog.com/openapi.json for all endpoint paths, parameters, and response schemas. Do not guess endpoints or field names — fetch the spec if uncertain.
- **Authentication**: All requests require `X-Api-Key: <key>` header. Key is stored in `.env` as `FREQBLOG_API_KEY`, never hardcoded.
- **Preferred lookup endpoint**: Use `GET /lookup?track=<name>&artist=<name>` for the richest response (38 fields). The Spotify-compat `GET /v1/audio-features/{id}` returns fewer fields — only use it when Spotify shape is explicitly required.
- **Embedding**: `GET /track/{itunes_track_id}/embedding` costs 1 quota request per track. Since it only repackages fields already returned by `/lookup`, reconstruct the embedding vector locally from the lookup response instead of making a separate call.
- **Quota**: Free tier is 1,000 requests/month. Always use `SUBSET_NUM` during development to avoid burning quota. Log running totals when making bulk calls.
- **Rate limits**: Handle HTTP 429 with exponential backoff. Do not retry in a tight loop.
- **Miss handling**: `/lookup` returns a `backfill_status` field. If a track is not in the catalog, the API queues analysis (30s–2min). Do not treat a null-feature response as a hard failure — log it and continue.
- **Error handling**: Handle all HTTP error codes per the OpenAPI schema. Surface errors meaningfully; never silently swallow a non-2xx response.

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
