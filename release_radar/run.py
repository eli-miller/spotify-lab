#!/usr/bin/env python3
import os
import sys
import smtplib
import argparse
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
import spotipy

# Allow running as `python release_radar/run.py` from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.spotify_auth import get_spotify_client

SCOPE = "playlist-read-private"


def find_release_radar_playlist(sp: spotipy.Spotify) -> str:
    # Spotify no longer exposes algorithmic playlists via current_user_playlists,
    # so we require the ID to be set explicitly in .env.
    playlist_id = os.environ.get("RELEASE_RADAR_PLAYLIST_ID")
    if playlist_id:
        return playlist_id

    # Fallback: search the library (works if Spotify re-adds API support)
    offset = 0
    while True:
        results = sp.current_user_playlists(limit=50, offset=offset)
        for playlist in results["items"]:
            if playlist["name"] == "Release Radar" and playlist["owner"]["id"] == "spotify":
                return playlist["id"]
        if results["next"] is None:
            break
        offset += 50
    raise RuntimeError(
        "Release Radar playlist not found. "
        "Set RELEASE_RADAR_PLAYLIST_ID in your .env — find the ID from the playlist URL at open.spotify.com."
    )


def fetch_all_playlist_tracks(sp: spotipy.Spotify, playlist_id: str) -> list[dict]:
    tracks = []
    offset = 0
    while True:
        results = sp._get(f"playlists/{playlist_id}/items", limit=100, offset=offset)
        for item in results["items"]:
            track = item.get("item")
            if track and track.get("type") == "track" and not track.get("is_local"):
                tracks.append(item)
        offset += len(results["items"])
        if results["next"] is None:
            break
    return tracks


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


def is_within_last_7_days(release_date_obj: date) -> bool:
    today = date.today()
    return today - timedelta(days=7) <= release_date_obj <= today


def filter_tracks(raw_tracks: list[dict]) -> list[dict]:
    filtered = []
    for item in raw_tracks:
        album = item["item"].get("album", {})
        if album.get("album_type") != "album":
            continue
        parsed = parse_release_date(
            album.get("release_date", ""),
            album.get("release_date_precision", ""),
        )
        if parsed and is_within_last_7_days(parsed):
            filtered.append(item)
    return filtered


def deduplicate_by_album(filtered_tracks: list[dict]) -> list[dict]:
    seen = {}
    for item in filtered_tracks:
        album = item["item"]["album"]
        album_id = album["id"]
        if album_id not in seen:
            seen[album_id] = album
    return list(seen.values())


def build_html_email(albums: list[dict]) -> str:
    if not albums:
        return (
            "<html><body>"
            "<h2>Release Radar — New Albums This Week</h2>"
            "<p>No new full albums in your Release Radar this week.</p>"
            "<small>Filtered from your Spotify Release Radar</small>"
            "</body></html>"
        )

    items_html = ""
    for album in albums:
        name = album["name"]
        url = album["external_urls"]["spotify"]
        artists = ", ".join(a["name"] for a in album["artists"])
        release_date = album["release_date"]
        items_html += (
            f'<div style="margin-bottom:16px;">'
            f'<strong><a href="{url}" style="color:#1DB954;text-decoration:none;">{name}</a></strong><br>'
            f'{artists}<br>'
            f'<small style="color:#888;">Released: {release_date}</small>'
            f'</div>'
        )

    return (
        "<html><body style='font-family:sans-serif;max-width:600px;margin:auto;padding:20px;'>"
        "<h2 style='border-bottom:1px solid #eee;padding-bottom:8px;'>Release Radar — New Albums This Week</h2>"
        f"{items_html}"
        "<hr style='margin-top:24px;'>"
        "<small style='color:#aaa;'>Filtered from your Spotify Release Radar</small>"
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print email HTML instead of sending")
    args = parser.parse_args()

    load_dotenv()

    try:
        sp = get_spotify_client(SCOPE)
    except spotipy.oauth2.SpotifyOauthError as e:
        print(f"ERROR: Spotify auth failed — {e}", file=sys.stderr)
        print("Re-run on Mac to re-authenticate, then copy shared/.spotify_cache to the Pi.", file=sys.stderr)
        sys.exit(1)

    try:
        playlist_id = find_release_radar_playlist(sp)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    raw_tracks = fetch_all_playlist_tracks(sp, playlist_id)
    filtered = filter_tracks(raw_tracks)
    albums = deduplicate_by_album(filtered)

    print(f"Release Radar: {len(raw_tracks)} tracks → {len(albums)} new album(s)")

    today_str = date.today().isoformat()
    subject = f"Release Radar: {len(albums)} new album(s) — {today_str}"
    html_body = build_html_email(albums)

    if args.dry_run:
        print(f"\nSubject: {subject}\n")
        print(html_body)
        return

    try:
        send_email(subject, html_body)
        print(f"Email sent to {os.environ['GMAIL_RECIPIENT']}")
    except smtplib.SMTPAuthenticationError:
        print("ERROR: Gmail authentication failed. Check GMAIL_APP_PASSWORD in your .env.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
