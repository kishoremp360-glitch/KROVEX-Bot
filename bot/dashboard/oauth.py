"""Discord OAuth2 API client, PKCE helpers, and permission verifiers for KROVEX."""
from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp

from bot.utils.logger import get_logger

logger = get_logger("death_bot.dashboard.oauth")

DISCORD_AUTH_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/v10/users/@me"
DISCORD_GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

# Discord Permissions Bitfield flags
PERM_ADMINISTRATOR = 0x8
PERM_MANAGE_GUILD = 0x20


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and corresponding code_challenge (RFC 7636)."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


def has_manage_guild_permission(guild_dict: Dict[str, Any]) -> bool:
    """Evaluate whether user has Administrator or Manage Guild permission for a given guild."""
    if guild_dict.get("owner", False):
        return True
    try:
        perms = int(guild_dict.get("permissions", 0))
        return bool((perms & PERM_ADMINISTRATOR) or (perms & PERM_MANAGE_GUILD))
    except (ValueError, TypeError):
        return False


class DiscordOAuth2Client:
    """Client for interacting securely with Discord OAuth2 endpoints."""

    def __init__(
        self,
        client_id: Optional[int],
        client_secret: Optional[str],
        redirect_uri: Optional[str],
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._external_session = session

    def get_authorization_url(
        self,
        state: str,
        code_challenge: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ) -> str:
        """Construct authorization URL requesting minimum necessary scopes."""
        if not self.client_id or not self.redirect_uri:
            raise ValueError("OAuth2 client_id and redirect_uri must be configured.")

        if scopes is None:
            scopes = ["identify", "guilds"]

        params: Dict[str, str] = {
            "client_id": str(self.client_id),
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "prompt": "consent",
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        return f"{DISCORD_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(
        self,
        code: str,
        code_verifier: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Exchange authorization code for access and refresh tokens."""
        if not self.client_id or not self.client_secret or not self.redirect_uri:
            logger.error("Cannot exchange code: client credentials or redirect_uri not set.")
            return None

        payload: Dict[str, str] = {
            "client_id": str(self.client_id),
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            if self._external_session and not self._external_session.closed:
                async with self._external_session.post(
                    DISCORD_TOKEN_URL, data=payload, headers=headers
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    logger.warning("Token exchange failed with HTTP %d", resp.status)
                    return None
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        DISCORD_TOKEN_URL, data=payload, headers=headers
                    ) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        logger.warning("Token exchange failed with HTTP %d", resp.status)
                        return None
        except Exception as err:
            logger.error("Exception during token exchange: %s", err)
            return None

    async def fetch_user_profile(self, access_token: str) -> Optional[Dict[str, Any]]:
        """Fetch current authenticated user profile from Discord."""
        if not access_token:
            return None

        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            if self._external_session and not self._external_session.closed:
                async with self._external_session.get(
                    DISCORD_USER_URL, headers=headers
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.get(DISCORD_USER_URL, headers=headers) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        return None
        except Exception as err:
            logger.error("Exception fetching user profile: %s", err)
            return None

    async def fetch_user_guilds(self, access_token: str) -> Optional[List[Dict[str, Any]]]:
        """Fetch guilds current user belongs to from Discord."""
        if not access_token:
            return None

        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            if self._external_session and not self._external_session.closed:
                async with self._external_session.get(
                    DISCORD_GUILDS_URL, headers=headers
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.get(DISCORD_GUILDS_URL, headers=headers) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        return None
        except Exception as err:
            logger.error("Exception fetching user guilds: %s", err)
            return None
