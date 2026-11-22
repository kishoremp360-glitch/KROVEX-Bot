"""REST API endpoints and OAuth2 authentication handlers for the Death Bot web dashboard."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional
import aiohttp

from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.dashboard.api")


class DashboardAPI:
    """REST API service powering dashboard web clients."""

    def __init__(self, bot: "DeathBot") -> None:
        self.bot = bot

    async def verify_oauth_user(self, access_token: str) -> Optional[Dict[str, Any]]:
        """Validate Discord OAuth2 Bearer token with Discord API."""
        if not access_token:
            return None
        url = "https://discord.com/api/v10/users/@me"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logger.error("OAuth2 user validation failed: %s", e)
        return None

    async def verify_guild_permission(self, access_token: str, guild_id: int) -> bool:
        """Verify that the OAuth2 user has Administrator or Manage Guild permissions."""
        url = "https://discord.com/api/v10/users/@me/guilds"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        guilds = await resp.json()
                        for g in guilds:
                            if int(g["id"]) == guild_id:
                                perms = int(g.get("permissions", 0))
                                # 0x8 = Administrator, 0x20 = Manage Guild
                                return bool(perms & 0x8 or perms & 0x20 or g.get("owner", False))
        except Exception as e:
            logger.error("OAuth2 guild permissions verification failed: %s", e)
        return False

    # =========================================================
    # BACKEND API DATA ENDPOINTS
    # =========================================================

    async def get_ticket_dashboard_data(self, guild_id: int) -> Dict[str, Any]:
        """Fetch ticket configuration, categories, and resolution statistics."""
        if not self.bot.ticket_repo:
            return {"error": "Repository unavailable"}
        settings = await self.bot.ticket_repo.get_settings(guild_id)
        categories = await self.bot.ticket_repo.get_categories(guild_id)
        stats = await self.bot.ticket_repo.get_ticket_stats(guild_id)
        return {"settings": settings, "categories": categories, "stats": stats}

    async def get_leveling_dashboard_data(self, guild_id: int) -> Dict[str, Any]:
        """Fetch leveling settings, rewards, and top rank leaderboard."""
        if not self.bot.level_repo:
            return {"error": "Repository unavailable"}
        settings = await self.bot.level_repo.get_settings(guild_id)
        rewards = await self.bot.level_repo.get_rewards(guild_id)
        stats = await self.bot.level_repo.get_guild_stats(guild_id)
        top = await self.bot.level_repo.get_leaderboard(guild_id, limit=5)
        return {"settings": settings, "rewards": rewards, "stats": stats, "top_members": top}

    async def get_economy_dashboard_data(self, guild_id: int) -> Dict[str, Any]:
        """Fetch economy rules, circulation, and recent financial transactions."""
        if not self.bot.economy_repo:
            return {"error": "Repository unavailable"}
        settings = await self.bot.economy_repo.get_settings(guild_id)
        stats = await self.bot.economy_repo.get_economy_stats(guild_id)
        logs = await self.bot.economy_repo.get_transaction_logs(guild_id, limit=10)
        return {"settings": settings, "stats": stats, "recent_transactions": logs}

    async def get_shop_dashboard_data(self, guild_id: int) -> Dict[str, Any]:
        """Fetch marketplace merchandise, stock, and orders."""
        if not self.bot.shop_repo:
            return {"error": "Repository unavailable"}
        items = await self.bot.shop_repo.get_items(guild_id)
        categories = await self.bot.shop_repo.get_categories(guild_id)
        stats = await self.bot.shop_repo.get_shop_stats(guild_id)
        orders = await self.bot.shop_repo.get_purchases(guild_id, limit=10)
        return {"items": items, "categories": categories, "stats": stats, "recent_orders": orders}

    async def get_minigames_dashboard_data(self, guild_id: int) -> Dict[str, Any]:
        """Fetch betting limits, active challenges, and player leaderboards."""
        if not self.bot.minigame_repo:
            return {"error": "Repository unavailable"}
        settings = await self.bot.minigame_repo.get_settings(guild_id)
        top_players = await self.bot.minigame_repo.get_leaderboard(guild_id, limit=5)
        return {"settings": settings, "leaderboard": top_players}

