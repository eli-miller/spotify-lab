# Rate Limiting: What's Spotify, What's Spotipy, What's Our Code

## The Stack

When our script makes an API call, the request passes through four layers before Spotify responds — and the response passes back through all four on the way out. Rate limiting involves every layer.

```
Our code (new_releases.py)
    └── spotipy (Python Spotify wrapper)
        └── requests (Python HTTP library)
            └── urllib3 (low-level HTTP + retry logic)
                └── Spotify API (server)
```

---

## What Spotify Does (Server Side)

Spotify enforces a **rolling 30-second window** rate limit. If your app makes too many requests within any 30-second window, subsequent requests get a **HTTP 429 Too Many Requests** response.

The 429 response has two notable pieces:
- A `Retry-After` header with a value in seconds
- A JSON body: `{"error": {"status": 429, "message": "Your application has reached a rate/request limit. Retry will occur after: 85359 s"}}`

**What Spotify does NOT tell you:**
- The exact request limit (it's unpublished and varies by quota mode)
- Why the Retry-After is sometimes ~85,000 seconds (~24 hours) instead of a few seconds

The 85,000s Retry-After is the key mystery. A true rolling 30-second window limit would only ask you to wait 30 seconds. The ~24h value suggests Spotify has a secondary **daily quota** on top of the burst limit — but they don't document it. In practice it means: "you've used up your daily budget, come back tomorrow."

**Dev Mode vs Extended Quota Mode:** Dev Mode has a much lower limit. Extended Quota Mode (requires a legally registered business with 250K+ MAU) gets a higher limit. There is no middle ground.

---

## What urllib3 Does (The Invisible Layer)

This is where the behavior gets surprising.

spotipy configures urllib3 — the low-level HTTP library — with automatic retry logic:

```python
# Inside spotipy's Spotify.__init__ (simplified):
Retry(
    total=3,                          # retry up to 3 times
    status_forcelist=[429, 500, 502, 503, 504],  # on these HTTP status codes
)
```

When urllib3 gets a 429 response, it:
1. Reads the `Retry-After` header (e.g., 85,359)
2. Calls `time.sleep(85359)` — **before Python even sees the response**
3. Retries the request (up to 3 times total)

This is why the script appeared to hang silently with no output. urllib3 was sleeping for 23+ hours deep inside the HTTP layer. Our `try/except SpotifyException` block never fired because the exception only gets raised *after* urllib3 exhausts all retries — which would have taken 3 × 85,000s = ~255,000 seconds (~3 days).

**The fix:** We now pass `retries=0` when constructing the spotipy client ([shared/spotify_auth.py](../shared/spotify_auth.py)), which disables urllib3's retry entirely. 429s now surface immediately as Python exceptions.

---

## What Spotipy Does

With urllib3's retry disabled, spotipy's behavior on a 429 is straightforward:
- It raises `spotipy.SpotifyException` with `http_status=429`
- The exception includes the response headers (where `Retry-After` lives)
- It does nothing else — our code is now in control

---

## What Our Code Does

**`_get_with_retry()` in [new_releases.py](new_releases.py):**

```
API call
  └── SpotifyException with 429?
        ├── Retry-After ≤ 60s  → wait and retry once (burst limit)
        └── Retry-After > 60s  → re-raise (daily quota — caller handles)
```

**Main artist loop:**

```
For each artist:
  └── fetch_recent_releases()
        └── SpotifyException with long Retry-After?
              └── save checkpoint → print how long to wait → exit cleanly
```

**`fetch_all_followed_artists()`:** Also catches 429 and exits cleanly (no checkpoint mid-fetch since we don't have a partial artist list worth saving).

---

## Why Testing Hits Limits Faster Than Production

Each test run (even `--limit 5`) still paginates through **all followed artists** before capping album fetches. For Tucker's 1,743 artists, that's ~35 API calls just to get the list — every single run.

| Run | Artist calls | Album calls | Total |
|-----|-------------|-------------|-------|
| `--limit 5` (no cache) | ~35 | 5 | ~40 |
| `--limit 5` (cached) | 0 | 5 | 5 |
| Full production run (cached) | 0 | ~1,743 | ~1,743 |

The **artist cache** ([followed_artists_tucker.json](followed_artists_tucker.json), etc.) eliminates the artist pagination entirely after the first run. The artist list is saved to disk and reused until you run `--refresh-artists`.

---

## Summary: Who's Responsible for What

| Behaviour | Responsible party |
|---|---|
| Returning 429 with Retry-After | **Spotify** |
| Silently sleeping for 85,000 seconds | **urllib3** (spotipy's default config) — now fixed |
| Surfacing 429 as a Python exception | **spotipy** (once urllib3 retries=0) |
| Short-wait retry (burst) | **Our code** (`_get_with_retry`) |
| Clean exit + checkpoint on daily quota | **Our code** (main loop) |
| Reducing calls via artist cache | **Our code** (`followed_artists_*.json`) |
| Reducing calls via run checkpoint | **Our code** (`checkpoint.json`) |
