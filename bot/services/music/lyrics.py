"""Authorized lyrics search engine and formatter for Death Bot."""

from __future__ import annotations

import asyncio
from typing import Optional, Tuple
import aiohttp

from bot.utils.logger import get_logger

logger = get_logger("death_bot.music.lyrics")

LRCLIB_API_URL = "https://lrclib.net/api/get"
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"


class LyricsService:
    """Retrieves verified song lyrics without fabrication."""

    def __init__(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        self._session = session

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"User-Agent": "DeathBot/2.0 (Discord Audio Engine)"})
        return self._session

    async def get_lyrics(self, track_name: str, artist_name: Optional[str] = None) -> Optional[Tuple[str, str, str]]:
        """Fetch lyrics for a given track name and artist.

        Returns:
            Tuple of (resolved_title, resolved_artist, lyrics_text) or None if unavailable.
        """
        session = await self._get_session()
        params = {"track_name": track_name}
        if artist_name:
            params["artist_name"] = artist_name

        try:
            async with session.get(LRCLIB_API_URL, params=params, timeout=8.0) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    plain = data.get("plainLyrics") or data.get("syncedLyrics")
                    if plain:
                        return (data.get("trackName", track_name), data.get("artistName", artist_name or "Unknown"), plain)
        except Exception as err:
            logger.debug("Direct lyrics query failed for '%s': %s", track_name, err)

        # Fallback: general search query
        try:
            q = f"{artist_name} {track_name}".strip() if artist_name else track_name
            async with session.get(LRCLIB_SEARCH_URL, params={"q": q}, timeout=8.0) as resp:
                if resp.status == 200:
                    results = await resp.json()
                    if results and isinstance(results, list):
                        top = results[0]
                        plain = top.get("plainLyrics") or top.get("syncedLyrics")
                        if plain:
                            return (top.get("trackName", track_name), top.get("artistName", "Unknown"), plain)
        except Exception as err:
            logger.warning("Lyrics search failed for query '%s': %s", track_name, err)

        return None

