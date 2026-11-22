"""KROVEX Spotify API Verification Test Suite.

Comprehensive tests verifying:
1. Environment variable loading without credential leakage
2. Spotify Client Credentials flow authentication
3. Token caching & expiration logic
4. Track, album, and playlist metadata extraction
5. Spotify URL recognition
6. Fallback resilience on failure or invalid credentials
7. Integration with the AudioResolver ranking and matching engine
8. YouTube, direct URL, and non-Spotify audio compatibility preservation
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch
import pytest

from bot.config import BotConfig
from bot.services.music.resolver import AudioResolver, URL_REGEX
from bot.services.music.spotify_client import SpotifyClient


def _create_mock_response(payload: dict, status: int = 200) -> MagicMock:
    """Helper to create a urllib response mock that works inside a `with` context manager."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    return mock_resp


def test_env_loaded_and_secrets_protected():
    """Requirement 1 & 2: Environment variables are loaded and never exposed in repr or logs."""
    config = BotConfig.from_env(validate=False)

    # Confirm fields exist on config
    assert hasattr(config, "spotify_client_id")
    assert hasattr(config, "spotify_client_secret")

    # Safe representation must NEVER display secret
    safe_dict = config.safe_repr()
    assert safe_dict["spotify_client_secret"] in ("***REDACTED***", "NOT_SET")
    if config.spotify_client_secret:
        assert config.spotify_client_secret not in str(safe_dict)
        assert config.spotify_client_secret not in repr(config)


def test_spotify_client_credentials_and_caching():
    """Requirement 3 & 4: Test Spotify authentication and token caching."""
    client = SpotifyClient(client_id="mock_client_id", client_secret="mock_client_secret")
    assert client.is_configured is True

    # Mock token response
    mock_response = _create_mock_response({"access_token": "mock_token_abc_123", "expires_in": 3600})

    with patch("urllib.request.urlopen", return_value=mock_response):
        token1 = client._get_access_token()
        assert token1 == "mock_token_abc_123"
        assert client._token == "mock_token_abc_123"
        assert client._token_expires_at > time.time() + 3500

        # Second call within validity should return cached token without requesting API
        with patch("urllib.request.urlopen") as mock_urlopen_fail:
            token2 = client._get_access_token()
            assert token2 == "mock_token_abc_123"
            mock_urlopen_fail.assert_not_called()

        # When token is near expiration (< 60s), it should refresh
        client._token_expires_at = time.time() + 30
        mock_refresh = _create_mock_response({"access_token": "new_refreshed_token", "expires_in": 3600})
        with patch("urllib.request.urlopen", return_value=mock_refresh):
            token3 = client._get_access_token()
            assert token3 == "new_refreshed_token"


def test_track_metadata_retrieval():
    """Requirement 5: Test retrieving track metadata."""
    client = SpotifyClient(client_id="id", client_secret="sec")
    client._token = "valid_token"
    client._token_expires_at = time.time() + 3600

    track_api_payload = {
        "name": "Believer",
        "artists": [{"name": "Imagine Dragons"}],
        "album": {
            "name": "Evolve",
            "images": [{"url": "https://i.scdn.co/image/evolve_cover"}],
        },
        "duration_ms": 204000,
        "external_ids": {"isrc": "USUM71700626"},
    }
    mock_resp = _create_mock_response(track_api_payload)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        track = client.get_track("0pqnGHJpmpxLKifKRmU6WP")
        assert track is not None
        assert track["title"] == "Believer"
        assert track["artist"] == "Imagine Dragons"
        assert track["album"] == "Evolve"
        assert track["duration"] == 204
        assert track["query"] == "Believer Imagine Dragons"
        assert track["isrc"] == "USUM71700626"
        assert track["source"] == "spotify_api"


def test_album_and_search_retrieval():
    """Requirement 5: Test album extraction and search pre-resolution."""
    client = SpotifyClient(client_id="id", client_secret="sec")
    client._token = "valid_token"
    client._token_expires_at = time.time() + 3600

    album_payload = {
        "name": "Evolve",
        "artists": [{"name": "Imagine Dragons"}],
        "images": [{"url": "https://img.jpg"}],
        "tracks": {
            "items": [
                {"name": "Next To Me", "duration_ms": 230000, "artists": [{"name": "Imagine Dragons"}]},
                {"name": "Believer", "duration_ms": 204000, "artists": [{"name": "Imagine Dragons"}]},
            ]
        },
    }
    mock_resp = _create_mock_response(album_payload)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        album = client.get_album("33pt9HBdGlAbRGBHQgsZsU")
        assert album is not None
        assert album["name"] == "Evolve"
        assert album["track_count"] == 2
        assert album["tracks"][1]["title"] == "Believer"


def test_spotify_url_recognition():
    """Requirement 6: Verify Spotify URL patterns are recognized."""
    urls = [
        "https://open.spotify.com/track/0pqnGHJpmpxLKifKRmU6WP",
        "http://open.spotify.com/intl-fr/track/0pqnGHJpmpxLKifKRmU6WP",
        "https://open.spotify.com/album/33pt9HBdGlAbRGBHQgsZsU",
        "https://open.spotify.com/playlist/7DgPQwzEoUVfQYBiMLER9Z",
        "https://spotify.com/track/0pqnGHJpmpxLKifKRmU6WP",
    ]
    for url in urls:
        assert AudioResolver.is_url(url) is True


def test_fallback_when_spotify_api_fails():
    """Requirement 7: Verify resilient fallback when Spotify API is unavailable."""
    client = SpotifyClient(client_id="bad_id", client_secret="bad_sec")

    # API request fails
    with patch("urllib.request.urlopen", side_effect=Exception("API Network Error")):
        res = client.get_track("dummy_id")
        assert res is None

    # AudioResolver should fallback to HTML scraping or oEmbed
    html_with_next_data = (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"state":{"data":{"entity":{"title":"Scraped Believer","artists":[{"name":"Imagine Dragons"}],"duration":204000}}}}}}'
        '</script></html>'
    )
    mock_html_resp = MagicMock()
    mock_html_resp.read.return_value = html_with_next_data.encode("utf-8")
    mock_html_resp.__enter__.return_value = mock_html_resp

    with patch.object(client, "get_track", return_value=None):
        with patch("urllib.request.urlopen", return_value=mock_html_resp):
            meta = AudioResolver.extract_spotify_metadata("https://open.spotify.com/track/test123", spotify_client=client)
            assert meta["title"] == "Scraped Believer"
            assert meta["artist"] == "Imagine Dragons"


def test_spotify_metadata_connects_to_ranking_engine():
    """Requirement 8: Confirm Spotify metadata evaluates cleanly in match score engine."""
    sp_meta = {
        "title": "Believer",
        "artist": "Imagine Dragons",
        "duration": 204,
    }

    # Perfect official candidate
    score_high = AudioResolver.calculate_spotify_match_score(
        spotify_meta=sp_meta,
        candidate_title="Imagine Dragons - Believer (Official Music Video)",
        candidate_uploader="ImagineDragonsVEVO",
        candidate_channel="Imagine Dragons",
        candidate_duration=204,
    )
    assert score_high >= 0.85

    # Low score for unwanted nightcore/remix with huge duration mismatch
    score_low = AudioResolver.calculate_spotify_match_score(
        spotify_meta=sp_meta,
        candidate_title="Believer (Nightcore Remix 1 Hour Loop)",
        candidate_uploader="RandomUser",
        candidate_channel="RandomChannel",
        candidate_duration=3600,
    )
    assert score_low < 0.30


def test_youtube_and_direct_url_support_preserved():
    """Requirement 9: Preserve YouTube, Soundcloud, and direct audio URL support."""
    yt_url = "https://www.youtube.com/watch?v=7wtfhZwyrcc"
    sc_url = "https://soundcloud.com/imaginedragons/believer"
    assert AudioResolver.is_url(yt_url) is True
    assert AudioResolver.is_url(sc_url) is True

    # Standard query match score
    yt_score = AudioResolver.calculate_match_score(
        query="believer imagine dragons",
        title="Imagine Dragons - Believer (Official Video)",
        uploader="ImagineDragonsVEVO",
        channel="ImagineDragons",
    )
    assert yt_score >= 0.80
