"""Intelligent song resolution, yt-dlp extraction, and audio ranking engine."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
import urllib.request
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


class AudioResolver:
    """Intelligent audio resolver utilizing yt-dlp with non-blocking concurrency and ranking."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> None:
        self.spotify_client = SpotifyClient(client_id=client_id, client_secret=client_secret)
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
        """Synchronous yt-dlp extraction executed inside worker thread with Spotify bridge and intelligent fallback."""
        opts = dict(self.ydl_opts)
        opts["noplaylist"] = not playlist
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

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target, download=False)
                return info, spotify_meta
        except Exception as yt_err:
            err_msg = str(yt_err).lower()
            if not self.is_url(query) or (spotify_meta and spotify_meta.get("query")):
                logger.warning("YouTube blocked datacenter request (%s); seamlessly falling back to SoundCloud for '%s'", yt_err, query)
                sc_opts = dict(self.ydl_opts)
                sc_opts["noplaylist"] = not playlist
                sc_target = spotify_meta["query"] if (spotify_meta and spotify_meta.get("query")) else query.strip()
                try:
                    with yt_dlp.YoutubeDL(sc_opts) as sc_ydl:
                        info = sc_ydl.extract_info(f"scsearch5:{sc_target}", download=False)
                        if info:
                            return info, spotify_meta
                except Exception as sc_err:
                    logger.warning("SoundCloud fallback failed for '%s': %s", sc_target, sc_err)
            raise

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
            if "youtube.com" in webpage or "youtu.be" in webpage:
                provider = "youtube"
            elif "soundcloud.com" in webpage:
                provider = "soundcloud"
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

