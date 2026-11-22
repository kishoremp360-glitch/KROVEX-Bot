"""Anime & Social Roleplay Interaction Module for Death Bot.

Provides 49 genuine, rich social interactions and media commands:
- Roleplay interactions: hug, kiss, cuddle, pat, slap, punch, bite, boop, bonk, bully, etc.
- Emotional reactions: cry, dance, smile, smug, blush, pout, sleepy, wag, etc.
- Social matchmaking: ship, shipp, couple
- Media discovery: anime, mydog, boy
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.social import _anime_data
from bot.cogs.social._anime_data import (
    ANIME_BOY_IMAGES,
    DOG_FACTS,
    FALLBACK_DOG_IMAGES,
    calculate_ship_score,
    format_ship_result,
    get_action_gif,
)
from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.anime_social")
BRAND_COLOR = 0x9D4EDD
PINK_COLOR = 0xFF69B4

# Action display descriptions and messages
ACTION_MESSAGES = {
    "hug": ("Warm Hug", "{author} gives {target} a warm, loving hug! <a:19539heart:1571210595079037040>", "{author} hugs themselves softly! <a:19539heart:1571210595079037040>"),
    "kiss": ("Affectionate Kiss", "{author} kisses {target} sweetly! <a:73094hellokittylove:1571209757639843931>", "{author} kisses the mirror! Muah~ <a:73094hellokittylove:1571209757639843931>"),
    "cuddle": ("Cozy Cuddle", "{author} snuggles close and cuddles {target}! <:46712milkandmochaforehead:1571210610484445275>", "{author} cuddles up with a warm blanket! <:46712milkandmochaforehead:1571210610484445275>"),
    "pat": ("Gentle Headpat", "{author} gently pats {target} on the head. Good job! <a:89920starspink5:1571210538304667758>", "{author} gives themselves a comforting headpat. <a:89920starspink5:1571210538304667758>"),
    "slap": ("Anime Slap", "{author} slaps {target}! Ouch, that stung! 💢", "{author} slaps some sense into themselves!"),
    "punch": ("Anime Power-Punch", "{author} lands a powerful anime punch on {target}! 💥", "{author} punches the air with fierce determination!"),
    "bite": ("Playful Bite", "{author} playfully bites {target}! Nom! <:46712milkandmochaforehead:1571210610484445275>", "{author} nibbles on a snack! <:84604kittymifin:1571210534395838474>"),
    "boop": ("Nose Boop", "{author} boops {target} right on the nose! Boop! 👉", "{author} boops their own nose in the mirror!"),
    "bonk": ("Horny Jail Bonk", "{author} bonks {target}! Off to horny jail! 🔨", "{author} bonks themselves on the head!"),
    "bully": ("Playful Tease", "{author} teases and bullies {target} playfully! 😈", "{author} is feeling mischievous today!"),
    "greet": ("Warm Greeting", "{author} warmly greets {target}! Great to see you! <a:96650flowerswhite:1571210540624257044>", "{author} sends greetings to the whole room! <a:96650flowerswhite:1571210540624257044>"),
    "handholding": ("Wholesome Handholding", "{author} gently holds hands with {target}! How romantic! <a:19539heart:1571210595079037040>", "{author} holds their own hands together."),
    "kill": ("Anime Battle Knockout", "{author} executes a dramatic anime battle knockout on {target}! <a:17684rainbowknife:1571210592121786398>", "{author} faints dramatically on the floor! <a:17684rainbowknife:1571210592121786398>"),
    "lick": ("Playful Lick", "{author} playfully licks {target}! 👅", "{author} licks an ice cream cone! 🍦"),
    "nom": ("Cute Nibble", "{author} nibbles on {target}! Delicious! <:84604kittymifin:1571210534395838474>", "{author} munches on a tasty muffin! <:84604kittymifin:1571210534395838474>"),
    "poke": ("Gentle Poke", "{author} pokes {target} repeatedly. Hey you! 👈", "{author} pokes at thin air."),
    "highfive": ("High Five", "{author} gives {target} a crisp, energetic high-five! ✋", "{author} high-fives the air! Yeah!"),
    "tickle": ("Tickle Attack", "{author} attacks {target} with relentless tickles! 😆", "{author} giggles uncontrollably!"),
    "stare": ("Intense Anime Stare", "{author} stares intently at {target}... 👀", "{author} stares blankly into the void..."),
    "cheer": ("Enthusiastic Cheer", "{author} cheers enthusiastically for {target}! You got this! <a:3368kokotadance:1571199726395588772>", "{author} cheers themselves on! I can do it! <a:3368kokotadance:1571199726395588772>"),
    "fuck": ("Angry Outburst", "{author} is fed up and yells at {target}! <a:57819x:1571210516141969489> (Harmless cartoon outburst)", "{author} flips a desk in frustration! ╯°□°）╯︵ ┻━┻"),
    "lewd": ("Too Lewd!", "{author} covers their eyes at {target}: That is way too lewd! <:41624dramaqueentext:1571210597712924823>", "{author} turns red and looks away: Too lewd!"),
    "blush": ("Flustered Blush", "{author} is blushing bright red in front of {target}! 😳", "{author} blushes bright red! 😳"),
    "cry": ("Sad Tears", "{author} cries on {target}'s shoulder... <:45572bubbles:1571210608127377469>", "{author} is crying their eyes out... Someone offer a hug! <:45572bubbles:1571210608127377469>"),
    "dance": ("Dance Party", "{author} dances around {target}! <a:3368kokotadance:1571199726395588772>", "{author} breaks into an energetic dance routine! <a:3368kokotadance:1571199726395588772>"),
    "deredere": ("Sweet Affection", "{author} radiates pure sweet love towards {target}! <a:7348yaeheartsparkles:1571210652024836176>", "{author} is filled with pure sweet love! <a:7348yaeheartsparkles:1571210652024836176>"),
    "grin": ("Mischievous Grin", "{author} grins slyly at {target}! 😏", "{author} smirks with a mischievous anime grin! 😏"),
    "happy": ("Pure Joy", "{author} jumps with joy around {target}! <a:55256purplesparkles:1571210505786495016>", "{author} is radiating pure joy and happiness! <a:55256purplesparkles:1571210505786495016>"),
    "pout": ("Angry Pout", "{author} pouts angrily at {target}! Hmph! 😾", "{author} crosses their arms and pouts! Hmph!"),
    "sleepy": ("Sleepy Yawns", "{author} yawns sleepily next to {target}... <a:63092moon:1571210526812541050>", "{author} is feeling very sleepy... Time for a nap! <a:63092moon:1571210526812541050>"),
    "smile": ("Radiant Smile", "{author} smiles warmly at {target}! <a:99088cherryblossomspin:1571210546278305954>", "{author} flashes a radiant, heartwarming smile! <a:99088cherryblossomspin:1571210546278305954>"),
    "smug": ("Delightfully Smug", "{author} looks delightfully smug towards {target}! <:90177vforvictory:1571209730976649246>", "{author} has the smug look of supreme victory! <:90177vforvictory:1571209730976649246>"),
    "scoff": ("Dismissive Scoff", "{author} scoffs dismissively at {target}! 😤", "{author} scoffs: Hah, as if! 😤"),
    "teehee": ("Cute Giggle", "{author} giggles cutely at {target}: Teehee~! <a:13083cinnamoji1:1571210572102504578>", "{author} giggles cutely: Teehee~! <a:13083cinnamoji1:1571210572102504578>"),
    "thinking": ("Deep Thoughts", "{author} ponders deeply about {target}... <:44519crystalball:1571210605644488774>", "{author} is deep in philosophical contemplation... <:44519crystalball:1571210605644488774>"),
    "thumbs": ("Thumbs Up", "{author} gives {target} a big thumbs up! <a:72921hellokittyyes:1571210532105617418>", "{author} gives an encouraging thumbs up! <a:72921hellokittyyes:1571210532105617418>"),
    "triggered": ("Anime Triggered", "{author} is TRIGGERED by {target}! <a:57819x:1571210516141969489>", "{author} is completely TRIGGERED! <a:57819x:1571210516141969489>"),
    "wag": ("Happy Tail Wag", "{author} happily wags their tail at {target}! 🐾", "{author} wags their tail with pure excitement! 🐾"),
    "wave": ("Friendly Wave", "{author} waves hello warmly to {target}! 👋", "{author} waves enthusiastically to everyone! 👋"),
}


class AnimeSocial(commands.Cog, name="Anime & Social Interactions"):
    """Comprehensive anime roleplay, emotional reactions, and social modules."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if hasattr(self.bot, "session") and self.bot.session and not self.bot.session.closed:
            return self.bot.session
        return aiohttp.ClientSession()

    # ── SHARED ACTION DISPATCHER ─────────────────────────────────────────────

    async def _execute_action(
        self,
        ctx: UnifiedContext,
        action: str,
        target: Optional[discord.Member] = None,
    ) -> None:
        """Generic, robust roleplay and reaction execution engine."""
        action_key = action.lower()
        title, duo_msg, solo_msg = ACTION_MESSAGES.get(
            action_key,
            (action_key.title(), "{author} interacts with {target}!", "{author} expresses themselves!"),
        )

        author_name = ctx.author.display_name
        is_self = target is None or target.id == ctx.author.id

        if is_self:
            description = solo_msg.format(author=author_name)
        else:
            description = duo_msg.format(author=author_name, target=target.display_name)

        session = await self._get_http_session()
        gif_url = await get_action_gif(action_key, session)

        embed = discord.Embed(
            title=f"🌸 {title}",
            description=description,
            color=BRAND_COLOR,
        )
        embed.set_image(url=gif_url)
        embed.set_footer(text=f"Requested by {ctx.author.name} • KROVEX Anime Engine")

        await ctx.reply(embed=embed)

    # ── 1. SHIP & SHIPP ──────────────────────────────────────────────────────

    async def _execute_ship(
        self,
        ctx: UnifiedContext,
        user1: discord.Member,
        user2: Optional[discord.Member] = None,
    ) -> None:
        """Calculate romantic compatibility between two users."""
        target1 = ctx.author if user2 is None else user1
        target2 = user1 if user2 is None else user2

        if target1.id == target2.id:
            embed = discord.Embed(
                title="💖 Self-Love Meter • 100%",
                description=(
                    f"**{target1.display_name}** loves themselves completely!\n"
                    f"`[██████████]` **100%**\n\n"
                    f"👑 **Self-Care Champion:** Loving yourself is the greatest love of all! Stay fabulous."
                ),
                color=PINK_COLOR,
            )
            embed.set_thumbnail(url=target1.display_avatar.url)
            await ctx.reply(embed=embed)
            return

        score = calculate_ship_score(target1.id, target2.id)
        ship_name, bar, verdict = format_ship_result(target1.display_name, target2.display_name, score)

        score_badge = f"{KrovexEmoji.SCORE_100} " if score == 100 else ""
        embed = discord.Embed(
            title=f"{KrovexEmoji.ANIMATED_HEART} Love Calculator • {ship_name} {KrovexEmoji.PURPLE_SPARKLES}",
            description=(
                f"**Matchup:** {target1.mention} + {target2.mention}\n\n"
                f"**Compatibility:** {score_badge}`{score}%`\n"
                f"`[{bar}]`\n\n"
                f"{verdict}"
            ),
            color=PINK_COLOR,
        )
        embed.set_thumbnail(url=target2.display_avatar.url)
        embed.set_footer(text=f"Requested by {ctx.author.name} • Calculated fresh today")
        await ctx.reply(embed=embed)

    @commands.command(name="ship", aliases=["love", "lovemeter"], help="Calculate romance compatibility with another user.")
    async def ship_prefix(self, ctx: commands.Context, user1: discord.Member, user2: Optional[discord.Member] = None) -> None:
        await self._execute_ship(UnifiedContext.from_prefix(ctx), user1, user2)

    @commands.command(name="shipp", help="Calculate romance compatibility with another user.")
    async def shipp_prefix(self, ctx: commands.Context, user1: discord.Member, user2: Optional[discord.Member] = None) -> None:
        await self._execute_ship(UnifiedContext.from_prefix(ctx), user1, user2)

    # ── 2. COUPLE ────────────────────────────────────────────────────────────

    async def _execute_couple(self, ctx: UnifiedContext) -> None:
        """Pick a random lucky couple from the server."""
        guild = ctx.guild
        if not guild:
            await ctx.send_error("Server Only", "The couple command can only be used in a Discord server.")
            return

        members = [m for m in guild.members if not m.bot]
        if len(members) < 2:
            await ctx.send_error("Not Enough Members", "At least 2 non-bot members are required to find a couple!")
            return

        # Pick two distinct random members
        partner1, partner2 = random.sample(members, 2)
        score = calculate_ship_score(partner1.id, partner2.id)
        ship_name, bar, _ = format_ship_result(partner1.display_name, partner2.display_name, score)

        embed = discord.Embed(
            title=f"{KrovexEmoji.ANIMATED_HEART} Server Couple of the Day! {KrovexEmoji.FALLING_PETALS}",
            description=(
                f"The stars have aligned! Today's chosen server couple is:\n\n"
                f"{KrovexEmoji.ANIMATED_HEART} **{partner1.mention}** & **{partner2.mention}** {KrovexEmoji.ANIMATED_HEART}\n\n"
                f"**Ship Name:** `{ship_name}`\n"
                f"**Compatibility Rating:** `{score}%` `[{bar}]`\n\n"
                f"May their bond bring peace, chaos, and memes to **{guild.name}**!"
            ),
            color=PINK_COLOR,
        )
        embed.set_thumbnail(url=partner1.display_avatar.url)
        embed.set_footer(text=f"Chosen by destiny for {guild.name}")
        await ctx.reply(embed=embed)

    @commands.command(name="couple", help="Pick a random lucky couple from the server.")
    @commands.guild_only()
    async def couple_prefix(self, ctx: commands.Context) -> None:
        await self._execute_couple(UnifiedContext.from_prefix(ctx))

    # ── 3. MYDOG ─────────────────────────────────────────────────────────────

    async def _execute_mydog(self, ctx: UnifiedContext) -> None:
        """Fetch a cute random dog picture with an interesting dog fact."""
        session = await self._get_http_session()
        dog_url = None
        try:
            async with session.get("https://dog.ceo/api/breeds/image/random", timeout=aiohttp.ClientTimeout(total=3.0)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    dog_url = data.get("message")
        except Exception:
            pass

        if not dog_url:
            dog_url = random.choice(FALLBACK_DOG_IMAGES)

        fact = random.choice(DOG_FACTS)
        embed = discord.Embed(
            title="🐶 Woof! Here is a Cute Doggo!",
            description=f"💡 **Did you know?**\n*{fact}*",
            color=0xF59E0B,
        )
        embed.set_image(url=dog_url)
        embed.set_footer(text=f"Requested by {ctx.author.name} • Dog.ceo API")
        await ctx.reply(embed=embed)

    @commands.command(name="mydog", help="Fetch a random cute dog picture and fun dog fact.")
    async def mydog_prefix(self, ctx: commands.Context) -> None:
        await self._execute_mydog(UnifiedContext.from_prefix(ctx))

    # ── 4. BOY ───────────────────────────────────────────────────────────────

    async def _execute_boy(self, ctx: UnifiedContext) -> None:
        """Fetch a stylish anime boy character image."""
        boy_img = random.choice(ANIME_BOY_IMAGES)
        embed = discord.Embed(
            title="🌸 Anime Boy Art",
            color=BRAND_COLOR,
        )
        embed.set_image(url=boy_img)
        embed.set_footer(text=f"Requested by {ctx.author.name} • SFW Anime Collection")
        await ctx.reply(embed=embed)

    @commands.command(name="boy", help="Fetch a stylish anime boy image.")
    async def boy_prefix(self, ctx: commands.Context) -> None:
        await self._execute_boy(UnifiedContext.from_prefix(ctx))

    # ── 5. ANIME ─────────────────────────────────────────────────────────────

    async def _execute_anime(self, ctx: UnifiedContext, query: str) -> None:
        """Search AniList for comprehensive anime metadata."""
        if not query or not query.strip():
            await ctx.send_error("Missing Search Query", "Please provide the name of an anime to search for!")
            return

        session = await self._get_http_session()
        media = await _anime_data.fetch_anilist_media(query.strip(), session)

        if not media:
            await ctx.send_error(
                "Not Found",
                f"Could not find any anime matching **'{query}'** on AniList. Please check the spelling and try again.",
            )
            return

        if media.get("isAdult", False):
            # Enforce SFW channel boundary
            is_nsfw = getattr(ctx.channel, "is_nsfw", lambda: False)()
            if not is_nsfw:
                await ctx.send_error(
                    "Content Restricted",
                    "⚠️ The requested anime is flagged as adult/18+ content and can only be viewed in age-restricted (NSFW) channels.",
                )
                return

        titles = media.get("title", {})
        title_romaji = titles.get("romaji") or "Unknown Title"
        title_english = titles.get("english")
        display_title = f"{title_romaji} ({title_english})" if title_english and title_english != title_romaji else title_romaji

        description = media.get("description") or "No description provided."
        # Strip simple HTML formatting tags
        description = description.replace("<br>", "\n").replace("<i>", "*").replace("</i>", "*").replace("<b>", "**").replace("</b>", "**")
        if len(description) > 400:
            description = description[:397] + "..."

        episodes = media.get("episodes") or "Unknown"
        status = (media.get("status") or "Unknown").replace("_", " ").title()
        score = f"{media.get('averageScore')}%" if media.get("averageScore") else "N/A"
        genres = ", ".join(media.get("genres", [])[:4]) or "General"
        site_url = media.get("siteUrl") or "https://anilist.co"

        embed = discord.Embed(
            title=display_title,
            url=site_url,
            description=description,
            color=BRAND_COLOR,
        )
        embed.add_field(name="Episodes", value=str(episodes), inline=True)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Average Score", value=f"⭐ `{score}`", inline=True)
        embed.add_field(name="Genres", value=genres, inline=False)

        cover_img = media.get("coverImage", {}).get("large")
        if cover_img:
            embed.set_thumbnail(url=cover_img)
        banner_img = media.get("bannerImage")
        if banner_img:
            embed.set_image(url=banner_img)

        embed.set_footer(text="Data provided by AniList GraphQL API")
        await ctx.reply(embed=embed)

    @commands.command(name="anime", help="Search for anime details and synopsis on AniList.")
    async def anime_prefix(self, ctx: commands.Context, *, query: str) -> None:
        await self._execute_anime(UnifiedContext.from_prefix(ctx), query)

    # ── 6. ALL 43 PREFIX ROLEPLAY & REACTION COMMANDS ────────────────────────

    @commands.command(name="hug", help="Give someone a warm, loving hug.")
    async def hug_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "hug", member)

    @commands.command(name="kiss", help="Give someone a sweet kiss.")
    async def kiss_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "kiss", member)

    @commands.command(name="cuddle", help="Snuggle and cuddle someone.")
    async def cuddle_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "cuddle", member)

    @commands.command(name="pat", help="Gently pat someone on the head.")
    async def pat_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "pat", member)

    @commands.command(name="pats", help="Gently pat someone on the head.")
    async def pats_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "pat", member)

    @commands.command(name="slap", help="Slap someone playfully.")
    async def slap_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "slap", member)

    @commands.command(name="punch", help="Punch someone with anime power.")
    async def punch_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "punch", member)

    @commands.command(name="bite", help="Playfully bite someone.")
    async def bite_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "bite", member)

    @commands.command(name="boop", help="Boop someone on the nose.")
    async def boop_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "boop", member)

    @commands.command(name="bonk", help="Bonk someone to horny jail.")
    async def bonk_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "bonk", member)

    @commands.command(name="bully", help="Tease and bully someone playfully.")
    async def bully_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "bully", member)

    @commands.command(name="greet", help="Warmly greet someone.")
    async def greet_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "greet", member)

    @commands.command(name="handholding", help="Hold hands with someone wholesomely.")
    async def handholding_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "handholding", member)

    @commands.command(name="handhold", help="Hold hands with someone wholesomely.")
    async def handhold_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "handholding", member)

    @commands.command(name="hold", help="Hold hands with someone wholesomely.")
    async def hold_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "handholding", member)

    @commands.command(name="kill", help="Dramatic anime battle knockout.")
    async def kill_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "kill", member)

    @commands.command(name="lick", help="Playfully lick someone.")
    async def lick_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "lick", member)

    @commands.command(name="nom", help="Nibble on someone.")
    async def nom_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "nom", member)

    @commands.command(name="poke", help="Poke someone repeatedly.")
    async def poke_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "poke", member)

    @commands.command(name="highfive", help="Give someone a high-five.")
    async def highfive_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "highfive", member)

    @commands.command(name="tickle", help="Tickle someone relentlessly.")
    async def tickle_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "tickle", member)

    @commands.command(name="stare", help="Stare intensely at someone.")
    async def stare_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "stare", member)

    @commands.command(name="cheer", help="Cheer excitedly for someone.")
    async def cheer_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "cheer", member)

    @commands.command(name="fuck", help="Express an angry cartoon outburst (harmless SFW).")
    async def fuck_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "fuck", member)

    @commands.command(name="lewd", help="Express an anime embarrassment reaction: Too lewd!")
    async def lewd_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "lewd", member)

    @commands.command(name="blush", help="Blush bright red.")
    async def blush_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "blush", member)

    @commands.command(name="cry", help="Express sadness and tears.")
    async def cry_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "cry", member)

    @commands.command(name="dance", help="Dance energetically.")
    async def dance_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "dance", member)

    @commands.command(name="deredere", help="Express sweet loving affection.")
    async def deredere_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "deredere", member)

    @commands.command(name="grin", help="Mischievous anime grin.")
    async def grin_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "grin", member)

    @commands.command(name="happy", help="Express pure joy and happiness.")
    async def happy_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "happy", member)

    @commands.command(name="pout", help="Sulking anime pout.")
    async def pout_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "pout", member)

    @commands.command(name="sleepy", help="Yawn sleepily.")
    async def sleepy_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "sleepy", member)

    @commands.command(name="smile", help="Warm, radiant smile.")
    async def smile_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "smile", member)

    @commands.command(name="smug", help="Delightfully smug expression.")
    async def smug_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "smug", member)

    @commands.command(name="scoff", help="Dismissive scoff.")
    async def scoff_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "scoff", member)

    @commands.command(name="teehee", help="Cute giggle: Teehee~!")
    async def teehee_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "teehee", member)

    @commands.command(name="thinking", help="Deep contemplative thought.")
    async def thinking_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "thinking", member)

    @commands.command(name="thumbs", help="Encouraging thumbs up.")
    async def thumbs_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "thumbs", member)

    @commands.command(name="thumbsup", help="Encouraging thumbs up.")
    async def thumbsup_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "thumbs", member)

    @commands.command(name="triggered", help="Dramatic anime triggered shake.")
    async def triggered_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "triggered", member)

    @commands.command(name="wag", help="Happy tail wagging.")
    async def wag_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "wag", member)

    @commands.command(name="wave", help="Friendly wave greeting.")
    async def wave_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_action(UnifiedContext.from_prefix(ctx), "wave", member)


# ── SLASH COMMAND GROUPS (SLASH COMMAND SLOTS DEFENSE) ───────────────────────

interact_group = app_commands.Group(name="interact", description="Anime roleplay and social interactions")
react_group = app_commands.Group(name="react", description="Anime emotional expressions and reactions")


def _register_interact_slash_subcommands() -> None:
    """Register subcommands on the /interact Slash Group."""
    # 1. Standalone social actions moved to /interact
    @app_commands.command(name="ship", description="Calculate romance compatibility between two members.")
    @app_commands.describe(user1="First member to ship", user2="Second member (optional, defaults to you)")
    async def ship_cmd(interaction: discord.Interaction, user1: discord.Member, user2: Optional[discord.Member] = None):
        cog: AnimeSocial = interaction.client.cogs["Anime & Social Interactions"]
        await cog._execute_ship(UnifiedContext.from_interaction(interaction), user1, user2)
    interact_group.add_command(ship_cmd)

    @app_commands.command(name="couple", description="Randomly matchmake a lucky couple from the server.")
    @app_commands.guild_only()
    async def couple_cmd(interaction: discord.Interaction):
        cog: AnimeSocial = interaction.client.cogs["Anime & Social Interactions"]
        await cog._execute_couple(UnifiedContext.from_interaction(interaction))
    interact_group.add_command(couple_cmd)

    @app_commands.command(name="mydog", description="Fetch a cute random dog picture and fun dog fact.")
    async def mydog_cmd(interaction: discord.Interaction):
        cog: AnimeSocial = interaction.client.cogs["Anime & Social Interactions"]
        await cog._execute_mydog(UnifiedContext.from_interaction(interaction))
    interact_group.add_command(mydog_cmd)

    @app_commands.command(name="boy", description="Fetch a stylish anime boy image.")
    async def boy_cmd(interaction: discord.Interaction):
        cog: AnimeSocial = interaction.client.cogs["Anime & Social Interactions"]
        await cog._execute_boy(UnifiedContext.from_interaction(interaction))
    interact_group.add_command(boy_cmd)

    @app_commands.command(name="anime", description="Search for anime details, rating, and episodes on AniList.")
    @app_commands.describe(query="Name of the anime to look up")
    async def anime_cmd(interaction: discord.Interaction, query: str):
        cog: AnimeSocial = interaction.client.cogs["Anime & Social Interactions"]
        await cog._execute_anime(UnifiedContext.from_interaction(interaction), query)
    interact_group.add_command(anime_cmd)

    @app_commands.command(name="roast", description="Deliver a witty, PG-13, harmless comedy roast.")
    @app_commands.describe(member="Member to playfully roast (optional)")
    async def roast_cmd(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        ratings_cog = interaction.client.cogs.get("Ratings & Fun")
        if ratings_cog and hasattr(ratings_cog, "_execute_roast"):
            await ratings_cog._execute_roast(UnifiedContext.from_interaction(interaction), member)
        else:
            await interaction.response.send_message("Roast subsystem offline.", ephemeral=True)
    interact_group.add_command(roast_cmd)

    # 2. 19 Roleplay actions
    roleplay_actions = [
        ("hug", "Give someone a warm, loving hug"),
        ("kiss", "Give someone an affectionate kiss"),
        ("cuddle", "Snuggle close and cuddle someone"),
        ("pat", "Gently pat someone on the head"),
        ("slap", "Playfully slap someone with an anime GIF"),
        ("punch", "Punch someone with anime power"),
        ("bite", "Playfully bite someone"),
        ("boop", "Boop someone on the nose"),
        ("bonk", "Playfully bonk someone with an anime mallet"),
        ("bully", "Tease and bully someone playfully"),
        ("greet", "Warmly greet someone"),
        ("handholding", "Hold hands with someone wholesomely"),
        ("knockout", "Dramatic anime battle knockout"),
        ("lick", "Playfully lick someone"),
        ("nom", "Nibble on someone playfully"),
        ("poke", "Poke someone repeatedly"),
        ("highfive", "Give someone an energetic high-five"),
        ("tickle", "Tickle someone relentlessly"),
        ("stare", "Stare intensely at someone"),
    ]

    for act, desc in roleplay_actions:
        underlying = "kill" if act == "knockout" else act

        def make_cmd(action_name: str, description: str, action_key: str):
            @app_commands.command(name=action_name, description=description)
            @app_commands.describe(member="Member to interact with (optional)")
            async def cmd(interaction: discord.Interaction, member: Optional[discord.Member] = None):
                cog: AnimeSocial = interaction.client.cogs["Anime & Social Interactions"]
                await cog._execute_action(UnifiedContext.from_interaction(interaction), action_key, member)
            return cmd

        interact_group.add_command(make_cmd(act, desc, underlying))


def _register_react_slash_subcommands() -> None:
    """Register subcommands on the /react Slash Group."""
    reaction_actions = [
        ("blush", "Blush bright red"),
        ("cry", "Express sadness and tears"),
        ("dance", "Dance energetically"),
        ("deredere", "Express sweet loving affection"),
        ("grin", "Mischievous anime grin"),
        ("happy", "Express pure joy and happiness"),
        ("pout", "Sulking anime pout"),
        ("sleepy", "Yawn sleepily"),
        ("smile", "Warm, radiant smile"),
        ("smug", "Delightfully smug expression"),
        ("scoff", "Dismissive scoff"),
        ("teehee", "Cute giggle: Teehee~!"),
        ("thinking", "Deep contemplative thought"),
        ("thumbs", "Encouraging thumbs up"),
        ("triggered", "Dramatic anime triggered shake"),
        ("wag", "Happy tail wagging"),
        ("wave", "Friendly wave greeting"),
        ("cheer", "Cheer excitedly for someone"),
        ("outburst", "Express an angry cartoon outburst (harmless comedy)"),
        ("fluster", "Express an anime embarrassment fluster reaction"),
    ]

    for act, desc in reaction_actions:
        underlying = "fuck" if act == "outburst" else ("lewd" if act == "fluster" else act)

        def make_cmd(action_name: str, action_desc: str, action_key: str):
            @app_commands.command(name=action_name, description=action_desc)
            @app_commands.describe(member="Member to react towards (optional)")
            async def cmd(interaction: discord.Interaction, member: Optional[discord.Member] = None):
                cog: AnimeSocial = interaction.client.cogs["Anime & Social Interactions"]
                await cog._execute_action(UnifiedContext.from_interaction(interaction), action_key, member)
            return cmd

        react_group.add_command(make_cmd(act, desc, underlying))


_register_interact_slash_subcommands()
_register_react_slash_subcommands()


async def setup(bot: DeathBot) -> None:
    """Setup hook to register cog and slash command groups."""
    cog = AnimeSocial(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(interact_group)
    bot.tree.add_command(react_group)
    logger.info("Loaded Anime & Social Interactions module with 49 commands.")
