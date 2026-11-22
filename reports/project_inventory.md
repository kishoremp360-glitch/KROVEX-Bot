# KROVEX — Project Architectural Inventory

**Inspection Date:** 2026-11-17  
**Branch:** `qa/krovex-complete-audit`  
**Repository:** `https://github.com/kishorerai390/krovex`  
**Development Guild ID:** `1560990395666538529`  
**Bot Client ID:** `1570428426974662718`

---

## 1. System Architectural Overview

| Subsystem | Directory | Total Modules / Components | Core Role |
|---|---|---|---|
| **Entry Point & Lifecycle** | `bot/` & `bot/core/` | 6 modules | Gateway lifecycle, bot subclass, checks, error & event handling |
| **Command Cogs** | `bot/cogs/` | 21 Cog directories | User-facing Discord commands (Slash & Prefix), views, and interactions |
| **Autonomous Services** | `bot/services/` | 10 root services, 2 sub-packages (`ai/`, `music/`) | Security, AutoMod, Logging, Music, Voice, Mentions, Roles, AI SOUL |
| **Data Persistence Layer** | `bot/database/` | 1 manager, 1 connection pool, 11 repository modules | SQLite with WAL mode, parameterized transactions, atomic operations (71 tables) |
| **UI & Styling Framework** | `bot/utils/` | 4 utility modules | Embed builders, typography, custom application emojis, permissions |
| **Automated Test Matrix** | `tests/` | 58 test suites | Comprehensive unit, integration, mock-gateway, and regression suites |

---

## 2. Cog Inventory (21 Modules)

| # | Cog Category | Primary Directory | Scope & Capabilities |
|---|---|---|---|
| 1 | **Admin** | `bot/cogs/admin/` | Server configuration, channel management, setup wizard, Owner Dashboard |
| 2 | **AutoMod** | `bot/cogs/automod/` | Spam, link, invite, mentions, caps, and attachment rule enforcement |
| 3 | **Economy** | `bot/cogs/economy/` | Wallet/bank, daily/weekly streaks, work/crime economy transactions |
| 4 | **Fun** | `bot/cogs/fun/` | Memes, roast, roll, 8ball, rate systems, aesthetic interactions |
| 5 | **Leveling** | `bot/cogs/leveling/` | XP tracking, rank cards, leaderboard, milestone rewards |
| 6 | **Logging** | `bot/cogs/logging/` | Event dispatchers for server, channels, roles, messages, and members |
| 7 | **Mimic** | `bot/cogs/mimic/` | Webhook identity mimicry, impersonation safeguards |
| 8 | **Minigames** | `bot/cogs/minigames/` | Interactive Discord UI games (TicTacToe, Connect4, Blackjack, Coinflip) |
| 9 | **Moderation** | `bot/cogs/moderation/` | Ban, unban, kick, timeout, purge, warn, slowmode, channel locking |
| 10 | **Music** | `bot/cogs/music/` | Audio player, track resolver, queue management, volume, lyrics |
| 11 | **OwnerVC** | `bot/cogs/ownervc/` | 3-Dropdown Owner & Staff Control Center, VC loop, voice bans |
| 12 | **ReactionRoles** | `bot/cogs/reactionroles/` | Button & select menu persistent reaction role panels |
| 13 | **Security** | `bot/cogs/security/` | Anti-nuke, anti-raid, anti-webhook abuse, emergency lockdown |
| 14 | **Shop** | `bot/cogs/shop/` | Virtual store item catalog, purchasing, inventory management |
| 15 | **Social** | `bot/cogs/social/` | Ship, couple, anime reactions, hug, pat, kiss, user banners |
| 16 | **SOUL** | `bot/cogs/soul/` | Gemini-powered conversational AI companion with context memory |
| 17 | **Tickets** | `bot/cogs/tickets/` | Support ticket creation, claim/unclaim, transcripts, ratings |
| 18 | **Utility** | `bot/cogs/utility/` | Help pagination, botinfo, serverinfo, userinfo, uptime, ping |
| 19 | **Vault** | `bot/cogs/vault/` | Emergency disaster recovery, state archives, integrity drills |
| 20 | **Voice** | `bot/cogs/voice/` | Voice state diagnostics, temporary dynamic voice channels |
| 21 | **Welcome** | `bot/cogs/welcome/` | Multi-embed welcome cards, autoroles, DM greetings, goodbye logs |

---

## 3. Autonomous Services (10 Root Services + Subsystems)

| Service Name | Source File | Background Tasks & Hooks |
|---|---|---|
| **SecurityService** | `bot/services/security_service.py` | Anti-nuke tracking window, rate limits, snapshot restoration |
| **AutoModService** | `bot/services/automod_service.py` | In-memory token-bucket spam filters, regex invite/link scanning |
| **LoggingService** | `bot/services/logging_service.py` | Asynchronous natural-language embed dispatch for 14 event types |
| **VoiceService** | `bot/services/voice_service.py` | State tracking, dynamic voice room provisioning & auto-cleanup |
| **WelcomeService** | `bot/services/welcome_service.py` | Invite tracking, custom card rendering, role attribution |
| **BotRoleService** | `bot/services/bot_role_service.py` | Hoisted role auto-provisioning, position sorting, 403 fallbacks |
| **MentionService** | `bot/services/mention_service.py` | Ghost-ping detection, real-time mention alerts, user DM dispatch |
| **DMQueueService** | `bot/services/dm_queue_service.py` | Bounded priority queue with rate-limit backoff for safe user DMs |
| **MusicService** | `bot/services/music_service.py` | Audio pipeline coordination, queue persistence, stream recovery |
| **CustomCommandService** | `bot/services/custom_command_service.py` | Custom server trigger execution and tag evaluation |
