"""Central Application Emoji Registry for KROVEX Discord Bot.

Maintains registered Discord Application Emojis with verified IDs, semantic constants,
Discord formatting helpers, and reliable Unicode fallbacks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import discord


@dataclass(frozen=True)
class AppEmoji:
    """Descriptor for an individual registered Discord Application Emoji."""

    name: str
    id: int
    fallback: str
    animated: bool = False

    @property
    def discord_format(self) -> str:
        """Standard Discord message formatting `<:name:id>` or `<a:name:id>`."""
        prefix = "a" if self.animated else ""
        return f"<{prefix}:{self.name}:{self.id}>"

    @property
    def partial(self) -> discord.PartialEmoji:
        """Construct a discord.PartialEmoji instance for UI components."""
        return discord.PartialEmoji(name=self.name, id=self.id, animated=self.animated)

    def to_ui(self, use_fallback: bool = False) -> Union[discord.PartialEmoji, str]:
        """Return PartialEmoji for UI components or fallback string if custom emojis are disabled."""
        if use_fallback:
            return self.fallback
        return self.partial

    def format(self, use_fallback: bool = False) -> str:
        """Format emoji for embed titles, descriptions, and text messages."""
        return self.fallback if use_fallback else self.discord_format

    def __str__(self) -> str:
        return self.discord_format


class KrovexEmoji:
    """Central registry of registered Discord Application Emojis for KROVEX.

    Registered Application Emojis:
    - `550849blue`                    (ID: `1571035143748194304`, Animated) -> Music / Diamond / Status / Info
    - `131720purplearrow`             (ID: `1571036183751036928`, Animated) -> Navigation / Next / Arrow
    - `275933holliens`                (ID: `1571036451825647677`, Animated) -> Moderation / Skull / Danger
    - `414205emoangel`                (ID: `1571036723729928202`, Animated) -> Welcome / Angel / Special
    - `828216bats`                    (ID: `1571037209098850428`, Animated) -> Security / Bats / Panic / Anti-Nuke
    - `881980whitecrown`              (ID: `1571039260721684480`, Animated) -> Leaderboard / VIP / XP / Top Crown
    - `684179cross`                   (ID: `1571039956179099729`, Animated) -> Cross / Cancel / Close / Denied
    - `65954pinkbutterflies`          (ID: `1571040335944097803`, Animated) -> Aesthetic / Social / Profile
    - `8632chechbw`                   (ID: `1571047860814741524`, Animated) -> Verified / Audit / Check BW / Log
    - `7163milk3`                     (ID: `1571053751131709501`, Animated) -> Economy / Fun / Milk / Daily / Coins
    - `560905maketicket`              (ID: `1571145823042019379`, Animated) -> Ticket / Support / Panels / Help
    - `968736rocket`                  (ID: `1571160565622120549`, Animated) -> Boost / Launch / Speed / Setup
    - `38124shieldcrown`              (ID: `1571189876177764493`, Static)   -> Admin / Shield Crown / Owner / Server Info
    - `843139correct`                 (ID: `1571190648630153368`, Static)   -> Correct / Success / Active / Approved
    - `602393rightangleallwhitewing`  (ID: `1571190676081869050`, Animated) -> White Wing / Arrow / Sub-bullet
    - `3972failed`                    (ID: `1571191511528505384`, Static)   -> Failed / Error / Disabled / Denied
    - `6850warning`                   (ID: `1571191536472031262`, Animated) -> Warning / Alert / Caution / Timeout
    """

    # Exact registered application emojis
    BLUE = AppEmoji(name="550849blue", id=1571035143748194304, fallback="💎", animated=True)
    PURPLE_ARROW = AppEmoji(name="131720purplearrow", id=1571036183751036928, fallback="▶️", animated=True)
    HOLLIENS = AppEmoji(name="275933holliens", id=1571036451825647677, fallback="💀", animated=True)
    EMO_ANGEL = AppEmoji(name="414205emoangel", id=1571036723729928202, fallback="🪽", animated=True)
    BATS = AppEmoji(name="828216bats", id=1571037209098850428, fallback="🦇", animated=True)
    WHITE_CROWN = AppEmoji(name="881980whitecrown", id=1571039260721684480, fallback="👑", animated=True)
    CROSS = AppEmoji(name="684179cross", id=1571039956179099729, fallback="❌", animated=True)
    PINK_BUTTERFLIES = AppEmoji(name="65954pinkbutterflies", id=1571040335944097803, fallback="🦋", animated=True)
    CHECK_BW = AppEmoji(name="8632chechbw", id=1571047860814741524, fallback="✔️", animated=True)
    MILK = AppEmoji(name="7163milk3", id=1571053751131709501, fallback="🥛", animated=True)
    MAKE_TICKET = AppEmoji(name="560905maketicket", id=1571145823042019379, fallback="🎫", animated=True)
    ROCKET = AppEmoji(name="968736rocket", id=1571160565622120549, fallback="🚀", animated=True)
    SHIELD_CROWN = AppEmoji(name="38124shieldcrown", id=1571189876177764493, fallback="🛡️", animated=False)
    CORRECT = AppEmoji(name="843139correct", id=1571190648630153368, fallback="✅", animated=False)
    WHITE_WING = AppEmoji(name="602393rightangleallwhitewing", id=1571190676081869050, fallback="🪽", animated=True)
    FAILED = AppEmoji(name="3972failed", id=1571191511528505384, fallback="❌", animated=False)
    WARNING = AppEmoji(name="6850warning", id=1571191536472031262, fallback="⚠️", animated=True)
    LIGHTNING = AppEmoji(name="25801", id=1571196825220943902, fallback="⚡", animated=True)
    TADA = AppEmoji(name="3368kokotadance", id=1571199726395588772, fallback="🎉", animated=True)

    # 35 Newly Registered Emojis (Total 54 Application Emojis)
    FALLING_PETALS = AppEmoji(name="62524fallingpetals", id=1571209707115253943, fallback="🌸", animated=True)
    VICTORY = AppEmoji(name="90177vforvictory", id=1571209730976649246, fallback="✌️", animated=False)
    HELLO_KITTY_LOVE = AppEmoji(name="73094hellokittylove", id=1571209757639843931, fallback="💖", animated=True)
    CRYSTALS = AppEmoji(name="34196crystals", id=1571209787922718743, fallback="💎", animated=True)
    YOU_SUCK = AppEmoji(name="99311yousucksign", id=1571210484907114617, fallback="👎", animated=False)
    HELLO_KITTY = AppEmoji(name="99590hellokitty", id=1571210487314784448, fallback="🐱", animated=False)
    GOLD_STAR = AppEmoji(name="578502star", id=1571210489898205315, fallback="⭐", animated=False)
    HELLO_KITTY_DANCE = AppEmoji(name="48106hellokiitty", id=1571210494772125827, fallback="💃", animated=True)
    CUTE_STAR = AppEmoji(name="53030cutecutestar", id=1571210499948019712, fallback="✨", animated=True)
    PURPLE_SPARKLES = AppEmoji(name="55256purplesparkles", id=1571210505786495016, fallback="✨", animated=True)
    PURPLE_BUTTERFLY = AppEmoji(name="55926butterfly", id=1571210511280906240, fallback="🦋", animated=True)
    BLOSSOMS = AppEmoji(name="56308blossoms", id=1571210513428516912, fallback="🌸", animated=True)
    ANIMATED_CROSS = AppEmoji(name="57819x", id=1571210516141969489, fallback="❌", animated=True)
    STARBUCKS = AppEmoji(name="60429starbucks", id=1571210520760033390, fallback="☕", animated=True)
    PURPLE_MOON = AppEmoji(name="63092moon", id=1571210526812541050, fallback="🌙", animated=True)
    RAINBOW_STAR = AppEmoji(name="63591rainbowhappystar", id=1571210529454948563, fallback="⭐", animated=False)
    KITTY_YES = AppEmoji(name="72921hellokittyyes", id=1571210532105617418, fallback="✅", animated=True)
    KITTY_MUFFIN = AppEmoji(name="84604kittymifin", id=1571210534395838474, fallback="🧁", animated=False)
    PINK_STARS = AppEmoji(name="89920starspink5", id=1571210538304667758, fallback="✨", animated=True)
    WHITE_FLOWERS = AppEmoji(name="96650flowerswhite", id=1571210540624257044, fallback="💮", animated=True)
    CHERRY_SPIN = AppEmoji(name="99088cherryblossomspin", id=1571210546278305954, fallback="🌸", animated=True)
    CRESCENT_MOON = AppEmoji(name="10601moon", id=1571210569422479550, fallback="🌙", animated=True)
    CINNAMOROLL = AppEmoji(name="13083cinnamoji1", id=1571210572102504578, fallback="🤍", animated=True)
    ANGEL_STATIC = AppEmoji(name="14408angelmoji", id=1571210588523204831, fallback="🪽", animated=False)
    RAINBOW_KNIFE = AppEmoji(name="17684rainbowknife", id=1571210592121786398, fallback="🔪", animated=True)
    ANIMATED_HEART = AppEmoji(name="19539heart", id=1571210595079037040, fallback="💖", animated=True)
    DRAMA_QUEEN = AppEmoji(name="41624dramaqueentext", id=1571210597712924823, fallback="👑", animated=False)
    CUTE_STAR_STATIC = AppEmoji(name="42220cutestar", id=1571210600003145972, fallback="⭐", animated=False)
    MINI_STAR = AppEmoji(name="43893star", id=1571210602670587934, fallback="⭐", animated=False)
    CRYSTAL_BALL = AppEmoji(name="44519crystalball", id=1571210605644488774, fallback="🔮", animated=False)
    BUBBLES = AppEmoji(name="45572bubbles", id=1571210608127377469, fallback="🫧", animated=False)
    MILK_MOCHA = AppEmoji(name="46712milkandmochaforehead", id=1571210610484445275, fallback="🐻", animated=False)
    BLUE_BUTTERFLIES = AppEmoji(name="47599butterflies", id=1571210613072597174, fallback="🦋", animated=True)
    SCORE_100 = AppEmoji(name="6433100", id=1571210615286931477, fallback="💯", animated=True)
    YAE_HEART = AppEmoji(name="7348yaeheartsparkles", id=1571210652024836176, fallback="💖", animated=True)
    NITRO = AppEmoji(name="495162nitro", id=1571362065866559608, fallback="🚀", animated=True)
    GREEN_SPARKLES = AppEmoji(name="5267greensparkles", id=1571360362685538404, fallback="✨", animated=True)

    # Semantic developer aliases
    SUCCESS = CORRECT
    ERROR = FAILED
    WARN = WARNING
    ALERT = WARNING
    ADMIN = SHIELD_CROWN
    SHIELD = SHIELD_CROWN
    SECURITY = BATS
    WELCOME = EMO_ANGEL
    MODERATION = HOLLIENS
    NAV_NEXT = PURPLE_ARROW
    ARROW = PURPLE_ARROW
    BULLET = WHITE_WING
    WING = WHITE_WING
    MUSIC = BLUE
    STATUS = BLUE
    VIP = WHITE_CROWN
    CROWN = WHITE_CROWN
    LEADERBOARD = WHITE_CROWN
    DENIED = CROSS
    CANCEL = CROSS
    AESTHETIC = PINK_BUTTERFLIES
    SOCIAL = PINK_BUTTERFLIES
    TICKET = MAKE_TICKET
    BOOST = ROCKET
    LAUNCH = ROCKET
    SPEED = ROCKET
    FUN = MILK
    ECONOMY = MILK
    COIN = CRYSTALS
    COINS = CRYSTALS
    ELECTRIC = LIGHTNING
    BOLT = LIGHTNING
    ENERGY = LIGHTNING
    POWER = LIGHTNING
    FAST = LIGHTNING
    PING = LIGHTNING
    CELEBRATE = TADA
    PARTY = TADA
    DANCE = TADA
    WIN = TADA
    KOKOTA = TADA
    VICTORY_SIGN = VICTORY
    LOSE = YOU_SUCK
    DEFEAT = YOU_SUCK
    PERFECT = SCORE_100
    SPARKLES = PURPLE_SPARKLES
    MAGIC = PURPLE_SPARKLES
    HEART = ANIMATED_HEART
    LOVE = ANIMATED_HEART
    PETALS = FALLING_PETALS
    SAKURA = CHERRY_SPIN
    KNIFE = RAINBOW_KNIFE
    BOOST_NITRO = NITRO
    VERIFIED_SPARKLES = GREEN_SPARKLES
    CAFE = STARBUCKS
    MUFFIN = KITTY_MUFFIN
    YES = KITTY_YES
    APPROVED_YES = KITTY_YES
    MOON = CRESCENT_MOON
    DARK_MOON = PURPLE_MOON
    FORTUNE = CRYSTAL_BALL
    SOUL_SPARKLES = PINK_STARS
    WHITE_PETALS = WHITE_FLOWERS

    _ALL_EMOJIS: List[AppEmoji] = [
        BLUE,
        PURPLE_ARROW,
        HOLLIENS,
        EMO_ANGEL,
        BATS,
        WHITE_CROWN,
        CROSS,
        PINK_BUTTERFLIES,
        CHECK_BW,
        MILK,
        MAKE_TICKET,
        ROCKET,
        SHIELD_CROWN,
        CORRECT,
        WHITE_WING,
        FAILED,
        WARNING,
        LIGHTNING,
        TADA,
        FALLING_PETALS,
        VICTORY,
        HELLO_KITTY_LOVE,
        CRYSTALS,
        YOU_SUCK,
        HELLO_KITTY,
        GOLD_STAR,
        HELLO_KITTY_DANCE,
        CUTE_STAR,
        PURPLE_SPARKLES,
        PURPLE_BUTTERFLY,
        BLOSSOMS,
        ANIMATED_CROSS,
        STARBUCKS,
        PURPLE_MOON,
        RAINBOW_STAR,
        KITTY_YES,
        KITTY_MUFFIN,
        PINK_STARS,
        WHITE_FLOWERS,
        CHERRY_SPIN,
        CRESCENT_MOON,
        CINNAMOROLL,
        ANGEL_STATIC,
        RAINBOW_KNIFE,
        ANIMATED_HEART,
        DRAMA_QUEEN,
        CUTE_STAR_STATIC,
        MINI_STAR,
        CRYSTAL_BALL,
        BUBBLES,
        MILK_MOCHA,
        BLUE_BUTTERFLIES,
        SCORE_100,
        YAE_HEART,
        NITRO,
        GREEN_SPARKLES,
    ]

    @classmethod
    def get_by_name(cls, name: str) -> Optional[AppEmoji]:
        """Lookup an application emoji by exact registered name."""
        for emoji in cls._ALL_EMOJIS:
            if emoji.name == name:
                return emoji
        return None

    @classmethod
    def get_by_id(cls, emoji_id: int) -> Optional[AppEmoji]:
        """Lookup an application emoji by registered integer ID."""
        for emoji in cls._ALL_EMOJIS:
            if emoji.id == emoji_id:
                return emoji
        return None

    @classmethod
    def all_emojis(cls) -> List[AppEmoji]:
        """Return a list of all registered application emojis."""
        return list(cls._ALL_EMOJIS)
