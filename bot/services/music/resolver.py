"""Intelligent song resolution, yt-dlp extraction, and audio ranking engine."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yt_dlp

from bot.services.music.source import AudioSourceInfo
from bot.services.music.spotify_client import SpotifyClient
from bot.utils.logger import get_logger

logger = get_logger("death_bot.music.resolver")

# Unwanted descriptors to penalize when not explicitly requested by user
UNWANTED_PATTERNS = [
    r"\bremix\b",
    r"\bnightcore\b",
    r"\bslowed\b",
    r"\bsped\s*up\b",
    r"\bcover\b",
    r"\blive\b",
    r"\binstrumental\b",
    r"\bkaraoke\b",
    r"\b8d\s*(audio)?\b",
    r"\btribute\b",
    r"\bparody\b",
]

OFFICIAL_PATTERNS = [
    r"\bofficial\s*audio\b",
    r"\bofficial\s*music\s*video\b",
    r"\bofficial\s*video\b",
    r"\bofficial\s*lyric\s*video\b",
    r"\bvisualizer\b",
    r"- topic\b",
]

URL_REGEX = re.compile(
    r"^(https?://)?([a-zA-Z0-9_-]+\.)*(youtube\.com|youtu\.be|soundcloud\.com|spotify\.com)/.+",
    re.IGNORECASE,
)


class ResolverError(Exception):
    """Base error for audio resolution."""
    pass


class TrackNotFoundError(ResolverError):
    """Raised when no matching tracks could be found."""
    pass


class LowConfidenceError(ResolverError):
    """Raised when matches fall below minimum reliability confidence."""
    pass


class ExtractionTimeoutError(ResolverError):
    """Raised when metadata extraction exceeds timeout threshold."""
    pass


class YouTubeBotChallengeError(ResolverError):
    """Raised when YouTube issues a bot verification / datacenter anti-bot challenge."""
    pass


class AudioResolver:
    """Intelligent audio resolver utilizing yt-dlp with non-blocking concurrency and ranking."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        cookie_path: Optional[str] = None,
        cookies_content: Optional[str] = None,
        po_token: Optional[str] = None,
        visitor_data: Optional[str] = None,
    ) -> None:
        self.spotify_client = SpotifyClient(client_id=client_id, client_secret=client_secret)
        self.cookie_path = cookie_path
        self.cookies_content = cookies_content
        self.po_token = po_token
        self.visitor_data = visitor_data
        self._temp_cookie_file: Optional[str] = None

        self.ydl_opts: Dict[str, Any] = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "default_search": "ytsearch2",
            "source_address": "0.0.0.0",
            "extract_flat": False,
            "skip_download": True,
            "socket_timeout": 6,
            "retries": 0,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "web"],
                    "skip": ["translated_subs"]
                }
            },
        }

    def _validate_and_get_cookie_file(self) -> Optional[str]:
        """Validate or create cookie file path safely without exposing contents."""
        # 1. Directly configured path
        if self.cookie_path:
            p = Path(self.cookie_path).resolve()
            if p.is_file() and p.stat().st_size > 0:
                logger.info("Using configured YouTube cookie file (%d bytes).", p.stat().st_size)
                return str(p)

        # 2. Project root cookies.txt
        root_cookie = Path(__file__).resolve().parent.parent.parent.parent / "cookies.txt"
        if root_cookie.is_file() and root_cookie.stat().st_size > 0:
            logger.info("Detected project root cookies.txt (%d bytes).", root_cookie.stat().st_size)
            return str(root_cookie)

        # 3. Cookies content string (e.g. from environment variable)
        if self.cookies_content and self.cookies_content.strip():
            if not self._temp_cookie_file or not os.path.exists(self._temp_cookie_file):
                try:
                    tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8")
                    tmp.write(self.cookies_content.strip())
                    tmp.flush()
                    tmp.close()
                    # Secure permissions on POSIX systems
                    try:
                        os.chmod(tmp.name, 0o600)
                    except Exception:
                        pass
                    self._temp_cookie_file = tmp.name
                    logger.info("Wrote secure temporary cookie file (%d bytes).", len(self.cookies_content.encode("utf-8")))
                except Exception as exc:
                    logger.warning("Failed to create temporary cookie file: %s", exc)
                    return None
            return self._temp_cookie_file

        return None

    def _configure_po_token(self, ydl_opts: Dict[str, Any]) -> None:
        """Inject PO Token parameters into extractor args safely without exposing token in logs."""
        if not self.po_token or not self.po_token.strip():
            return

        token_clean = self.po_token.strip()
        vis_clean = (self.visitor_data or "").strip()

        if "extractor_args" not in ydl_opts:
            ydl_opts["extractor_args"] = {}
        if "youtube" not in ydl_opts["extractor_args"]:
            ydl_opts["extractor_args"]["youtube"] = {}

        # Format po_token for yt-dlp: web+<visitor_data>+<token> or web+<token>
        if vis_clean:
            formatted_po = f"web+{vis_clean}+{token_clean}"
        else:
            formatted_po = f"web+{token_clean}"

        ydl_opts["extractor_args"]["youtube"]["po_token"] = [formatted_po]
        logger.info("Configured YouTube PO Token provider integration.")

    def _search_audius(self, query: str) -> Optional[Dict[str, Any]]:
        """Search Audius decentralized streaming network as a resilient fallback."""
        try:
            encoded_q = urllib.parse.quote(query)
            api_url = f"https://discoveryprovider.audius.co/v1/tracks/search?query={encoded_q}&app_name=KROVEX"
            req = urllib.request.Request(api_url, headers={"User-Agent": "KROVEX-Bot/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            tracks = data.get("data", [])
            if not tracks:
                return None

            entries: List[Dict[str, Any]] = []
            for t in tracks[:5]:
                track_id = t.get("id")
                title = t.get("title")
                user = t.get("user", {})
                artist = user.get("name") or user.get("handle") or "Audius Artist"
                duration = t.get("duration", 0)
                artwork = t.get("artwork", {})
                thumbnail = artwork.get("1000x1000") or artwork.get("480x480") or artwork.get("150x150")

                if track_id and title:
                    stream_url = f"https://discoveryprovider.audius.co/v1/tracks/{track_id}/stream?app_name=KROVEX"
                    webpage_url = f"https://audius.co/tracks/{track_id}"
                    entries.append({
                        "id": str(track_id),
                        "title": title,
                        "url": stream_url,
                        "webpage_url": webpage_url,
                        "uploader": artist,
                        "channel": artist,
                        "duration": duration,
                        "thumbnail": thumbnail,
                        "extractor": "audius",
                    })

            if entries:
                return {"_type": "playlist", "entries": entries}
        except Exception as exc:
            logger.debug("Audius search fallback failed for '%s': %s", query, exc)
        return None

    def _search_jamendo(self, query: str) -> Optional[Dict[str, Any]]:
        """Search Jamendo open music database as a resilient fallback."""
        try:
            encoded_q = urllib.parse.quote(query)
            api_url = f"https://api.jamendo.com/v3.0/tracks/?client_id=56d30c95&format=json&limit=5&namesearch={encoded_q}&include=musicinfo"
            req = urllib.request.Request(api_url, headers={"User-Agent": "KROVEX-Bot/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            results = data.get("results", [])
            if not results:
                return None

            entries: List[Dict[str, Any]] = []
            for t in results:
                title = t.get("name")
                artist = t.get("artist_name") or "Jamendo Artist"
                duration = t.get("duration", 0)
                stream_url = t.get("audio")
                webpage_url = t.get("shareurl") or t.get("shorturl")
                thumbnail = t.get("image")

                if title and stream_url:
                    entries.append({
                        "id": str(t.get("id")),
                        "title": title,
                        "url": stream_url,
                        "webpage_url": webpage_url or stream_url,
                        "uploader": artist,
                        "channel": artist,
                        "duration": duration,
                        "thumbnail": thumbnail,
                        "extractor": "jamendo",
                    })

            if entries:
                return {"_type": "playlist", "entries": entries}
        except Exception as exc:
            logger.debug("Jamendo search fallback failed for '%s': %s", query, exc)
        return None

    @staticmethod
    def is_url(query: str) -> bool:
        """Check if query is a direct web URL."""
        return bool(URL_REGEX.match(query.strip()))

    @staticmethod
    def calculate_match_score(query: str, title: str, uploader: str, channel: str) -> float:
        """Compute match confidence score (0.0 to 1.0) evaluating relevance and quality."""
        q_clean = query.lower()
        t_clean = title.lower()
        u_clean = f"{uploader} {channel}".lower()

        score = 0.5  # Base score

        # 1. Title keyword overlap
        q_words = set(re.findall(r"\w+", q_clean))
        t_words = set(re.findall(r"\w+", t_clean))
        if q_words:
            overlap = len(q_words.intersection(t_words)) / len(q_words)
            score += overlap * 0.4

        # 2. Artist/channel relevance
        for word in q_words:
            if word in u_clean:
                score += 0.1
                break

        # 3. Official indicators boost
        for pattern in OFFICIAL_PATTERNS:
            if re.search(pattern, t_clean) or re.search(pattern, u_clean):
                score += 0.15
                break

        # 4. Penalty for unwanted variants (unless user explicitly searched for them)
        for pattern in UNWANTED_PATTERNS:
            has_in_query = bool(re.search(pattern, q_clean))
            has_in_title = bool(re.search(pattern, t_clean))
            if has_in_title and not has_in_query:
                score -= 0.35  # Heavily penalize unwanted remix/live/nightcore

        return max(0.0, min(1.0, score))

    @staticmethod
    def calculate_spotify_match_score(
        spotify_meta: Dict[str, Any],
        candidate_title: str,
        candidate_uploader: str,
        candidate_channel: str,
        candidate_duration: int,
    ) -> float:
        """Calculate match confidence (0.0 to 1.0) between Spotify metadata and candidate audio stream.

        Evaluates title keyword overlap, artist presence, duration tolerance,
        remix differentiation, and penalizes live/cover/karaoke/instrumental versions
        when not requested by the original Spotify metadata.
        """
        sp_title = (spotify_meta.get("title") or "").lower()
        sp_artist = (spotify_meta.get("artist") or "").lower()
        sp_duration = spotify_meta.get("duration") or 0

        c_title = candidate_title.lower()
        c_uploader = f"{candidate_uploader} {candidate_channel}".lower()

        score = 0.0  # Base additive score starting at zero

        # 1. Title keyword overlap
        sp_words = set(re.findall(r"\w+", sp_title))
        c_words = set(re.findall(r"\w+", c_title))
        if sp_words:
            overlap = len(sp_words.intersection(c_words)) / len(sp_words)
            score += overlap * 0.40
            # Exact title contained
            if sp_title in c_title:
                score += 0.15

        # 2. Artist match
        if sp_artist:
            sp_artist_words = set(re.findall(r"\w+", sp_artist))
            if any(w in c_uploader or w in c_title for w in sp_artist_words):
                score += 0.25

        # 3. Official indicators boost
        for pattern in OFFICIAL_PATTERNS:
            if re.search(pattern, c_title) or re.search(pattern, c_uploader):
                score += 0.10
                break

        # 4. Duration tolerance check (critical for rejecting loops, previews, compilations)
        if sp_duration > 0 and candidate_duration > 0:
            # Reject preview snippets (e.g. 30-second SoundCloud previews for full songs)
            if candidate_duration <= 35 and sp_duration > 60:
                score -= 0.60
            diff = abs(candidate_duration - sp_duration)
            if diff <= 6:
                score += 0.10  # Near perfect duration match
            elif diff <= 25:
                score += 0.05  # Acceptable tolerance
            elif diff > 120:
                score -= 0.50  # Far too long or short (compilations, 1-hour loops)
            elif diff > 45:
                score -= 0.25

        # 5. Remix mismatch detection
        is_sp_remix = bool(re.search(r"\bremix\b", sp_title))
        is_c_remix = bool(re.search(r"\bremix\b", c_title))
        if is_c_remix and not is_sp_remix:
            score -= 0.45  # User wants original studio track, candidate is remix
        elif is_sp_remix and is_c_remix:
            score += 0.15  # Both are remix

        # 6. Live / Cover / Karaoke / Instrumental mismatch detection
        for pattern in [r"\bcover\b", r"\blive\b", r"\binstrumental\b", r"\bkaraoke\b", r"\bnightcore\b", r"\btribute\b"]:
            in_sp = bool(re.search(pattern, sp_title))
            in_c = bool(re.search(pattern, c_title))
            if in_c and not in_sp:
                score -= 0.40

        return max(0.0, min(1.0, score))

    @staticmethod
    def extract_spotify_metadata(url: str, spotify_client: Optional[SpotifyClient] = None) -> Dict[str, Any]:
        """Extract metadata for Spotify track, album, or playlist with Web API priority and scraping fallback."""
        client = spotify_client or SpotifyClient()

        track_match = re.search(
            r"https?://(?:open\.)?spotify\.com/(?:intl-[a-z]{2}/)?track/([a-zA-Z0-9]+)",
            url,
            re.IGNORECASE,
        )
        album_match = re.search(
            r"https?://(?:open\.)?spotify\.com/(?:intl-[a-z]{2}/)?(album|playlist)/([a-zA-Z0-9]+)",
            url,
            re.IGNORECASE,
        )

        if track_match:
            track_id = track_match.group(1)

            # 1. Primary path: Official Spotify Web API if configured
            if client.is_configured:
                api_res = client.get_track(track_id)
                if api_res and api_res.get("title"):
                    return api_res

            # 2. Resilient fallback: Next.js embed pageProps
            embed_url = f"https://open.spotify.com/embed/track/{track_id}"
            try:
                req = urllib.request.Request(embed_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
                next_data = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">([^<]+)</script>', html)
                if next_data:
                    data = json.loads(next_data.group(1))
                    entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                    title = entity.get("title") or entity.get("name")
                    artists = [a.get("name") for a in entity.get("artists", []) if a.get("name")]
                    artist_str = ", ".join(artists) if artists else entity.get("subtitle", "")
                    album_name = entity.get("album", {}).get("name") or entity.get("albumTitle")
                    images = entity.get("visualIdentity", {}).get("image", [])
                    thumbnail = images[0].get("url") if images else None
                    duration = entity.get("duration", 0) // 1000 if entity.get("duration") else 0
                    if title:
                        return {
                            "type": "track",
                            "id": track_id,
                            "title": title,
                            "artist": artist_str,
                            "album": album_name,
                            "query": f"{title} {artist_str}".strip(),
                            "thumbnail": thumbnail,
                            "duration": duration,
                            "uri": f"spotify:track:{track_id}",
                        }
            except Exception:
                pass

            # 3. Last-resort fallback: oEmbed
            try:
                oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(url)}"
                req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    return {
                        "type": "track",
                        "id": track_id,
                        "title": data.get("title"),
                        "artist": "",
                        "album": None,
                        "query": data.get("title"),
                        "thumbnail": data.get("thumbnail_url"),
                        "duration": 0,
                        "uri": f"spotify:track:{track_id}",
                    }
            except Exception:
                pass

        elif album_match:
            kind = album_match.group(1).lower()
            coll_id = album_match.group(2)

            # 1. Primary path: Official Spotify Web API if configured
            if client.is_configured:
                if kind == "album":
                    api_res = client.get_album(coll_id)
                    if api_res and api_res.get("tracks"):
                        return api_res
                elif kind == "playlist":
                    api_res = client.get_playlist(coll_id)
                    if api_res and api_res.get("tracks"):
                        return api_res

            # 2. Resilient fallback: Next.js embed pageProps
            embed_url = f"https://open.spotify.com/embed/{kind}/{coll_id}"
            try:
                req = urllib.request.Request(embed_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
                next_data = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">([^<]+)</script>', html)
                if next_data:
                    data = json.loads(next_data.group(1))
                    entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                    name = entity.get("name") or entity.get("title")
                    images = entity.get("visualIdentity", {}).get("image", [])
                    thumbnail = images[0].get("url") if images else None
                    author = entity.get("subtitle") or entity.get("byline") or ""
                    track_list = entity.get("trackList", [])
                    tracks = []
                    for idx, t in enumerate(track_list):
                        t_title = t.get("title")
                        t_artist = t.get("subtitle") or author
                        t_dur = t.get("duration", 0) // 1000 if t.get("duration") else 0
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
                        "type": kind,
                        "id": coll_id,
                        "name": name,
                        "author": author,
                        "thumbnail": thumbnail,
                        "track_count": len(tracks),
                        "tracks": tracks,
                        "query": tracks[0]["query"] if tracks else name,
                    }
            except Exception:
                pass

        return {}

    async def resolve_spotify_collection(self, query: str) -> Optional[Dict[str, Any]]:
        """Extract all track queries for a Spotify album or playlist asynchronously."""
        if not ("spotify.com" in query.lower() and ("album" in query.lower() or "playlist" in query.lower())):
            return None
        loop = asyncio.get_running_loop()
        meta = await loop.run_in_executor(None, self.extract_spotify_metadata, query, self.spotify_client)
        if meta and meta.get("tracks"):
            return meta
        return None

    def _extract_sync(self, query: str, playlist: bool = False) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """Synchronous yt-dlp extraction executed inside worker thread with Spotify bridge, authentication, and intelligent fallback."""
        opts = dict(self.ydl_opts)
        opts["noplaylist"] = not playlist

        cookie_file = self._validate_and_get_cookie_file()
        if cookie_file:
            opts["cookiefile"] = cookie_file

        self._configure_po_token(opts)

        spotify_meta = None

        if self.is_url(query) and "spotify.com" in query.lower():
            spotify_meta = self.extract_spotify_metadata(query, self.spotify_client)
            if spotify_meta and spotify_meta.get("query"):
                target = f"ytsearch2:{spotify_meta['query']}"
            else:
                target = query.strip()
        elif self.is_url(query):
            target = query.strip()
        else:
            clean_q = re.sub(r"\bspotify\b", "", query, flags=re.IGNORECASE).strip()
            # If Spotify client is configured, search Spotify API first for precise track metadata
            if self.spotify_client.is_configured:
                sp_track = self.spotify_client.search_track(clean_q or query.strip())
                if sp_track and sp_track.get("query"):
                    spotify_meta = sp_track
                    target = f"ytsearch2:{spotify_meta['query']}"
                else:
                    target = f"ytsearch2:{clean_q or query.strip()}"
            else:
                target = f"ytsearch2:{clean_q or query.strip()}"

        # Attempt YouTube extraction with bounded retry
        bot_challenge_detected = False
        last_yt_error: Optional[Exception] = None
        max_attempts = 2

        for attempt in range(1, max_attempts + 1):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(target, download=False)
                    if info:
                        return info, spotify_meta
            except Exception as yt_err:
                last_yt_error = yt_err
                err_msg = str(yt_err).lower()
                if (
                    "sign in to confirm you're not a bot" in err_msg
                    or "bot verification" in err_msg
                    or "confirm you’re not a bot" in err_msg
                    or "429" in err_msg
                    or "too many requests" in err_msg
                ):
                    bot_challenge_detected = True
                    logger.warning("YouTube anti-bot challenge detected on attempt %d: %s", attempt, yt_err)
                    break
                if attempt < max_attempts:
                    time.sleep(0.5)

        # Multi-provider resilient fallback cascade (SoundCloud -> Audius -> Jamendo)
        sc_target = spotify_meta["query"] if (spotify_meta and spotify_meta.get("query")) else (clean_q if not self.is_url(query) else query.strip())

        # 1. Fallback: SoundCloud
        try:
            logger.info("Attempting SoundCloud fallback for '%s'...", sc_target)
            sc_opts = dict(self.ydl_opts)
            sc_opts["noplaylist"] = not playlist
            with yt_dlp.YoutubeDL(sc_opts) as sc_ydl:
                sc_info = sc_ydl.extract_info(f"scsearch5:{sc_target}", download=False)
                if sc_info and "entries" in sc_info and sc_info["entries"]:
                    valid_sc = [e for e in sc_info["entries"] if e]
                    if valid_sc:
                        # Check match score for top candidate
                        top_sc = valid_sc[0]
                        sc_title = top_sc.get("title") or ""
                        sc_uploader = top_sc.get("uploader") or ""
                        sc_channel = top_sc.get("channel") or ""
                        match_score = self.calculate_match_score(sc_target, sc_title, sc_uploader, sc_channel)
                        if match_score >= 0.35:
                            logger.info("SoundCloud resolved matching candidate '%s' (score: %.2f)", sc_title, match_score)
                            return sc_info, spotify_meta
        except Exception as sc_err:
            logger.warning("SoundCloud fallback failed for '%s': %s", sc_target, sc_err)

        # 2. Fallback: Audius
        try:
            logger.info("Attempting Audius fallback for '%s'...", sc_target)
            audius_info = self._search_audius(sc_target)
            if audius_info and "entries" in audius_info and audius_info["entries"]:
                top_aud = audius_info["entries"][0]
                aud_title = top_aud.get("title") or ""
                aud_uploader = top_aud.get("uploader") or ""
                match_score = self.calculate_match_score(sc_target, aud_title, aud_uploader, "")
                if match_score >= 0.35:
                    logger.info("Audius resolved matching candidate '%s' (score: %.2f)", aud_title, match_score)
                    return audius_info, spotify_meta
        except Exception as aud_err:
            logger.warning("Audius fallback failed for '%s': %s", sc_target, aud_err)

        # 3. Fallback: Jamendo
        try:
            logger.info("Attempting Jamendo fallback for '%s'...", sc_target)
            jam_info = self._search_jamendo(sc_target)
            if jam_info and "entries" in jam_info and jam_info["entries"]:
                top_jam = jam_info["entries"][0]
                jam_title = top_jam.get("title") or ""
                jam_uploader = top_jam.get("uploader") or ""
                match_score = self.calculate_match_score(sc_target, jam_title, jam_uploader, "")
                if match_score >= 0.35:
                    logger.info("Jamendo resolved matching candidate '%s' (score: %.2f)", jam_title, match_score)
                    return jam_info, spotify_meta
        except Exception as jam_err:
            logger.warning("Jamendo fallback failed for '%s': %s", sc_target, jam_err)

        if bot_challenge_detected:
            raise YouTubeBotChallengeError(
                f"YouTube requested bot verification ('Sign in to confirm you're not a bot'). "
                f"Fallback providers (SoundCloud, Audius, Jamendo) did not have a matching source for '{query}'. "
                f"Please configure YouTube cookies or a PO token in the environment to unlock YouTube playback on cloud servers."
            )

        if last_yt_error:
            raise last_yt_error

        raise TrackNotFoundError(f"Could not resolve any audio candidates for '{query}'.")

    async def resolve(
        self,
        query: str,
        timeout: float = 35.0,
        min_confidence: float = 0.35,
    ) -> Tuple[AudioSourceInfo, List[AudioSourceInfo]]:
        """Resolve a search query or URL asynchronously.

        Returns:
            Tuple of (primary_candidate, all_ranked_candidates)
        """
        try:
            loop = asyncio.get_running_loop()
            raw_res = await asyncio.wait_for(
                loop.run_in_executor(None, self._extract_sync, query, False),
                timeout=timeout,
            )
            if isinstance(raw_res, tuple) and len(raw_res) == 2:
                info, spotify_meta = raw_res
            else:
                info, spotify_meta = raw_res, None
        except asyncio.TimeoutError as err:
            logger.error("Extraction timed out for query: %s", query)
            raise ExtractionTimeoutError(f"Search timed out after {timeout:.0f} seconds.") from err
        except Exception as err:
            logger.error("yt-dlp extraction failed for '%s': %s", query, err)
            raise ResolverError(f"Could not extract audio metadata: {err}") from err

        if not info:
            raise TrackNotFoundError(f"No results found for `{query}`.")

        # Process entries
        entries: List[Dict[str, Any]] = []
        if "entries" in info and info["entries"]:
            entries = [e for e in info["entries"] if e]
        else:
            entries = [info]

        if not entries:
            raise TrackNotFoundError(f"No valid tracks found for `{query}`.")

        candidates: List[AudioSourceInfo] = []
        for entry in entries:
            stream_url = entry.get("url")
            webpage = entry.get("webpage_url") or entry.get("original_url") or query
            title = entry.get("title") or "Unknown Track"
            uploader = entry.get("uploader") or entry.get("channel") or "Unknown Artist"
            channel = entry.get("channel") or ""
            duration = int(entry.get("duration") or 0)
            thumbnail = entry.get("thumbnail")
            is_live = bool(entry.get("is_live", False))
            views = entry.get("view_count")

            # Determine audio provider
            extractor = (entry.get("extractor") or "").lower()
            if "youtube.com" in webpage or "youtu.be" in webpage or "youtube" in extractor:
                provider = "youtube"
            elif "soundcloud.com" in webpage or "soundcloud" in extractor:
                provider = "soundcloud"
            elif "audius" in webpage or "audius" in extractor:
                provider = "audius"
            elif "jamendo" in webpage or "jamendo" in extractor:
                provider = "jamendo"
            else:
                provider = "direct"

            # Calculate confidence score
            if spotify_meta and spotify_meta.get("type") == "track":
                score = self.calculate_spotify_match_score(
                    spotify_meta=spotify_meta,
                    candidate_title=title,
                    candidate_uploader=uploader,
                    candidate_channel=channel,
                    candidate_duration=duration,
                )
            elif self.is_url(query):
                score = 1.0  # Direct non-Spotify URLs are exact matches
            else:
                score = self.calculate_match_score(query, title, uploader, channel)

            candidates.append(
                AudioSourceInfo(
                    title=title,
                    url=stream_url or webpage,
                    webpage_url=webpage,
                    duration_seconds=duration,
                    uploader=uploader,
                    thumbnail_url=thumbnail,
                    is_live=is_live,
                    views=views,
                    confidence_score=score,
                    source_provider=provider,
                    original_source="spotify" if (spotify_meta and spotify_meta.get("type") == "track") else provider,
                )
            )

        # Rank candidates by confidence score
        candidates.sort(key=lambda c: c.confidence_score, reverse=True)

        primary = candidates[0]

        # Apply Spotify high-fidelity metadata overlay if resolved from Spotify
        if spotify_meta and spotify_meta.get("type") == "track":
            if primary.confidence_score < min_confidence:
                raise LowConfidenceError(
                    f"No reliable audio match found for Spotify track '{spotify_meta.get('title')}' by '{spotify_meta.get('artist')}'. "
                    f"Best match '{primary.title}' had low confidence ({primary.confidence_score:.2f})."
                )
            if spotify_meta.get("title"):
                primary.title = spotify_meta["title"]
            if spotify_meta.get("artist"):
                primary.uploader = spotify_meta["artist"]
            if spotify_meta.get("album"):
                primary.album_name = spotify_meta["album"]
            if spotify_meta.get("thumbnail"):
                primary.thumbnail_url = spotify_meta["thumbnail"]
            primary.original_source = "spotify"
        elif not self.is_url(query) and primary.confidence_score < min_confidence:
            raise LowConfidenceError(
                f"Top result '{primary.title}' had low confidence ({primary.confidence_score:.2f}). "
                f"Please refine your search with artist and title."
            )

        return primary, candidates

