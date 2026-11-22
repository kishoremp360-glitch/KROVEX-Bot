"""KROVEX Vault — Disaster Recovery and Secure Remote Backup Subsystem."""
from bot.cogs.vault.cog import VaultCog

async def setup(bot):
    await bot.add_cog(VaultCog(bot))
