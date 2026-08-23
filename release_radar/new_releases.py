#!/usr/bin/env python3
import os
import sys
import json
import smtplib
import time
import random
import argparse
from datetime import date, timedelta, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
import spotipy
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.spotify_auth import get_spotify_client

SCOPE = "user-follow-read"
LOOKBACK_DAYS = 7
REQUEST_DELAY = 1.0   # base seconds between album API calls (full jitter applied)
DELAY_CAP = 30.0      # maximum base delay after exponential backoff
CHECKPOINT_PATH = Path(__file__).parent / "checkpoint.json"
ARTIST_CACHE_PATH = Path(__file__).parent / "followed_artists.json"
COOLDOWN_PATH = Path(__file__).parent / "quota_cooldown.json"


# ── Quota cooldown guard ──────────────────────────────────────────────────────

def _check_quota_cooldown() -> None:
    """Exit early if a previous run hit the daily quota and it hasn't reset yet."""
    if not COOLDOWN_PATH.exists():
        return
    try:
        data = json.loads(COOLDOWN_PATH.read_text())
        reset_at = datetime.fromisoformat(data["reset_at"])
        if datetime.now() < reset_at:
            remaining = reset_at - datetime.now()
            h, rem = divmod(int(remaining.total_seconds()), 3600)
            m = rem // 60
            print(f"[quota cooldown] Daily limit active — resets in {h}h {m}m (at {reset_at.strftime('%H:%M')}).")
            print("Wait for the cooldown to expire, or delete quota_cooldown.json to override.")
            sys.exit(0)
        COOLDOWN_PATH.unlink()  # expired, clean up
    except (json.JSONDecodeError, KeyError, ValueError):
        COOLDOWN_PATH.unlink()


def _save_quota_cooldown(retry_after: int) -> None:
    reset_at = datetime.now() + timedelta(seconds=retry_after)
    COOLDOWN_PATH.write_text(json.dumps({
        "reset_at": reset_at.isoformat(timespec="seconds"),
        "retry_after_seconds": retry_after,
    }, indent=2))


def _clear_quota_cooldown() -> None:
    if COOLDOWN_PATH.exists():
        COOLDOWN_PATH.unlink()


# ── Artist cache ──────────────────────────────────────────────────────────────

def _artist_cache_path(cache_arg: str | None) -> Path:
    if cache_arg:
        suffix = Path(cache_arg).stem.replace(".spotify_cache", "")
        return ARTIST_CACHE_PATH.parent / f"followed_artists{suffix}.json"
    return ARTIST_CACHE_PATH


def load_artist_cache(cache_arg: str | None) -> list[dict] | None:
    path = _artist_cache_path(cache_arg)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        print(f"Loaded {len(data['artists'])} artists from cache (last refreshed {data['cached_at']}).")
        return data["artists"]
    except (json.JSONDecodeError, KeyError):
        return None


def save_artist_cache(artists: list[dict], cache_arg: str | None) -> None:
    path = _artist_cache_path(cache_arg)
    path.write_text(json.dumps({
        "cached_at": date.today().isoformat(),
        "artists": [{"id": a["id"], "name": a["name"]} for a in artists],
    }, indent=2))


# ── Spotify API calls ─────────────────────────────────────────────────────────

def fetch_all_followed_artists(sp: spotipy.Spotify) -> list[dict]:
    artists = []
    cursor = None
    while True:
        kwargs = {"type": "artist", "limit": 50}
        if cursor:
            kwargs["after"] = cursor
        try:
            results = sp._get("me/following", **kwargs)
        except spotipy.SpotifyException as e:
            if e.http_status == 429:
                retry_after = int((e.headers or {}).get("Retry-After", 0))
                _save_quota_cooldown(retry_after)
                hours = f"{retry_after / 3600:.1f}h" if retry_after else "unknown"
                print(f"\n[quota] Hit rate limit fetching followed artists (resets in {hours}).")
                print("Cooldown saved. Re-run once the limit resets.")
                sys.exit(0)
            raise
        page = results["artists"]
        artists.extend(page["items"])
        cursor = page["cursors"]["after"]
        if cursor is None:
            break
        _jittered_sleep(0.5)
    return artists


def fetch_recent_releases(sp: spotipy.Spotify, artist_id: str, since_date: date, include_groups: str) -> list[dict]:
    """Raises SpotifyException on 429 — caller handles backoff."""
    results = sp._get(
        f"artists/{artist_id}/albums",
        include_groups=include_groups,
        limit=10,
    )
    releases = []
    for album in results.get("items", []):
        parsed = parse_release_date(
            album.get("release_date", ""),
            album.get("release_date_precision", ""),
        )
        if parsed and parsed >= since_date:
            image_url = album["images"][-1]["url"] if album.get("images") else None
            releases.append({
                "album_name": album["name"],
                "artist_name": album["artists"][0]["name"] if album.get("artists") else "Unknown",
                "release_date": parsed,
                "spotify_url": album["external_urls"]["spotify"],
                "image_url": image_url,
                "album_type": album.get("album_type", "album"),
            })
    return releases


# ── Utilities ─────────────────────────────────────────────────────────────────

def _jittered_sleep(base: float) -> None:
    """Full jitter: sleep a random duration between 0 and base seconds."""
    time.sleep(random.uniform(0, base))


def parse_release_date(release_date: str, precision: str) -> date | None:
    try:
        if precision == "day":
            return date.fromisoformat(release_date)
        if precision == "month":
            year, month = release_date.split("-")
            return date(int(year), int(month), 1)
        if precision == "year":
            return date(int(release_date), 1, 1)
    except (ValueError, AttributeError):
        return None
    return None


# ── Checkpoint ────────────────────────────────────────────────────────────────

def _load_checkpoint(since_date: date, include_groups: str) -> dict | None:
    if not CHECKPOINT_PATH.exists():
        return None
    try:
        data = json.loads(CHECKPOINT_PATH.read_text())
        if data.get("since_date") != since_date.isoformat():
            return None
        if data.get("include_groups") != include_groups:
            return None
        for r in data.get("releases", []):
            r["release_date"] = date.fromisoformat(r["release_date"])
        return data
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _save_checkpoint(since_date: date, include_groups: str, artists: list, checked_ids: set, releases: list) -> None:
    serializable = [{**r, "release_date": r["release_date"].isoformat()} for r in releases]
    CHECKPOINT_PATH.write_text(json.dumps({
        "since_date": since_date.isoformat(),
        "include_groups": include_groups,
        "artists": [{"id": a["id"], "name": a["name"]} for a in artists],
        "checked_artist_ids": list(checked_ids),
        "releases": serializable,
    }, indent=2))


def _clear_checkpoint() -> None:
    if CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()


# ── Email ─────────────────────────────────────────────────────────────────────

def _render_cards(releases: list[dict]) -> str:
    sorted_releases = sorted(releases, key=lambda r: (-r["release_date"].toordinal(), r["artist_name"].lower()))
    html = ""
    for r in sorted_releases:
        thumb = ""
        if r["image_url"]:
            thumb = f'<img src="{r["image_url"]}" width="48" height="48" style="vertical-align:middle;margin-right:12px;border-radius:4px;">'
        html += (
            f'<div style="display:flex;align-items:center;margin-bottom:16px;">'
            f'{thumb}'
            f'<div>'
            f'<strong><a href="{r["spotify_url"]}" style="color:#1DB954;text-decoration:none;">{r["album_name"]}</a></strong><br>'
            f'{r["artist_name"]}<br>'
            f'<small style="color:#888;">Released: {r["release_date"].isoformat()}</small>'
            f'</div>'
            f'</div>'
        )
    return html


def build_html_email(albums: list[dict], singles: list[dict], artist_count: int, include_singles: bool) -> str:
    today_str = date.today().strftime("%B %d, %Y")
    header = f"New Releases — Week of {today_str}"

    albums_html = _render_cards(albums) if albums else "<p style='color:#888;'>No new albums this week.</p>"

    singles_section = ""
    if include_singles:
        singles_html = _render_cards(singles) if singles else "<p style='color:#888;'>No new singles this week.</p>"
        singles_section = (
            f"<h3 style='border-bottom:1px solid #eee;padding-bottom:6px;margin-top:28px;'>Singles</h3>"
            f"{singles_html}"
        )

    all_releases = albums + singles
    n = len(all_releases)
    unique_artists = len({r["artist_name"] for r in all_releases})
    footer = f"{n} new release{'s' if n != 1 else ''} from {unique_artists} artist{'s' if unique_artists != 1 else ''} you follow (checked {artist_count} total)"

    return (
        "<html><body style='font-family:sans-serif;max-width:600px;margin:auto;padding:20px;'>"
        f"<h2 style='border-bottom:1px solid #eee;padding-bottom:8px;'>{header}</h2>"
        f"<h3 style='border-bottom:1px solid #eee;padding-bottom:6px;'>Albums</h3>"
        f"{albums_html}"
        f"{singles_section}"
        "<hr style='margin-top:24px;'>"
        f"<small style='color:#aaa;'>{footer}</small>"
        "</body></html>"
    )


def send_email(subject: str, html_body: str) -> None:
    sender = os.environ["GMAIL_SENDER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["GMAIL_RECIPIENT"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print email HTML instead of sending")
    parser.add_argument("--limit", type=int, default=None, help="Cap number of artists to check (for testing, disables checkpoint)")
    parser.add_argument("--days", type=int, default=LOOKBACK_DAYS, help=f"How many days back to look for releases (default: {LOOKBACK_DAYS})")
    parser.add_argument("--singles", action="store_true", help="Include singles as a second section in the email")
    parser.add_argument("--cache", type=str, default=None, help="Path to a specific token cache file (for running as another user)")
    parser.add_argument("--refresh-artists", action="store_true", help="Re-fetch followed artists from Spotify instead of using the local cache")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY, help=f"Base seconds between album API calls, full jitter applied (default: {REQUEST_DELAY})")
    args = parser.parse_args()

    load_dotenv()
    _check_quota_cooldown()

    try:
        sp = get_spotify_client(SCOPE, cache_path=args.cache)
    except spotipy.oauth2.SpotifyOauthError as e:
        print(f"ERROR: Spotify auth failed — {e}", file=sys.stderr)
        print("Run setup_auth.py on Mac first to authorize user-follow-read, then copy shared/.spotify_cache to Pi.", file=sys.stderr)
        sys.exit(1)

    since_date = date.today() - timedelta(days=args.days)
    include_groups = "album,single" if args.singles else "album"
    use_checkpoint = args.limit is None

    print(f"Checking for releases since {since_date.isoformat()} ({args.days} days)...")

    checkpoint = _load_checkpoint(since_date, include_groups) if use_checkpoint else None
    if checkpoint:
        artists = checkpoint["artists"]
        checked_ids = set(checkpoint["checked_artist_ids"])
        releases = checkpoint["releases"]
        print(f"Resuming checkpoint: {len(checked_ids)}/{len(artists)} artists already done.")
    else:
        cached = None if args.refresh_artists else load_artist_cache(args.cache)
        if cached is None:
            print("Fetching followed artists from Spotify...")
            artists = fetch_all_followed_artists(sp)
            save_artist_cache(artists, args.cache)
            print(f"Fetched and cached {len(artists)} followed artists.")
        else:
            artists = cached
        checked_ids = set()
        releases = []
        if use_checkpoint:
            _save_checkpoint(since_date, include_groups, artists, checked_ids, releases)

    if args.limit:
        artists = artists[: args.limit]
        print(f"(limited to first {args.limit} for testing)")

    remaining = [a for a in artists if a["id"] not in checked_ids]

    # Shuffle so repeated partial runs cover different artists each time
    random.shuffle(remaining)

    base_delay = args.delay
    found_count = 0

    with tqdm(remaining, desc="Checking artists", unit="artist") as bar:
        for artist in bar:
            bar.set_postfix(releases=found_count, delay=f"{base_delay:.1f}s")
            _jittered_sleep(base_delay)

            while True:
                try:
                    recent = fetch_recent_releases(sp, artist["id"], since_date, include_groups)
                    break
                except spotipy.SpotifyException as e:
                    if e.http_status != 429:
                        raise
                    retry_after = int((e.headers or {}).get("Retry-After", 5))
                    if retry_after > 60:
                        # Daily quota — save state and exit cleanly
                        if use_checkpoint:
                            _save_checkpoint(since_date, include_groups, artists, checked_ids, releases)
                        _save_quota_cooldown(retry_after)
                        h = retry_after / 3600
                        bar.close()
                        print(f"\n[quota] Daily limit hit (resets in {h:.1f}h). {'Checkpoint saved — run again later.' if use_checkpoint else ''}")
                        sys.exit(0)
                    else:
                        # Burst limit — respect Retry-After, then double the base delay
                        new_delay = min(base_delay * 2, DELAY_CAP)
                        tqdm.write(f"  [burst 429] waiting {retry_after}s, base delay {base_delay:.1f}s → {new_delay:.1f}s")
                        time.sleep(retry_after)
                        base_delay = new_delay
                        bar.set_postfix(releases=found_count, delay=f"{base_delay:.1f}s")

            releases.extend(recent)
            checked_ids.add(artist["id"])
            found_count += len(recent)

            for r in recent:
                tqdm.write(f"  + [{r['album_type']}] {artist['name']} — {r['album_name']} ({r['release_date'].isoformat()})")

            if use_checkpoint:
                _save_checkpoint(since_date, include_groups, artists, checked_ids, releases)

    albums = [r for r in releases if r["album_type"] != "single"]
    singles = [r for r in releases if r["album_type"] == "single"]

    print(f"\nFound {len(albums)} album(s) and {len(singles)} single(s) across {len(artists)} artists.")

    today_str = date.today().isoformat()
    total = len(albums) + len(singles)
    subject = f"New Releases: {total} release(s) this week — {today_str}"
    html_body = build_html_email(albums, singles, len(artists), args.singles)

    if args.dry_run:
        print(f"\nSubject: {subject}\n")
        print(html_body)
        _clear_checkpoint()
        return

    try:
        send_email(subject, html_body)
        print(f"Email sent to {os.environ['GMAIL_RECIPIENT']}")
        _clear_checkpoint()
        _clear_quota_cooldown()
    except smtplib.SMTPAuthenticationError:
        print("ERROR: Gmail authentication failed. Check GMAIL_APP_PASSWORD in your .env.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
