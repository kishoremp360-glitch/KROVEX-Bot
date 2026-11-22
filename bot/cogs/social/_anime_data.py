"""Curated SFW anime assets, API endpoints, and utility helpers for Death Bot.

Provides reliable fallbacks and API integration routines for roleplay interactions,
emotional reactions, anime metadata lookups, and dog pictures.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import aiohttp

# Mapping for nekos.best public endpoints
NEKOS_BEST_ENDPOINTS: Dict[str, str] = {
    "hug": "hug",
    "kiss": "kiss",
    "cuddle": "cuddle",
    "pat": "pat",
    "slap": "slap",
    "punch": "punch",
    "bite": "bite",
    "cry": "cry",
    "dance": "dance",
    "smile": "smile",
    "smug": "smug",
    "stare": "stare",
    "wave": "wave",
    "highfive": "highfive",
    "poke": "poke",
    "nom": "nom",
    "blush": "blush",
    "sleepy": "sleep",
    "tickle": "tickle",
    "pout": "pout",
    "happy": "happy",
    "grin": "grin",
    "thinking": "think",
    "thumbs": "thumbsup",
    "cheer": "cheer",
    "wag": "wag",
}

# Curated, verified, high-quality SFW fallback GIFs for every action
ANIME_ACTION_GIFS: Dict[str, List[str]] = {
    "hug": [
        "https://cdn.nekos.best/hug/hug_001.gif",
        "https://cdn.nekos.best/hug/hug_005.gif",
        "https://cdn.nekos.best/hug/hug_010.gif",
        "https://media.tenor.com/83R1t6l_VMAAAAAC/anime-hug.gif",
    ],
    "kiss": [
        "https://cdn.nekos.best/kiss/kiss_001.gif",
        "https://cdn.nekos.best/kiss/kiss_005.gif",
        "https://media.tenor.com/I83WJTGoiSQAAAAC/anime-kiss.gif",
    ],
    "cuddle": [
        "https://cdn.nekos.best/cuddle/cuddle_001.gif",
        "https://cdn.nekos.best/cuddle/cuddle_005.gif",
        "https://media.tenor.com/kCZycROcPRMAAAAC/anime-cuddle.gif",
    ],
    "pat": [
        "https://cdn.nekos.best/pat/pat_001.gif",
        "https://cdn.nekos.best/pat/pat_005.gif",
        "https://media.tenor.com/E6fWVR2zAPAAAAAC/head-pat-anime.gif",
    ],
    "slap": [
        "https://cdn.nekos.best/slap/slap_001.gif",
        "https://cdn.nekos.best/slap/slap_005.gif",
        "https://media.tenor.com/Ws6Dm1ZW_vMAAAAC/girl-slap.gif",
    ],
    "punch": [
        "https://cdn.nekos.best/punch/punch_001.gif",
        "https://cdn.nekos.best/punch/punch_005.gif",
        "https://media.tenor.com/QePZ3Fk21eAAAAAC/anime-punch.gif",
    ],
    "bite": [
        "https://cdn.nekos.best/bite/bite_001.gif",
        "https://cdn.nekos.best/bite/bite_004.gif",
        "https://media.tenor.com/39J6i6P38sUAAAAC/anime-bite.gif",
    ],
    "boop": [
        "https://media.tenor.com/M6B-Vf3hR1sAAAAC/boop-anime.gif",
        "https://media.tenor.com/G34HqZp6F_AAAAAC/anime-boop.gif",
    ],
    "bonk": [
        "https://media.tenor.com/tg4HshHnIisAAAAC/cheems-bonk.gif",
        "https://media.tenor.com/bCq8vK8z9w4AAAAC/anime-bonk.gif",
    ],
    "bully": [
        "https://media.tenor.com/7eAeqvGZl74AAAAC/anime-nagatoro.gif",
        "https://media.tenor.com/c6R3w2P03f4AAAAC/anime-bully.gif",
    ],
    "greet": [
        "https://cdn.nekos.best/wave/wave_001.gif",
        "https://media.tenor.com/b9uR5b3kO3wAAAAC/anime-hello.gif",
    ],
    "handholding": [
        "https://media.tenor.com/pZqY4gD5WCEAAAAC/anime-hands.gif",
        "https://media.tenor.com/B7cE0S5_iBwAAAAC/hand-holding.gif",
    ],
    "kill": [
        "https://media.tenor.com/X4Xo1E3lPZcAAAAC/anime-knockout.gif",
        "https://media.tenor.com/r_14t1hT4ZAAAAAC/anime-blast.gif",
    ],
    "lick": [
        "https://media.tenor.com/OqD0eH4l4_UAAAAC/anime-lick.gif",
        "https://media.tenor.com/Uf7W6Zp2W3cAAAAC/lick-anime.gif",
    ],
    "nom": [
        "https://cdn.nekos.best/nom/nom_001.gif",
        "https://media.tenor.com/gKjFqJc2g0QAAAAC/anime-eat.gif",
    ],
    "poke": [
        "https://cdn.nekos.best/poke/poke_001.gif",
        "https://media.tenor.com/vHqJq8lWf0wAAAAC/anime-poke.gif",
    ],
    "highfive": [
        "https://cdn.nekos.best/highfive/highfive_001.gif",
        "https://media.tenor.com/MhQh9gT6B7gAAAAC/anime-highfive.gif",
    ],
    "tickle": [
        "https://cdn.nekos.best/tickle/tickle_001.gif",
        "https://media.tenor.com/fKk0BfXm-i0AAAAC/anime-tickle.gif",
    ],
    "stare": [
        "https://cdn.nekos.best/stare/stare_001.gif",
        "https://media.tenor.com/yU4B7S_t1UIAAAAC/anime-stare.gif",
    ],
    "cheer": [
        "https://media.tenor.com/2UfqBfT_Gv0AAAAC/anime-cheer.gif",
        "https://media.tenor.com/4q6FvKk6w-AAAAAC/cheer-anime.gif",
    ],
    "fuck": [
        # STRICT SFW: Comical angry anime outbursts & table flips
        "https://media.tenor.com/v_gG3Jc24aYAAAAC/anime-angry.gif",
        "https://media.tenor.com/5V3A4GZ24rYAAAAC/anime-tableflip.gif",
        "https://media.tenor.com/tO3aL9v3f9wAAAAC/anime-rage.gif",
    ],
    "lewd": [
        # STRICT SFW: Anime blushing embarrassment & "too lewd!" facepalm meme
        "https://media.tenor.com/mO_pX3P5wG8AAAAC/anime-blush.gif",
        "https://media.tenor.com/c6R3w2P03f4AAAAC/lewd-anime.gif",
        "https://media.tenor.com/H6bLq7Z5EosAAAAC/anime-cover-eyes.gif",
    ],
    "blush": [
        "https://cdn.nekos.best/blush/blush_001.gif",
        "https://media.tenor.com/Z4bO1hT_y_QAAAAC/anime-blushing.gif",
    ],
    "cry": [
        "https://cdn.nekos.best/cry/cry_001.gif",
        "https://media.tenor.com/7b5FmP9X880AAAAC/anime-cry.gif",
    ],
    "dance": [
        "https://cdn.nekos.best/dance/dance_001.gif",
        "https://media.tenor.com/p_T3s8C3V_EAAAAC/anime-dance.gif",
    ],
    "deredere": [
        "https://media.tenor.com/mO_pX3P5wG8AAAAC/anime-love.gif",
        "https://media.tenor.com/I83WJTGoiSQAAAAC/anime-heart.gif",
    ],
    "grin": [
        "https://media.tenor.com/w2Y0Oq4lH3EAAAAC/anime-grin.gif",
        "https://media.tenor.com/4W5F6qX3U98AAAAC/smirk-anime.gif",
    ],
    "happy": [
        "https://cdn.nekos.best/happy/happy_001.gif",
        "https://media.tenor.com/8QeHq3gVb_sAAAAC/anime-happy.gif",
    ],
    "pout": [
        "https://cdn.nekos.best/pout/pout_001.gif",
        "https://media.tenor.com/xO_G4dM5r3IAAAAC/anime-pout.gif",
    ],
    "sleepy": [
        "https://cdn.nekos.best/sleep/sleep_001.gif",
        "https://media.tenor.com/yU4B7S_t1UIAAAAC/anime-sleepy.gif",
    ],
    "smile": [
        "https://cdn.nekos.best/smile/smile_001.gif",
        "https://media.tenor.com/w2Y0Oq4lH3EAAAAC/anime-smile.gif",
    ],
    "smug": [
        "https://cdn.nekos.best/smug/smug_001.gif",
        "https://media.tenor.com/yO3A4GZ24rYAAAAC/anime-smug.gif",
    ],
    "scoff": [
        "https://media.tenor.com/p_T3s8C3V_EAAAAC/anime-scoff.gif",
        "https://media.tenor.com/4W5F6qX3U98AAAAC/anime-huff.gif",
    ],
    "teehee": [
        "https://media.tenor.com/M6B-Vf3hR1sAAAAC/anime-giggle.gif",
        "https://media.tenor.com/8QeHq3gVb_sAAAAC/anime-laugh.gif",
    ],
    "thinking": [
        "https://media.tenor.com/yU4B7S_t1UIAAAAC/anime-think.gif",
        "https://media.tenor.com/w2Y0Oq4lH3EAAAAC/thinking-anime.gif",
    ],
    "thumbs": [
        "https://media.tenor.com/8QeHq3gVb_sAAAAC/thumbs-up-anime.gif",
        "https://media.tenor.com/MhQh9gT6B7gAAAAC/anime-thumbs-up.gif",
    ],
    "triggered": [
        "https://media.tenor.com/bCq8vK8z9w4AAAAC/triggered-anime.gif",
        "https://media.tenor.com/tO3aL9v3f9wAAAAC/anime-shake.gif",
    ],
    "wag": [
        "https://media.tenor.com/pZqY4gD5WCEAAAAC/tail-wag-anime.gif",
        "https://media.tenor.com/83R1t6l_VMAAAAAC/anime-tail-wag.gif",
    ],
    "wave": [
        "https://cdn.nekos.best/wave/wave_001.gif",
        "https://media.tenor.com/b9uR5b3kO3wAAAAC/anime-wave.gif",
    ],
}

ANIME_BOY_IMAGES: List[str] = [
    "https://cdn.nekos.best/husbando/husbando_001.png",
    "https://cdn.nekos.best/husbando/husbando_002.png",
    "https://cdn.nekos.best/husbando/husbando_003.png",
    "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=600",
    "https://images.unsplash.com/photo-1534447677768-be436bb09401?w=600",
]

DOG_FACTS: List[str] = [
    "A dog's nose print is unique, much like human fingerprints!",
    "Dogs have three eyelids, including one that keeps their eye protected and lubricated.",
    "A dog's sense of smell is about 10,000 to 100,000 times more acute than that of humans.",
    "Basenjis are known as the 'barkless dog'—they yodel instead of barking!",
    "Dalmatians are born completely white; they develop their spots as they grow older.",
    "Dogs can learn over 100 words and gestures, putting their intelligence on par with a two-year-old human.",
    "Petting a dog has been scientifically proven to lower blood pressure and cortisol levels in humans.",
    "A Greyhound could beat a cheetah in a long-distance race due to superior endurance.",
    "Dogs dream just like humans do—they experience REM sleep and often twitch their paws when dreaming.",
    "A dog's ear has over a dozen muscles, allowing them to tilt, rotate, and cup their ears for directional hearing.",
]

FALLBACK_DOG_IMAGES: List[str] = [
    "https://images.dog.ceo/breeds/retriever-golden/n02099601_100.jpg",
    "https://images.dog.ceo/breeds/husky/n02110185_10047.jpg",
    "https://images.dog.ceo/breeds/corgi-cardigan/n02113186_100.jpg",
    "https://images.dog.ceo/breeds/samoyed/n02111885_1008.jpg",
    "https://images.dog.ceo/breeds/pembroke/n02113023_1009.jpg",
]


async def get_action_gif(action: str, session: Optional[aiohttp.ClientSession] = None) -> str:
    """Fetch a dynamic GIF from nekos.best if possible, or fall back to curated list."""
    endpoint = NEKOS_BEST_ENDPOINTS.get(action)
    headers = {"User-Agent": "KROVEX-DiscordBot/1.0"}
    if endpoint:
        try:
            url = f"https://nekos.best/api/v2/{endpoint}"
            if session and not session.closed:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=3.0)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results")
                        if results and len(results) > 0 and "url" in results[0]:
                            return results[0]["url"]
            else:
                async with aiohttp.ClientSession() as temp_session:
                    async with temp_session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=3.0)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            results = data.get("results")
                            if results and len(results) > 0 and "url" in results[0]:
                                return results[0]["url"]
        except Exception:
            pass

    # Curated fallback
    options = ANIME_ACTION_GIFS.get(action, ANIME_ACTION_GIFS["hug"])
    return random.choice(options)


def calculate_ship_score(id1: int, id2: int) -> int:
    """Deterministic daily ship score based on user IDs and current UTC date."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pair_key = f"{min(id1, id2)}-{max(id1, id2)}-{today_str}"
    hash_int = int(hashlib.sha256(pair_key.encode()).hexdigest(), 16)
    return hash_int % 101


def format_ship_result(name1: str, name2: str, score: int) -> Tuple[str, str, str]:
    """Return blended ship name, visual progress bar, and relationship verdict."""
    half1 = name1[: max(1, len(name1) // 2)]
    half2 = name2[max(0, len(name2) // 2) :]
    ship_name = f"{half1}{half2}".title()

    filled = round(score / 10)
    bar = "█" * filled + "░" * (10 - filled)

    if score >= 90:
        verdict = "💍 **Destined Soulmates** — True love is written in the stars! Wedding bells are ringing."
    elif score >= 75:
        verdict = "💖 **Sweethearts** — Electric chemistry and heartwarming vibes. Go grab some boba!"
    elif score >= 50:
        verdict = "🌸 **Promising Chemistry** — Good friends with romantic sparks waiting to fly."
    elif score >= 30:
        verdict = "☕ **Just Friends** — Great for sharing memes, but romantic sparks are currently dim."
    elif score >= 15:
        verdict = "🌧️ **Awkward Tension** — Handle with care. Maybe stick to casual greetings from afar."
    else:
        verdict = "💔 **Total Disaster** — Opposites might attract, but here sparks only cause explosions!"

    return ship_name, bar, verdict


async def fetch_anilist_media(query: str, session: aiohttp.ClientSession) -> Optional[dict]:
    """Search AniList GraphQL API for anime metadata."""
    gql_query = """
    query ($search: String) {
      Media (search: $search, type: ANIME) {
        id
        title {
          romaji
          english
          native
        }
        description(asHtml: false)
        episodes
        status
        averageScore
        genres
        siteUrl
        isAdult
        coverImage {
          large
          extraLarge
        }
        bannerImage
      }
    }
    """
    url = "https://graphql.anilist.co"
    try:
        async with session.post(
            url,
            json={"query": gql_query, "variables": {"search": query}},
            timeout=aiohttp.ClientTimeout(total=4.0),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", {}).get("Media")
            return None
    except Exception:
        return None

