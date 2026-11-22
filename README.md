---
title: KROVEX
emoji: 💀
colorFrom: purple
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# 🔮 Death Bot • Next-Generation All-In-One Discord Bot
### Phase 1: Foundation & Modular Architecture

**Death Bot** is a high-performance, modular, all-in-one Discord bot built from the ground up with **Python 3.11+**, **discord.py 2.x**, and **MongoDB Atlas**. Designed with a signature **Obsidian Dark & Neon Purple** visual identity, it features an enterprise-grade service-repository architecture, unified dual command handling (supporting both **Slash Commands `/`** and **Prefix Commands `!`** with 100% shared business logic), and native subsystems for **Premium Music**, **Advanced Voice Status Tracking**, and **Interactive Member Onboarding**.

---

## 📑 Table of Contents
1. [Core Features & Architecture](#-core-features--architecture)
2. [Visual Identity & Design System](#-visual-identity--design-system)
3. [Technology Stack](#-technology-stack)
4. [Project Directory Layout](#-project-directory-layout)
5. [Dual Command Architecture](#-dual-command-architecture)
6. [Database Schema & Indexes](#-database-schema--indexes)
7. [Installation & Local Setup](#-installation--local-setup)
8. [Configuration Reference](#-configuration-reference)
9. [Running Automated Tests](#-running-automated-tests)
10. [Phase 2 Implementation Roadmap](#-phase-2-implementation-roadmap)

---

## ⚡ Core Features & Architecture

### 1. Dual Command System (Shared Business Logic)
- **Zero Duplication**: Business logic is decoupled from Discord gateway contexts into unified handlers using `UnifiedContext`.
- **Dual Support**: Every command operates identically as a Slash command (`/ping`) or a Prefix command (`!ping`).
- **Dynamic Guild Prefixes**: Server administrators can customize the prefix per guild with automatic in-memory caching to avoid redundant database reads.
- **Unified Permission & Cooldown Engine**: Standardized checks and exception handlers for both interactions and messages.

### 2. Premium Music System Architecture
- Queue management, volume clamping, loop controls (`off`, `track`, `queue`), and playback state tracking (`idle`, `playing`, `paused`, `stopped`).
- High-performance domain models (`AudioSourceInfo`, `Track`, `PlayerState`).
- PyNaCl integration and optional Lavalink cluster support (disabled by default in Phase 1).

### 3. Voice Activity & Status Tracking Architecture
- Event-driven tracking via `on_voice_state_update` monitoring joins, leaves, and channel switches.
- In-memory session tracking with throttled database updates and rate-limited live embed refresh to prevent Discord API abuse.
- Voice leaderboards and individual time tracking.

### 4. Custom Welcome & Onboarding Architecture
- Dynamic string template rendering (`{user}`, `{user_name}`, `{server}`, `{member_count}`).
- Automatic role assignment with role hierarchy validation.
- Direct message greetings with closed-DM fallback handling.
- Farewell / departure logging.

---

## 🎨 Visual Identity & Design System

Death Bot utilizes an **Obsidian Dark** canvas with vibrant **Neon Purple** accents:
- **Primary / Brand Accent**: `0x9D4EDD` (Electric Neon Purple)
- **Secondary Accent**: `0x7B2CBF` (Royal Violet)
- **Success Accent**: `0x00F5A0` (Neon Emerald)
- **Error Accent**: `0xFF3366` (Neon Rose / Crimson)
- **Warning Accent**: `0xF59E0B` (Amber Flame)
- **Dark Neutral**: `0x111216` (Obsidian)

All responses utilize standardized embed layouts with consistent typography, custom emojis, and error reference codes.

---

## 🛠️ Technology Stack

| Component | Library / Framework | Purpose |
|---|---|---|
| **Language** | Python 3.11+ (Tested on 3.14) | Core asynchronous programming language |
| **Discord API** | discord.py 2.x | Gateway communication, slash command tree, sharding |
| **Database** | MongoDB Atlas & Motor 3.x | Scalable asynchronous NoSQL document storage |
| **Voice Processing** | PyNaCl & yt-dlp | Native voice encryption and audio stream extraction |
| **Image Generation** | Pillow 10+ | Dynamic canvas welcome card rendering |
| **Networking** | aiohttp | Asynchronous HTTP client operations |
| **Configuration** | python-dotenv | Secure environment variable management |
| **Testing** | pytest & pytest-asyncio | Automated unit, service, and integrity testing |

---

## 📂 Project Directory Layout

```
Death Bot/
├── .env.example                     # Environment configuration template
├── .gitignore                       # Git exclusion rules
├── requirements.txt                 # Pinned dependencies
├── README.md                        # Documentation and guides
├── logs/
│   └── bot.log                      # Rotated log files
├── bot/
│   ├── main.py                      # Application bootstrap and entry point
│   ├── config.py                    # Environment validation and credential masking
│   ├── core/
│   │   ├── bot.py                   # AutoShardedBot engine subclass
│   │   ├── context.py               # UnifiedContext bridging Slash & Prefix
│   │   ├── checks.py                # Permission decorators and checks
│   │   ├── error_handler.py         # Global error handling for Prefix & Slash
│   │   └── event_handler.py         # Gateway event dispatcher
│   ├── database/
│   │   ├── connection.py            # Motor MongoDB connection manager
│   │   ├── models.py                # Typed dataclass schemas
│   │   └── repositories/            # Data access layer
│   │       ├── base.py              # Generic async CRUD operations
│   │       ├── guild_repo.py        # Guild settings & custom prefix caching
│   │       ├── user_repo.py         # User profiles, XP, balance
│   │       ├── voice_repo.py        # Voice sessions & guild voice settings
│   │       ├── welcome_repo.py      # Welcome, farewell & autorole settings
│   │       ├── music_repo.py        # Guild audio preferences & 24/7 mode
│   │       ├── command_usage_repo.py# Command telemetry & analytics
│   │       └── moderation_repo.py   # Moderation cases & infraction history
│   ├── services/
│   │   ├── music_service.py         # Playback state, queues, volume & loop
│   │   ├── voice_service.py         # Real-time voice state & throttled embeds
│   │   └── welcome_service.py       # Member onboarding, templates & autoroles
│   ├── cogs/
│   │   ├── music/cog.py             # Music diagnostics and settings
│   │   ├── voice/cog.py             # Voice activity metrics and time tracking
│   │   ├── welcome/cog.py           # Welcome preview and status commands
│   │   ├── utility/
│   │   │   ├── system.py            # Ping, botinfo, uptime, health, prefix
│   │   │   └── help.py              # Dynamic categorized help menu
│   │   ├── moderation/cog.py        # Slowmode and moderation tooling
│   │   ├── fun/cog.py               # Roll, coinflip, 8ball mini-games
│   │   └── social/cog.py            # Profiles and daily currency rewards
│   └── utils/
│       ├── embeds.py                # Neon Purple EmbedBuilder
│       ├── logger.py                # Rotating colored logger with secret masking
│       └── permissions.py           # Permission and voice state validators
└── tests/
    ├── test_config.py               # Configuration & secret masking tests
    ├── test_embeds.py               # Embed generation tests
    ├── test_database.py             # Database models and manager tests
    ├── test_command_architecture.py # UnifiedContext prefix/slash tests
    ├── test_services.py             # Music, Voice, and Welcome service tests
    └── test_bot_integrity.py        # Python syntax & cog setup verification
```

---

## 🚀 Installation & Local Setup

### Step 1: Clone or Navigate to the Repository
```bash
cd "f:\Death Bot"
```

### Step 2: Install Python Dependencies
Ensure you have Python 3.11 or newer installed:
```bash
python -m pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Copy the `.env.example` template to `.env`:
```bash
# On Windows PowerShell:
Copy-Item .env.example .env

# On Linux/macOS:
cp .env.example .env
```

Edit `.env` and fill in your credentials:
```env
DISCORD_TOKEN=your_actual_bot_token_here
MONGODB_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority
MONGODB_DATABASE=death_bot
DEFAULT_PREFIX=!
OWNER_IDS=your_discord_user_id
```

> **Security Note:** Never commit your `.env` file or disclose your bot token. The logger and configuration manager automatically redact tokens and database passwords.

### Step 4: Run the Bot
```bash
python bot/main.py
```

---

## 🧪 Running Automated Tests

Death Bot includes a comprehensive test suite covering syntax compilation, configuration validation, secret masking, database schemas, service logic, and the unified command engine.

Execute the test suite using `pytest`:
```bash
python -m pytest -v
```

All 26 automated unit tests should pass with zero failures.

---

## 🔮 Phase 2 Implementation Roadmap

Once Phase 1 is reviewed and approved, Phase 2 will deliver:

1. **Full Music Audio Pipeline**:
   - `yt-dlp` integration with audio extraction and FFmpeg streaming.
   - Interactive persistent Discord UI (Play/Pause, Skip, Volume, Shuffle, 24/7 buttons).
   - Lyrics extraction and audio filter effects (Bass Boost, Nightcore, Vaporwave).
2. **Live Voice Status Dashboard**:
   - Auto-updating channel status boards with Discord message components.
   - Voice time leaderboards and XP accrual for voice engagement.
3. **Pillow Canvas Welcome Cards**:
   - Custom graphical banners rendered with member avatar, background textures, and typography.
   - Webhook-based invite tracker to log who invited new members.
4. **Command Expansion**:
   - Incremental expansion towards the 300+ functional command roadmap across Moderation, Social, Economy, Fun, and Utility categories.

