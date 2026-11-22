"""KROVEX Official Spotify Web API Client.

Provides authenticated metadata extraction for Spotify tracks, albums,
and playlists using the Spotify Web API (Client Credentials Flow).
Never exposes credentials or secrets in logs or responses.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from bot.utils.logger import get_logger

logger = get_logger("death_bot.services.spotify_client")


class SpotifyClient:
    """Authenticated Spotify Web API client with automatic token refreshing and caching."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> None:
        self.client_id = (client_id or os.getenv("SPOTIFY_CLIENT_ID", "")).strip() or None
        self.client_secret = (client_secret or os.getenv("SPOTIFY_CLIENT_SECRET", "")).strip() or None

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @property
    def is_configured(self) -> bool:
        """Return True if Spotify client credentials are available."""
        return bool(self.client_id and self.client_secret)

    def _get_access_token(self) -> Optional[str]:
        """Obtain or return cached Spotify Web API access token."""
        if not self.is_configured:
            return None

        # Return cached token if valid for at least another 60 seconds
        if self._token and time.time() < (self._token_expires_at - 60):
            return self._token

        try:
            auth_str = f"{self.client_id}:{self.client_secret}"
            b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

            token_url = "https://accounts.spotify.com/api/token"
            data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")

            req = urllib.request.Request(
                token_url,
                data=data,
                headers={
                    "Authorization": f"Basic {b64_auth}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "KROVEX-DiscordBot/1.0",
                },
            )

            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read().decode("utf-8"))
                    self._token = body.get("access_token")
                    expires_in = int(body.get("expires_in", 3600))
                    self._token_expires_at = time.time() + expires_in
                    logger.info("Successfully refreshed Spotify API client credentials token.")
                    return self._token
        except Exception as err:
            logger.warning("Failed to obtain Spotify access token: %s", err)

        return None

    def _make_api_request(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Make an authenticated GET request to the Spotify Web API."""
        token = self._get_access_token()
        if not token:
            return None

        url = f"https://api.spotify.com/v1/{endpoint.lstrip('/')}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "KROVEX-DiscordBot/1.0",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as err:
            logger.warning("Spotify API request failed for endpoint '%s': %s", endpoint, err)

        return None

    def get_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Fetch high-precision track metadata using official Spotify API."""
        data = self._make_api_request(f"tracks/{track_id}")
        if not data or not data.get("name"):
            return None

        title = data["name"]
        artists = [a.get("name") for a in data.get("artists", []) if a.get("name")]
        artist_str = ", ".join(artists) if artists else ""
        album_name = data.get("album", {}).get("name")

        images = data.get("album", {}).get("images", [])
        thumbnail = images[0].get("url") if images else None

        duration_ms = data.get("duration_ms", 0)
        duration_sec = duration_ms // 1000 if duration_ms else 0

        isrc = data.get("external_ids", {}).get("isrc")
        query = f"{title} {artist_str}".strip() if artist_str else title

        return {
            "type": "track",
            "id": track_id,
            "title": title,
            "artist": artist_str,
            "album": album_name,
            "query": query,
            "thumbnail": thumbnail,
            "duration": duration_sec,
            "uri": f"spotify:track:{track_id}",
            "isrc": isrc,
            "source": "spotify_api",
        }

    def search_track(self, query: str) -> Optional[Dict[str, Any]]:
        """Search Spotify for a track by name or keywords and return metadata."""
        if not query or not query.strip():
            return None
        encoded = urllib.parse.quote(query.strip())
        data = self._make_api_request(f"search?q={encoded}&type=track&limit=1")
        if not data:
            return None
        items = data.get("tracks", {}).get("items", [])
        if not items:
            return None
        track = items[0]
        track_id = track.get("id", "")
        title = track.get("name", "")
        artists = [a.get("name") for a in track.get("artists", []) if a.get("name")]
        artist_str = ", ".join(artists) if artists else ""
        album_name = track.get("album", {}).get("name")
        images = track.get("album", {}).get("images", [])
        thumbnail = images[0].get("url") if images else None
        duration_ms = track.get("duration_ms", 0)
        duration_sec = duration_ms // 1000 if duration_ms else 0
        resolved_q = f"{title} {artist_str}".strip() if artist_str else title

        return {
            "type": "track",
            "id": track_id,
            "title": title,
            "artist": artist_str,
            "album": album_name,
            "query": resolved_q,
            "thumbnail": thumbnail,
            "duration": duration_sec,
            "uri": f"spotify:track:{track_id}",
            "source": "spotify_api",
        }

    def get_album(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Fetch complete album metadata and track list using official Spotify API."""
        data = self._make_api_request(f"albums/{album_id}")
        if not data or not data.get("name"):
            return None

        name = data["name"]
        artists = [a.get("name") for a in data.get("artists", []) if a.get("name")]
        artist_str = ", ".join(artists) if artists else ""

        images = data.get("images", [])
        thumbnail = images[0].get("url") if images else None

        raw_tracks = data.get("tracks", {}).get("items", [])
        tracks: List[Dict[str, Any]] = []

        for idx, t in enumerate(raw_tracks):
            t_title = t.get("name")
            t_artists = [a.get("name") for a in t.get("artists", []) if a.get("name")]
            t_artist = ", ".join(t_artists) if t_artists else artist_str
            t_dur = t.get("duration_ms", 0) // 1000 if t.get("duration_ms") else 0
            t_uri = t.get("uri") or f"spotify:track:{t.get('id', '')}"

            if t_title:
                q = f"{t_title} {t_artist}".strip() if t_artist else t_title
                tracks.append({
                    "title": t_title,
                    "artist": t_artist,
                    "album": name,
                    "duration": t_dur,
                    "uri": t_uri,
                    "order": idx,
                    "query": q,
                })

        return {
            "type": "album",
            "id": album_id,
            "name": name,
            "author": artist_str,
            "thumbnail": thumbnail,
            "track_count": len(tracks),
            "tracks": tracks,
            "query": tracks[0]["query"] if tracks else name,
            "source": "spotify_api",
        }

    def get_playlist(self, playlist_id: str) -> Optional[Dict[str, Any]]:
        """Fetch playlist metadata and track items using official Spotify API."""
        data = self._make_api_request(f"playlists/{playlist_id}")
        if not data or not data.get("name"):
            return None

        name = data["name"]
        owner = data.get("owner", {}).get("display_name", "")

        images = data.get("images", [])
        thumbnail = images[0].get("url") if images else None

        raw_items = data.get("tracks", {}).get("items", [])
        tracks: List[Dict[str, Any]] = []

        for idx, item in enumerate(raw_items):
            t = item.get("track")
            if not t or not t.get("name"):
                continue

            t_title = t.get("name")
            t_artists = [a.get("name") for a in t.get("artists", []) if a.get("name")]
            t_artist = ", ".join(t_artists) if t_artists else ""
            t_album = t.get("album", {}).get("name")
            t_dur = t.get("duration_ms", 0) // 1000 if t.get("duration_ms") else 0
            t_uri = t.get("uri") or f"spotify:track:{t.get('id', '')}"

            q = f"{t_title} {t_artist}".strip() if t_artist else t_title
            tracks.append({
                "title": t_title,
                "artist": t_artist,
                "album": t_album,
                "duration": t_dur,
                "uri": t_uri,
                "order": idx,
                "query": q,
            })

        return {
            "type": "playlist",
            "id": playlist_id,
            "name": name,
            "author": owner,
            "thumbnail": thumbnail,
            "track_count": len(tracks),
            "tracks": tracks,
            "query": tracks[0]["query"] if tracks else name,
            "source": "spotify_api",
        }
