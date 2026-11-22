# KROVEX — Command Registry Architecture & Sync Audit

**Inspection Date:** 2026-11-17  
**Branch:** `qa/krovex-complete-audit`  
**Max Allowed Root Slash Limit (Discord):** 100  
**Current Root Slash Count:** **43** (57 Available Slots / Headroom)  
**Total Root Prefix Commands:** **415** (447 total operations including subcommands)

---

## 1. Slash Command Architecture (43 Root Commands)

KROVEX organizes its massive command catalog using a hybrid structure: **20 Group Cogs** for organized feature discovery, and **23 Standalone Shortcuts** for high-frequency user actions.

### A. 20 Slash Command Groups (380 Subcommands)

| # | Group Name | Total Subcommands | Primary Scope | Sample Subcommands |
|---|---|---|---|---|
| 1 | `/admin` | 25 | Server & Channel Management | `prefix`, `channelcreate`, `channeldelete`, `categorycreate`, `channelmove` |
| 2 | `/automod` | 22 | Automated Rule Enforcement | `status`, `rules`, `filterbadwords`, `filterinvites`, `filterlinks`, `filtercaps` |
| 3 | `/eco` | 22 | Virtual Currency Economy | `balance`, `bank`, `deposit`, `withdraw`, `daily`, `weekly`, `work`, `crime` |
| 4 | `/game` | 20 | Mini-Games & Entertainment | `coinflip`, `dice`, `rps`, `roulette`, `diceduel`, `tictactoe`, `connectfour`, `blackjack` |
| 5 | `/interact` | 25 | Social & Anime Interactions | `ship`, `couple`, `mydog`, `boy`, `anime`, `roast`, `hug`, `kiss`, `pat` |
| 6 | `/level` | 19 | Leveling & XP Progression | `rank`, `leaderboard`, `setup`, `toggle`, `channel`, `message`, `reward` |
| 7 | `/logs` | 22 | Server Event Logging | `channel`, `status`, `autolog`, `reset`, `disable`, `enable`, `toggle`, `ignorechannel` |
| 8 | `/music` | 21 | Audio Streaming & Control | `filter`, `search`, `resume`, `forceskip`, `previous`, `disconnect`, `nowplaying` |
| 9 | `/playlist` | 5 | Music Playlist Management | `create`, `add`, `play`, `list`, `delete` |
| 10 | `/rate` | 13 | Fun Ratings & Evaluators | `rainbow`, `harmony`, `cute`, `howhot`, `mischief`, `flirt`, `dumb`, `simp` |
| 11 | `/react` | 20 | Expressive Anime Reactions | `blush`, `cry`, `dance`, `deredere`, `grin`, `happy`, `pout`, `sleepy` |
| 12 | `/rr` | 16 | Reaction Role Panels | `create`, `remove`, `buttonpanel`, `buttonadd`, `menucreate`, `menuadd` |
| 13 | `/security` | 25 | Anti-Nuke & Defense | `status`, `antinuke`, `antiraid`, `antispam`, `antibot`, `antibanthreshold` |
| 14 | `/setup` | 7 | Server Setup Wizards | `server`, `roles`, `reactionroles`, `logging`, `welcome`, `goodbye`, `rollback` |
| 15 | `/shop` | 16 | Virtual Item Marketplace | `view`, `setup`, `add`, `edit`, `remove`, `item`, `list`, `buy` |
| 16 | `/soul` | 5 | Conversational AI Companion | `status`, `stop`, `settings`, `history`, `usage` |
| 17 | `/ticket` | 25 | Customer Support Tickets | `setup`, `panel`, `create`, `close`, `reopen`, `claim`, `unclaim`, `add` |
| 18 | `/util` | 13 | Server & Bot Utilities | `uptime`, `botinfo`, `banner`, `invite`, `support`, `membercount`, `roleinfo` |
| 19 | `/vc` | 25 | Voice Channel Management | `kick`, `ban`, `unban`, `kickall`, `banall`, `unbanall`, `mute`, `unmute` |
| 20 | `/welcome` | 14 | Onboarding & Greetings | `status`, `test`, `setup`, `message`, `embed`, `color`, `image`, `dm` |

### B. 23 Standalone Slash Shortcuts

The following 23 commands exist directly at the slash root for quick, fluid access:
* **Moderation:** `/ban`, `/kick`, `/timeout`, `/untimeout`, `/unban`, `/warn`, `/warnings`, `/clearwarns`, `/purge`, `/lock`, `/unlock`, `/slowmode`
* **Music:** `/play`, `/pause`, `/skip`, `/stop`, `/queue`
* **Information & Governance:** `/help`, `/ping`, `/avatar`, `/serverinfo`, `/userinfo`, `/ownerpanel`

---

## 2. Prefix Command Architecture (415 Commands)

* **Prefix:** `,` (Configured in `.env` as `DEFAULT_PREFIX=,`)
* **Total Root Prefix Commands:** 415
* **Prefix Command Groups:** 8
* **Total Registered Aliases:** 152
* **Alias Collisions:** **0** (All collisions verified resolved in `test_command_restructuring.py`)
