"""Permission resolution and validation helpers for Death Bot."""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Union

import discord
from discord.ext import commands


def is_guild_owner(guild: Optional[discord.Guild], user: Union[discord.User, discord.Member]) -> bool:
    """Check if the user is the owner of the given guild or a bot owner (treated as server 2nd owner)."""
    if not guild or not user:
        return False
    if guild.owner_id == user.id:
        return True
    client = getattr(user, "_state", None)
    if client:
        bot_fn = getattr(client, "_get_client", None)
        if callable(bot_fn):
            try:
                b = bot_fn()
                if b:
                    raw_owners = getattr(getattr(b, "config", None), "owner_ids", [])
                    if user.id in raw_owners or str(user.id) in [str(x) for x in raw_owners]:
                        return True
                    app_owners = getattr(b, "owner_ids", set()) or set()
                    if user.id in app_owners or str(user.id) in [str(x) for x in app_owners]:
                        return True
            except Exception:
                pass
    return False


def has_any_role_named(member: discord.Member, role_names: List[str]) -> bool:
    """Check if member has any role matching the specified names (case-insensitive)."""
    clean_names = {name.lower() for name in role_names}
    return any(role.name.lower() in clean_names for role in member.roles)


def has_any_role_id(member: discord.Member, role_ids: List[int]) -> bool:
    """Check if member has any role matching the specified role IDs."""
    user_role_ids = {role.id for role in member.roles}
    return bool(user_role_ids.intersection(role_ids))


def check_bot_permissions(
    channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread, discord.abc.GuildChannel],
    required: discord.Permissions,
) -> tuple[bool, list[str]]:
    """Verify that the bot has all required permissions in the specified channel."""
    guild = channel.guild
    me = guild.me
    if not me:
        return False, ["Unable to resolve bot member instance in guild"]

    perms = channel.permissions_for(me)
    missing: list[str] = []

    for attr, val in required:
        if val and not getattr(perms, attr, False):
            missing.append(attr.replace("_", " ").title())

    return len(missing) == 0, missing


def is_in_voice(member: Union[discord.User, discord.Member]) -> bool:
    """Check if a member is currently connected to a voice channel."""
    if not isinstance(member, discord.Member):
        return False
    return member.voice is not None and member.voice.channel is not None


def get_krovex_invite_permissions() -> discord.Permissions:
    """Return default Administrator permissions for KROVEX bot invites.

    Grants Administrator (permission integer 8) to ensure complete server security,
    seamless role hierarchy positioning, and unhindered voice and anti-nuke operations.
    """
    return discord.Permissions(administrator=True)


def get_krovex_invite_url(client_id: int) -> str:
    """Generate standard OAuth2 invite URL with Administrator permission."""
    perms = get_krovex_invite_permissions()
    return discord.utils.oauth_url(
        client_id=int(client_id),
        permissions=perms,
        scopes=("bot", "applications.commands"),
    )


