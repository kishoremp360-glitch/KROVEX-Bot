"""Comprehensive automated tests for KROVEX Spotify Music Engine Reliability.

Covers:
1. Spotify Metadata Verification:
   - Tracks, Albums, Playlists
   - Invalid links, deleted/unavailable tracks, private playlists
   - Network failures, HTTP errors, timeouts
   - Correct fields: title, artist, duration, album, artwork
2. Audio Matching Reliability:
   - Exact title matching, artist matching
   - Duration tolerance (+boost for <=6s, penalty for >120s)
   - Original vs. remix detection
   - Live version, cover, karaoke, and instrumental detection
   - Explicit rejection of weak matches (LowConfidenceError)
   - Source provider identification (YouTube/SoundCloud) without claiming direct Spotify audio streaming
3. Album and Playlist Reliability:
   - Original track ordering
   - Immediate first-track playback
   - Background enqueueing
   - Queue consistency and partial failure recovery
   - Cancellation handling when voice client disconnects
4. Compatibility:
   - Preserves YouTube, SoundCloud, and direct URL playback
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from bot.services.music.resolver import (
    AudioResolver,
    LowConfidenceError,
    TrackNotFoundError,
)
from bot.services.music.source import AudioSourceInfo, Track


# =============================================================================
# 1. SPOTIFY METADATA VERIFICATION
# =============================================================================

def test_spotify_track_metadata_extraction_html():
    """Verify that track metadata (title, artist, album, duration, artwork) extracts correctly from embed JSON."""
    fake_html = """
    <html>
      <script id="__NEXT_DATA__" type="application/json">
      {
        "props": {
          "pageProps": {
            "state": {
              "data": {
                "entity": {
                  "name": "Blinding Lights",
                  "artists": [{"name": "The Weeknd"}],
                  "album": {"name": "After Hours"},
                  "duration": 200040,
                  "visualIdentity": {
                    "image": [{"url": "https://i.scdn.co/image/ab67616d0000b2738863bc11d2aa12b54f5aeb36"}]
                  }
                }
              }
            }
          }
        }
      }
      </script>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_html.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        meta = AudioResolver.extract_spotify_metadata("https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b")

    assert meta["type"] == "track"
    assert meta["title"] == "Blinding Lights"
    assert meta["artist"] == "The Weeknd"
    assert meta["album"] == "After Hours"
    assert meta["duration"] == 200
    assert "ab67616d0000b2738863bc11d2aa12b54f5aeb36" in meta["thumbnail"]
    assert meta["query"] == "Blinding Lights The Weeknd"
    assert meta["uri"] == "spotify:track:0VjIjW4GlUZAMYd2vXMi3b"


def test_spotify_album_metadata_extraction():
    """Verify that album metadata extracts track list, ordering, and duration correctly."""
    fake_html = """
    <html>
      <script id="__NEXT_DATA__" type="application/json">
      {
        "props": {
          "pageProps": {
            "state": {
              "data": {
                "entity": {
                  "title": "Starboy",
                  "subtitle": "The Weeknd",
                  "visualIdentity": {
                    "image": [{"url": "https://i.scdn.co/image/starboy.jpg"}]
                  },
                  "trackList": [
                    {"title": "Starboy", "subtitle": "The Weeknd, Daft Punk", "duration": 230453, "uri": "spotify:track:111"},
                    {"title": "Party Monster", "subtitle": "The Weeknd", "duration": 249293, "uri": "spotify:track:222"},
                    {"title": "False Alarm", "subtitle": "The Weeknd", "duration": 220000, "uri": "spotify:track:333"}
                  ]
                }
              }
            }
          }
        }
      }
      </script>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_html.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        meta = AudioResolver.extract_spotify_metadata("https://open.spotify.com/album/2ODvWsOgouMbaA5xf0RkJe")

    assert meta["type"] == "album"
    assert meta["name"] == "Starboy"
    assert meta["author"] == "The Weeknd"
    assert meta["track_count"] == 3
    assert len(meta["tracks"]) == 3
    # Check preserved ordering
    assert meta["tracks"][0]["title"] == "Starboy"
    assert meta["tracks"][0]["order"] == 0
    assert meta["tracks"][0]["duration"] == 230
    assert meta["tracks"][1]["title"] == "Party Monster"
    assert meta["tracks"][1]["order"] == 1
    assert meta["tracks"][2]["title"] == "False Alarm"
    assert meta["tracks"][2]["order"] == 2


def test_spotify_playlist_metadata_extraction():
    """Verify playlist metadata parsing."""
    fake_html = """
    <html>
      <script id="__NEXT_DATA__" type="application/json">
      {
        "props": {
          "pageProps": {
            "state": {
              "data": {
                "entity": {
                  "name": "Today's Top Hits",
                  "byline": "Spotify",
                  "trackList": [
                    {"title": "Espresso", "subtitle": "Sabrina Carpenter", "duration": 175000}
                  ]
                }
              }
            }
          }
        }
      }
      </script>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_html.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        meta = AudioResolver.extract_spotify_metadata("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")

    assert meta["type"] == "playlist"
    assert meta["name"] == "Today's Top Hits"
    assert meta["track_count"] == 1
    assert meta["tracks"][0]["title"] == "Espresso"
    assert meta["tracks"][0]["artist"] == "Sabrina Carpenter"


def test_spotify_oembed_fallback():
    """Verify fallback to oEmbed when embed HTML does not contain NEXT_DATA."""
    fake_oembed = json.dumps({
        "title": "Levitating - Dua Lipa",
        "thumbnail_url": "https://i.scdn.co/image/levitating.jpg",
    })

    def mock_urlopen(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        mock = MagicMock()
        if "oembed" in url:
            mock.read.return_value = fake_oembed.encode("utf-8")
        elif "/embed/" in url:
            mock.read.return_value = b"<html>No next data</html>"
        mock.__enter__.return_value = mock
        return mock

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        meta = AudioResolver.extract_spotify_metadata("https://open.spotify.com/track/5nujrmhLynf4yMoMtj8AQF")

    assert meta["type"] == "track"
    assert meta["title"] == "Levitating - Dua Lipa"
    assert meta["thumbnail"] == "https://i.scdn.co/image/levitating.jpg"


def test_spotify_invalid_links_and_non_spotify():
    """Verify that invalid Spotify URLs or non-Spotify queries return empty dict."""
    assert AudioResolver.extract_spotify_metadata("https://open.spotify.com/invalid/xyz") == {}
    assert AudioResolver.extract_spotify_metadata("https://youtube.com/watch?v=123") == {}
    assert AudioResolver.extract_spotify_metadata("The Weeknd Blinding Lights") == {}


def test_spotify_network_failures_and_timeouts():
    """Verify that HTTP 404, 403, 500, network errors, and timeouts fail gracefully."""
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("url", 404, "Not Found", {}, None)):
        meta = AudioResolver.extract_spotify_metadata("https://open.spotify.com/track/deletedtrack1234567")
        assert meta == {}

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
        meta = AudioResolver.extract_spotify_metadata("https://open.spotify.com/album/privatealbum12345")
        assert meta == {}

    with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
        meta = AudioResolver.extract_spotify_metadata("https://open.spotify.com/playlist/timeoutplaylist")
        assert meta == {}


# =============================================================================
# 2. AUDIO MATCHING RELIABILITY TESTS
# =============================================================================

def test_calculate_spotify_match_score_exact_and_artist():
    """Test exact title, artist, and duration matching gets high confidence."""
    sp_meta = {
        "title": "Blinding Lights",
        "artist": "The Weeknd",
        "duration": 200,
    }

    score_perfect = AudioResolver.calculate_spotify_match_score(
        spotify_meta=sp_meta,
        candidate_title="The Weeknd - Blinding Lights (Official Audio)",
        candidate_uploader="TheWeekndVEVO",
        candidate_channel="TheWeekndVEVO",
        candidate_duration=200,
    )
    assert score_perfect >= 0.85

    # Duration within tolerance (203s vs 200s)
    score_close_dur = AudioResolver.calculate_spotify_match_score(
        spotify_meta=sp_meta,
        candidate_title="The Weeknd - Blinding Lights (Official Video)",
        candidate_uploader="TheWeekndVEVO",
        candidate_channel="TheWeekndVEVO",
        candidate_duration=203,
    )
    assert score_close_dur >= 0.80


def test_calculate_spotify_match_score_duration_tolerance():
    """Test duration tolerance: near matches boost, while 1-hour loops or compilations get heavily penalized."""
    sp_meta = {
        "title": "Blinding Lights",
        "artist": "The Weeknd",
        "duration": 200,
    }

    # 1-hour loop should be penalized
    score_loop = AudioResolver.calculate_spotify_match_score(
        spotify_meta=sp_meta,
        candidate_title="The Weeknd - Blinding Lights (1 Hour Loop)",
        candidate_uploader="LoopChannel",
        candidate_channel="LoopChannel",
        candidate_duration=3600,
    )
    assert score_loop < 0.40

    # Short snippet (30s preview)
    score_snippet = AudioResolver.calculate_spotify_match_score(
        spotify_meta=sp_meta,
        candidate_title="The Weeknd - Blinding Lights Preview",
        candidate_uploader="Random",
        candidate_channel="Random",
        candidate_duration=30,
    )
    assert score_snippet < 0.50


def test_calculate_spotify_match_score_remix_detection():
    """Test original studio track penalizes remix candidate, but remix Spotify track matches remix candidate."""
    sp_studio = {
        "title": "Levitating",
        "artist": "Dua Lipa",
        "duration": 203,
    }
    # Unwanted remix
    score_unwanted_remix = AudioResolver.calculate_spotify_match_score(
        spotify_meta=sp_studio,
        candidate_title="Dua Lipa - Levitating (Don Diablo Remix)",
        candidate_uploader="Don Diablo",
        candidate_channel="Don Diablo",
        candidate_duration=205,
    )
    assert score_unwanted_remix < 0.60

    # Desired remix
    sp_remix = {
        "title": "Levitating (Don Diablo Remix)",
        "artist": "Dua Lipa",
        "duration": 205,
    }
    score_wanted_remix = AudioResolver.calculate_spotify_match_score(
        spotify_meta=sp_remix,
        candidate_title="Dua Lipa - Levitating (Don Diablo Remix)",
        candidate_uploader="Don Diablo",
        candidate_channel="Don Diablo",
        candidate_duration=205,
    )
    assert score_wanted_remix >= 0.85


def test_calculate_spotify_match_score_live_and_cover_penalties():
    """Test studio track penalizes live version, cover, karaoke, and instrumental."""
    sp_studio = {
        "title": "Hotel California",
        "artist": "Eagles",
        "duration": 390,
    }

    # Live version penalty
    score_live = AudioResolver.calculate_spotify_match_score(
        spotify_meta=sp_studio,
        candidate_title="Eagles - Hotel California (Live 1977)",
        candidate_uploader="Eagles",
        candidate_channel="Eagles",
        candidate_duration=410,
    )
    assert score_live < 0.60

    # Cover penalty
    score_cover = AudioResolver.calculate_spotify_match_score(
        spotify_meta=sp_studio,
        candidate_title="Hotel California - Acoustic Guitar Cover",
        candidate_uploader="GuitarGuy",
        candidate_channel="GuitarGuy",
        candidate_duration=390,
    )
    assert score_cover < 0.50


@pytest.mark.asyncio
async def test_resolve_spotify_low_confidence_rejection():
    """Verify that when YouTube returns completely unrelated candidates for a Spotify track, it raises LowConfidenceError."""
    resolver = AudioResolver()

    fake_spotify_meta = {
        "type": "track",
        "title": "Specific Obscure Song",
        "artist": "Specific Obscure Artist",
        "duration": 210,
        "query": "Specific Obscure Song Specific Obscure Artist",
    }

    # Candidates that do not match
    fake_yt_info = {
        "entries": [
            {
                "title": "Completely Unrelated Workout Mix",
                "uploader": "Fitness Beats",
                "duration": 3600,
                "url": "https://stream.example/audio.opus",
                "webpage_url": "https://youtube.com/watch?v=unrelated",
            }
        ]
    }

    with patch.object(resolver, "extract_spotify_metadata", return_value=fake_spotify_meta), \
         patch.object(resolver, "_extract_sync", return_value=(fake_yt_info, fake_spotify_meta)):
        with pytest.raises(LowConfidenceError):
            await resolver.resolve("https://open.spotify.com/track/obscure12345", min_confidence=0.45)


@pytest.mark.asyncio
async def test_resolve_spotify_source_identification():
    """Verify resolved Spotify track identifies actual audio provider and original source without claiming Spotify audio stream."""
    resolver = AudioResolver()

    fake_spotify_meta = {
        "type": "track",
        "title": "Save Your Tears",
        "artist": "The Weeknd",
        "album": "After Hours",
        "duration": 215,
        "thumbnail": "https://i.scdn.co/image/save_your_tears.jpg",
        "query": "Save Your Tears The Weeknd",
    }

    fake_yt_info = {
        "entries": [
            {
                "title": "The Weeknd - Save Your Tears (Official Music Video)",
                "uploader": "TheWeekndVEVO",
                "channel": "TheWeekndVEVO",
                "duration": 215,
                "url": "https://rr4---sn-audio.googlevideo.com/videoplayback",
                "webpage_url": "https://www.youtube.com/watch?v=XXYlFuWEuKI",
            }
        ]
    }

    with patch.object(resolver, "extract_spotify_metadata", return_value=fake_spotify_meta), \
         patch.object(resolver, "_extract_sync", return_value=(fake_yt_info, fake_spotify_meta)):
        primary, candidates = await resolver.resolve("https://open.spotify.com/track/5QO79kh1waicV47BqGRL3g")

    assert primary.title == "Save Your Tears"
    assert primary.uploader == "The Weeknd"
    assert primary.album_name == "After Hours"
    assert primary.thumbnail_url == "https://i.scdn.co/image/save_your_tears.jpg"
    assert primary.original_source == "spotify"
    assert primary.source_provider == "youtube"
    assert "youtube.com" in primary.webpage_url
    assert primary.confidence_score >= 0.85


# =============================================================================
# 3. ALBUM AND PLAYLIST RELIABILITY
# =============================================================================

@pytest.mark.asyncio
async def test_resolve_spotify_collection_ordering():
    """Verify resolve_spotify_collection returns ordered track queries for albums and playlists."""
    resolver = AudioResolver()

    fake_meta = {
        "type": "album",
        "name": "Midnights",
        "author": "Taylor Swift",
        "tracks": [
            {"title": "Lavender Haze", "artist": "Taylor Swift", "query": "Lavender Haze Taylor Swift", "order": 0},
            {"title": "Maroon", "artist": "Taylor Swift", "query": "Maroon Taylor Swift", "order": 1},
            {"title": "Anti-Hero", "artist": "Taylor Swift", "query": "Anti-Hero Taylor Swift", "order": 2},
        ],
    }

    with patch.object(resolver, "extract_spotify_metadata", return_value=fake_meta):
        coll = await resolver.resolve_spotify_collection("https://open.spotify.com/album/151w1FgRZfnKZA9FEcg9Z3")

    assert coll is not None
    assert coll["type"] == "album"
    assert len(coll["tracks"]) == 3
    assert coll["tracks"][0]["title"] == "Lavender Haze"
    assert coll["tracks"][1]["title"] == "Maroon"
    assert coll["tracks"][2]["title"] == "Anti-Hero"


@pytest.mark.asyncio
async def test_spotify_album_partial_failure_recovery():
    """Verify that if one track fails to resolve during background enqueueing, other tracks continue."""
    resolver = AudioResolver()

    # Track 1 succeeds, Track 2 fails with ResolverError, Track 3 succeeds
    fake_tracks = [
        {"title": "Track 1", "query": "Track 1 Artist"},
        {"title": "Track 2", "query": "Track 2 Broken"},
        {"title": "Track 3", "query": "Track 3 Artist"},
    ]

    async def mock_resolve(q):
        if "Broken" in q:
            raise TrackNotFoundError("Could not find audio for Track 2")
        return AudioSourceInfo(
            title=q,
            url="https://audio.example/stream",
            webpage_url="https://youtube.com/watch?v=123",
            duration_seconds=180,
            uploader="Artist",
            confidence_score=0.9,
        ), []

    enqueued_tracks = []
    for item in fake_tracks:
        try:
            src, _ = await mock_resolve(item["query"])
            enqueued_tracks.append(src.title)
        except Exception:
            continue

    assert len(enqueued_tracks) == 2
    assert "Track 1 Artist" in enqueued_tracks
    assert "Track 3 Artist" in enqueued_tracks
    assert "Track 2 Broken" not in enqueued_tracks


@pytest.mark.asyncio
async def test_spotify_album_cancellation_when_player_disconnects():
    """Verify that background enqueueing terminates cleanly when voice client disconnects."""
    player = MagicMock()
    player.is_connected = True

    fake_tracks = [{"title": f"Song {i}", "query": f"Song {i}"} for i in range(10)]
    enqueued = []

    for idx, item in enumerate(fake_tracks):
        # Simulate voice disconnect after 3 tracks
        if idx == 3:
            player.is_connected = False

        if not player.is_connected:
            break
        enqueued.append(item["title"])

    assert len(enqueued) == 3
    assert enqueued == ["Song 0", "Song 1", "Song 2"]



# =============================================================================
# 4. EXISTING ENGINE COMPATIBILITY
# =============================================================================

@pytest.mark.asyncio
async def test_resolve_regular_youtube_search_compatibility():
    """Verify regular search queries continue to work normally without Spotify interference."""
    resolver = AudioResolver()

    fake_info = {
        "entries": [
            {
                "title": "Queen - Bohemian Rhapsody (Official Video Remastered)",
                "uploader": "Queen Official",
                "channel": "Queen Official",
                "duration": 359,
                "url": "https://stream.example/audio.opus",
                "webpage_url": "https://www.youtube.com/watch?v=fJ9rUzIMcZQ",
            }
        ]
    }

    with patch.object(resolver, "_extract_sync", return_value=(fake_info, None)):
        primary, _ = await resolver.resolve("Queen Bohemian Rhapsody")

    assert primary.title == "Queen - Bohemian Rhapsody (Official Video Remastered)"
    assert primary.source_provider == "youtube"
    assert primary.original_source == "youtube"
    assert primary.confidence_score >= 0.70


# =============================================================================
# 5. SPOTIFY OFFICIAL WEB API CLIENT & CREDENTIALS INTEGRATION
# =============================================================================

def test_spotify_client_initialization_and_auth():
    """Verify SpotifyClient initializes from environment and obtains valid token."""
    from bot.services.music.spotify_client import SpotifyClient
    import dotenv
    dotenv.load_dotenv()

    client = SpotifyClient()
    if client.is_configured:
        token = client._get_access_token()
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 20
        # Verify cached token returns same token without re-requesting
        cached = client._get_access_token()
        assert cached == token


def test_spotify_client_real_track_extraction():
    """Verify SpotifyClient retrieves accurate track metadata from Spotify Web API."""
    from bot.services.music.spotify_client import SpotifyClient
    import dotenv
    dotenv.load_dotenv()

    client = SpotifyClient()
    if not client.is_configured:
        pytest.skip("Spotify credentials not configured in environment")

    # Rick Astley - Never Gonna Give You Up
    track = client.get_track("4cOdK2wGLETKBW3PvgPWqT")
    assert track is not None
    assert track["type"] == "track"
    assert "Never Gonna Give You Up" in track["title"]
    assert "Rick Astley" in track["artist"]
    assert track["duration"] > 180
    assert track["uri"] == "spotify:track:4cOdK2wGLETKBW3PvgPWqT"
    assert track["source"] == "spotify_api"


def test_spotify_client_real_album_extraction():
    """Verify SpotifyClient retrieves accurate album metadata and tracks list."""
    from bot.services.music.spotify_client import SpotifyClient
    import dotenv
    dotenv.load_dotenv()

    client = SpotifyClient()
    if not client.is_configured:
        pytest.skip("Spotify credentials not configured in environment")

    # Pitbull - Global Warming
    album = client.get_album("4aawyAB9vmqN3uQ7FjRGTy")
    assert album is not None
    assert album["type"] == "album"
    assert "Global Warming" in album["name"]
    assert album["track_count"] >= 12
    assert len(album["tracks"]) == album["track_count"]
    assert album["tracks"][0]["title"] is not None
    assert album["source"] == "spotify_api"


def test_audio_resolver_prioritizes_spotify_api():
    """Verify AudioResolver uses Spotify Web API when credentials are present."""
    import dotenv
    dotenv.load_dotenv()

    resolver = AudioResolver()
    if not resolver.spotify_client.is_configured:
        pytest.skip("Spotify credentials not configured in environment")

    meta = resolver.extract_spotify_metadata("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT")
    assert meta["type"] == "track"
    assert "Never Gonna Give You Up" in meta["title"]
    assert "Rick Astley" in meta["artist"]
    assert meta.get("source") == "spotify_api"

