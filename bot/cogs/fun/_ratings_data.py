"""Curated pools, metrics algorithms, and response assets for Ratings & Fun module.

All content is 100% SFW, PG-13, playfully comedic, and strictly non-harassing.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Tuple


def get_user_metric(user_id: int, metric: str, min_val: int = 0, max_val: int = 100) -> int:
    """Calculate deterministic daily rating score for a user."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    seed = f"{user_id}:{metric.lower()}:{today}"
    hash_int = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    span = (max_val - min_val) + 1
    return min_val + (hash_int % span)


def get_pair_metric(id1: int, id2: int, metric: str, min_val: int = 0, max_val: int = 100) -> int:
    """Calculate deterministic daily rating score for a pair of users."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pair_key = f"{min(id1, id2)}:{max(id1, id2)}:{metric.lower()}:{today}"
    hash_int = int(hashlib.sha256(pair_key.encode()).hexdigest(), 16)
    span = (max_val - min_val) + 1
    return min_val + (hash_int % span)


def generate_bar(value: int, min_val: int = 0, max_val: int = 100, length: int = 10) -> str:
    """Generate visual progress bar [████████░░]."""
    clamped = max(min_val, min(value, max_val))
    ratio = (clamped - min_val) / max(1, (max_val - min_val))
    filled = round(ratio * length)
    return "█" * filled + "░" * (length - filled)


# ── RATING COMMENTARIES ──────────────────────────────────────────────────────

GAY_TIERS: List[Tuple[int, str]] = [
    (100, "👑 **Supreme Rainbow Royalty** — Radiating pure prismatic joy and glitter!"),
    (80, "🌈 **Vibrant Pride Energy** — The whole rainbow celebrates with you!"),
    (60, "✨ **Glitter Parade Star** — Bright, fabulous, and unapologetically colorful!"),
    (40, "🎨 **Pastel Palette** — A lovely touch of color in the server!"),
    (20, "🌸 **Subtle Rainbow Lite** — Gentle, sparkling pastel vibes!"),
    (0, "🤍 **Monochrome Mode** — Elegant minimalist monochrome aesthetic!"),
]

LESBIAN_TIERS: List[Tuple[int, str]] = [
    (100, "👑 **Supreme Lavender Royalty** — Peak Sapphic excellence and vibrant pride!"),
    (80, "💐 **Sunset Pride Energy** — Golden hour aesthetic with immense charm!"),
    (60, "✨ **Flannel & Boba Icon** — Radiating undeniable cottagecore cool!"),
    (40, "🌸 **Sweet Blossom** — Wholesome, friendly, and colorful vibes!"),
    (20, "☕ **Cozy Friend** — Great company for a coffee date!"),
    (0, "🤍 **Neutral Aesthetic** — Keeping things simple and classic!"),
]

CUTE_TIERS: List[Tuple[int, str]] = [
    (100, "🥺 **Illegal Cuteness Overload** — The server is melting! Cuteness police are on the way!"),
    (85, "🌸 **Adorably Irresistible** — Sweet as warm mochi and fluffy kittens!"),
    (65, "✨ **Certified Cutie** — Brightens everyone's day with sheer wholesome energy!"),
    (45, "🧸 **Cozy Charm** — Lovable, friendly, and pleasant to be around!"),
    (25, "😎 **Too Cool for Cute** — Prefers looking badass over being called adorable!"),
    (0, "🗿 **Pure Gigachad Energy** — No cuteness detected, only raw chiseled stoicism!"),
]

HOT_TIERS: List[Tuple[int, str]] = [
    (100, "🔥 **Supernova Heatwave** — Melting the Discord servers! Fire extinguishers deployed!"),
    (80, "🌶️ **Extra Spicy** — Handle with oven mitts! Sizzling charisma."),
    (60, "☀️ **Warm Summer Breeze** — Glowing with effortless confidence and good vibes."),
    (40, "☕ **Warm Coffee** — Cozy, comforting, and just the right temperature."),
    (20, "🧊 **Ice Cold Cool** — Chilly, calm, and composed under pressure."),
    (0, "❄️ **Absolute Zero** — Sub-zero cryogenic frostbite! Chill level 1000."),
]

HORNY_TIERS: List[Tuple[int, str]] = [
    (100, "🚨 **MAXIMUM JAIL TIME** — *BONK!* Straight to maximum security horny jail! 🔨"),
    (75, "👀 **Suspiciously Mischievous** — Caught red-handed being a little too flirty!"),
    (50, "🎭 **Mildly Saucy** — Occasional flirty banter, but mostly under control."),
    (25, "😇 **Pure & Innocent** — Saintly aura detected! Halo shining brightly."),
    (0, "🧘 **Monk of Zen** — Ascended beyond all worldly desire. Pure tranquility."),
]

THARKI_TIERS: List[Tuple[int, str]] = [
    (100, "🌹 **Asli Majnu 1000%** — Bhai ka romance Bollywood se bhi aage nikal gaya! *BONK!* 🔨"),
    (75, "🕶️ **Filmy Aashiq** — Har dialogue me hero banne ki koshish chal rahi hai!"),
    (50, "👀 **Chhupa Rustam** — Dheere dheere line maarne me expert hai!"),
    (25, "🙏 **Sanskari Balak** — Roz subah aarti aur pooja path karta hai!"),
    (0, "😇 **Devta Purush** — Duniya ke moh-maya se 100 kos door!"),
]

IQ_TIERS: List[Tuple[int, str]] = [
    (200, "🌌 **Multiversal 4D Megamind (200+ IQ)** — Calculating quantum physics while casually sending memes."),
    (160, "🧠 **Galaxy Brain (160–199 IQ)** — Einstein's secret successor. Solving problems before they exist."),
    (130, "💡 **Big Brain Energy (130–159 IQ)** — Sharp wit, tactical mindset, and master chess player."),
    (100, "⚖️ **Balanced Common Sense (100–129 IQ)** — Dependable logic and reliable server member."),
    (75, "📺 **DVD Logo Bouncing (75–99 IQ)** — Single brain cell waiting to hit the corner of the screen."),
    (50, "🥔 **Certified Potato Mind (50–74 IQ)** — Head empty, no thoughts, just vibes and happy thoughts!"),
]

DUMB_TIERS: List[Tuple[int, str]] = [
    (100, "🤪 **Peak Goofball (100%)** — Puts phone flashlight on to look for the phone!"),
    (75, "🙃 **Certified Derp (75%)** — Pushes the door clearly marked 'PULL' with full confidence!"),
    (50, "🤔 **Occasional Lag (50%)** — Forgets what they walked into the room for!"),
    (25, "🧐 **Sharp Observer (25%)** — Rare lapses in judgment, mostly highly competent!"),
    (0, "🧠 **Flawless Precision (0%)** — Zero goofiness, immaculate coordination!"),
]

SIMP_TIERS: List[Tuple[int, str]] = [
    (100, "👑 **Supreme Simp Overlord** — Diamond tier patron, writes sonnets in Discord DMs!"),
    (75, "💐 **Master Flatterer** — Always ready with flowers, compliments, and nitro gifts!"),
    (50, "☕ **Casual Admirer** — Friendly, supportive, but keeps self-respect intact!"),
    (25, "🛡️ **Steadfast Rebel** — Unswayed by charming avatars or sweet talk!"),
    (0, "🗿 **Unstoppable Gigachad** — Immune to all simping. Focuses purely on the grind!"),
]

TOXIC_TIERS: List[Tuple[int, str]] = [
    (100, "☢️ **Radioactive Reactor** — Spams 'What a save!' 15 times after scoring!"),
    (75, "🧂 **Salty Gamer** — Blames lag, the controller, the keyboard, and the weather!"),
    (50, "🎮 **Competitive Energy** — Fierce trash talk, but GG at the end of the round."),
    (25, "🕊️ **Wholesome Teammate** — Shares healing potions and encourages the squad!"),
    (0, "🌿 **Pure Zen Garden** — Radiates serenity, hugs, and peaceful harmony!"),
]

CHUTIYA_TIERS: List[Tuple[int, str]] = [
    (100, "🤪 **Level 100 Pagalpan** — Khud hi sawaal puchh ke khud hi galat jawab deta hai!"),
    (75, "🤦 **Ultra Nautanki** — Har baat pe full emotional drama shuru ho jata hai!"),
    (50, "🤷 **Aadha Shana** — Kabhi samajhdaar, kabhi poora khurafati dimaag!"),
    (25, "🧐 **Thoda Samajhdaar** — Kabhi kabhar hi galti se ajeeb harkat karta hai!"),
    (0, "🧠 **100% Chanakya** — Zero bakwas, sirf kaam ki baatein!"),
]

ROAST_POOL: List[str] = [
    "You bring everyone so much joy... when you log out of Discord.",
    "I'd agree with you, but then we'd both be wrong.",
    "You have something on your chin... no, the third one down.",
    "Your secrets are always safe with me. I never even listen when you speak.",
    "You are the human equivalent of a participation award.",
    "I'm not saying you're clumsy, but even your Wi-Fi drops connection around you.",
    "If laughter is the best medicine, your face is curing the whole world right now.",
    "You're like a cloud. When you disappear, it turns into a beautiful sunny day.",
    "I would explain it to you, but I left my crayons at home.",
    "You have an entire lifetime to be silly, why not take today off?",
    "You remind me of a software update: whenever I see you, I immediately think 'Not now'.",
    "I'd love to roast you, but my mom told me not to burn trash.",
    "You're proof that evolution can occasionally take a vacation.",
    "Light travels faster than sound, which is why you seemed bright until you spoke.",
    "You're like a math equation with zero: confusing, pointless, and adds nothing.",
    "Your Wi-Fi speed is higher than your situational awareness.",
    "Somewhere out there, a tree is working tirelessly to produce oxygen for you. Go apologize to it.",
    "I've seen salads with better tactical decision-making skills.",
    "You are as sharp as a marble and twice as smooth.",
    "If you had another brain cell, it would be lonely.",
    "You're the reason the shampoo bottle comes with step-by-step instructions.",
    "You have the reaction time of a sloth on tranquilizers.",
    "I'm listening, I'm just taking my time to process how someone could be so incorrect.",
    "Don't worry about people stealing your ideas. If they wanted bad ones, they'd ask you directly.",
    "You're not completely useless; you can always serve as a bad example.",
]

RELATIONSHIP_STATUSES: List[str] = [
    "Secret Admirers exchanging memes in DMs 💌",
    "Married in Las Vegas by an Elvis impersonator on a dare 💍",
    "Duo carrying each other in ranked (and constantly arguing about it) 🎮",
    "Roommates who refuse to wash the dishes until they grow mold 🧼",
    "Partners in crime plotting the ultimate server snack heist 🍕",
    "Awkward handholders at the movie theater staring straight ahead 🍿",
    "Proud co-parents of a stray orange cat that only visits for food 🐱",
    "Enemies to lovers slow-burn drama across 50 Discord channels 🎭",
    "Besties sharing one brain cell between them on weekends 🧠",
    "Time travelers from different eras trying to make Discord work ⏳",
    "Boba tea addicts competing over who orders extra boba bubble_tea:",
    "Gym bros arguing over who gets to spot the last bench press 🏋️",
    "Conspiracy theorists discussing whether bots dream of electric sheep 🛸",
    "Late-night voice call companions who both fell asleep with unmuted mics 💤",
    "Rival chefs arguing over whether pineapple belongs on pizza 🍍",
]


def get_tier_commentary(score: int, tiers: List[Tuple[int, str]]) -> str:
    """Find appropriate commentary for a given numerical score."""
    for threshold, commentary in tiers:
        if score >= threshold:
            return commentary
    return tiers[-1][1]

