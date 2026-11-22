# KROVEX — Complete Command & Feature Inventory

**Inspection Date:** 2026-11-17  
**Branch:** `qa/krovex-complete-audit`  
**Total Commands:** 403 Slash Operations (43 Root: 20 Groups + 23 Standalone) | 415 Prefix Commands  
**Total Cogs:** 21 Modules | **Total Services:** 10 Services

---

## Command Matrix by Subsystem

| Module | Exact Command | Primary File | Type | Required Permissions | Database Operations | Test Status |
|---|---|---|---|---|---|---|
| **Admin** | `/admin prefix`, `,prefix` | `bot/cogs/admin/cog.py` | Slash Sub / Prefix | Administrator | `guild_settings` | PASSED |
| **Admin** | `/admin channelcreate` | `bot/cogs/admin/cog.py` | Slash Sub | Manage Channels | None | PASSED |
| **Admin** | `/admin channeldelete` | `bot/cogs/admin/cog.py` | Slash Sub | Manage Channels | None | PASSED |
| **Admin** | `/admin channelrename` | `bot/cogs/admin/cog.py` | Slash Sub | Manage Channels | None | PASSED |
| **Admin** | `/setup server` | `bot/cogs/admin/setup_wizard.py` | Slash Sub | Administrator | `dashboard_panels` | PASSED |
| **Admin** | `/ownerpanel`, `,ownerpanel` | `bot/cogs/admin/owner_panel.py` | Slash / Prefix | Server / Bot Owner | `vc_staff_roles` | PASSED |
| **AutoMod** | `/automod status` | `bot/cogs/automod/cog.py` | Slash Sub | Manage Guild | `automod_settings` | PASSED |
| **AutoMod** | `/automod filterbadwords` | `bot/cogs/automod/cog.py` | Slash Sub | Manage Guild | `automod_rules` | PASSED |
| **AutoMod** | `/automod filterinvites` | `bot/cogs/automod/cog.py` | Slash Sub | Manage Guild | `automod_rules` | PASSED |
| **AutoMod** | `/automod filterlinks` | `bot/cogs/automod/cog.py` | Slash Sub | Manage Guild | `automod_rules` | PASSED |
| **Economy** | `/eco balance`, `,bal` | `bot/cogs/economy/cog.py` | Slash Sub / Prefix | None | `user_profiles` | PASSED |
| **Economy** | `/eco deposit`, `,dep` | `bot/cogs/economy/cog.py` | Slash Sub / Prefix | None | `user_profiles`, `economy_transactions` | PASSED |
| **Economy** | `/eco withdraw`, `,with` | `bot/cogs/economy/cog.py` | Slash Sub / Prefix | None | `user_profiles`, `economy_transactions` | PASSED |
| **Economy** | `/eco daily`, `,daily` | `bot/cogs/economy/cog.py` | Slash Sub / Prefix | None | `user_profiles`, `economy_transactions` | PASSED |
| **Economy** | `/eco work`, `,work` | `bot/cogs/economy/cog.py` | Slash Sub / Prefix | None | `user_profiles`, `economy_transactions` | PASSED |
| **Fun** | `/rate simp`, `,simprate` | `bot/cogs/fun/ratings.py` | Slash Sub / Prefix | None | None | PASSED |
| **Fun** | `/rate cute`, `,cuterate` | `bot/cogs/fun/ratings.py` | Slash Sub / Prefix | None | None | PASSED |
| **Fun** | `,8ball`, `,roll`, `,roast` | `bot/cogs/fun/cog.py` | Prefix | None | None | PASSED |
| **Leveling** | `/level rank`, `,rank` | `bot/cogs/leveling/cog.py` | Slash Sub / Prefix | None | `member_levels` | PASSED |
| **Leveling** | `/level leaderboard`, `,lb` | `bot/cogs/leveling/cog.py` | Slash Sub / Prefix | None | `member_levels` | PASSED |
| **Leveling** | `/level setup` | `bot/cogs/leveling/cog.py` | Slash Sub | Manage Guild | `leveling_settings` | PASSED |
| **Logging** | `/logs channel`, `,setlog` | `bot/cogs/logging/cog.py` | Slash Sub / Prefix | Manage Guild | `logging_settings` | PASSED |
| **Logging** | `/logs status`, `,logstatus` | `bot/cogs/logging/cog.py` | Slash Sub / Prefix | Manage Guild | `logging_settings`, `logging_event_toggles` | PASSED |
| **Minigames** | `/game tictactoe` | `bot/cogs/minigames/cog.py` | Slash Sub | None | `minigame_stats` | PASSED |
| **Minigames** | `/game connectfour` | `bot/cogs/minigames/cog.py` | Slash Sub | None | `minigame_stats` | PASSED |
| **Minigames** | `/game blackjack` | `bot/cogs/minigames/cog.py` | Slash Sub | None | `user_profiles`, `minigame_stats` | PASSED |
| **Moderation** | `/ban`, `,ban` | `bot/cogs/moderation/cog.py` | Slash / Prefix | Ban Members | `moderation_logs` | PASSED |
| **Moderation** | `/kick`, `,kick` | `bot/cogs/moderation/cog.py` | Slash / Prefix | Kick Members | `moderation_logs` | PASSED |
| **Moderation** | `/timeout`, `,timeout` | `bot/cogs/moderation/cog.py` | Slash / Prefix | Moderate Members | `moderation_logs` | PASSED |
| **Moderation** | `/purge`, `,purge` | `bot/cogs/moderation/cog.py` | Slash / Prefix | Manage Messages | `moderation_logs` | PASSED |
| **Moderation** | `/warn`, `,warn` | `bot/cogs/moderation/cog.py` | Slash / Prefix | Moderate Members | `warnings` | PASSED |
| **Music** | `/play`, `,play` | `bot/cogs/music/cog.py` | Slash / Prefix | Connect, Speak | None | PASSED |
| **Music** | `/pause`, `,pause` | `bot/cogs/music/cog.py` | Slash / Prefix | None | None | PASSED |
| **Music** | `/skip`, `,skip` | `bot/cogs/music/cog.py` | Slash / Prefix | None | None | PASSED |
| **Music** | `/queue`, `,queue` | `bot/cogs/music/cog.py` | Slash / Prefix | None | None | PASSED |
| **OwnerVC** | `.vcpanel`, `/ownerpanel` | `bot/cogs/ownervc/dashboard.py`| UI Component | Server / Bot Owner | `vc_bans`, `vc_staff_roles` | PASSED |
| **OwnerVC** | `/vc kick`, `,vckick` | `bot/cogs/ownervc/cog.py` | Slash Sub / Prefix | Move Members | `moderation_logs` | PASSED |
| **OwnerVC** | `/vc ban`, `,vcban` | `bot/cogs/ownervc/cog.py` | Slash Sub / Prefix | Manage Channels | `vc_bans` | PASSED |
| **OwnerVC** | `/vc muteall`, `,vcmuteall` | `bot/cogs/ownervc/cog.py` | Slash Sub / Prefix | Mute Members | None | PASSED |
| **ReactionRoles** | `/rr create` | `bot/cogs/reactionroles/cog.py`| Slash Sub | Manage Roles | `reaction_roles`, `reaction_role_panels` | PASSED |
| **Security** | `/security status` | `bot/cogs/security/cog.py` | Slash Sub | Administrator | `security_settings` | PASSED |
| **Security** | `/security antinuke` | `bot/cogs/security/cog.py` | Slash Sub | Server Owner | `security_settings` | PASSED |
| **Shop** | `/shop view`, `,shop` | `bot/cogs/shop/cog.py` | Slash Sub / Prefix | None | `shop_items`, `shop_categories` | PASSED |
| **Shop** | `/shop buy`, `,buy` | `bot/cogs/shop/cog.py` | Slash Sub / Prefix | None | `shop_items`, `user_inventory`, `user_profiles` | PASSED |
| **Social** | `/interact ship`, `,ship` | `bot/cogs/social/cog.py` | Slash Sub / Prefix | None | None | PASSED |
| **SOUL** | `/soul status` | `bot/cogs/soul/cog.py` | Slash Sub | None | `soul_guild_settings`, `soul_sessions` | PASSED |
| **Tickets** | `/ticket setup` | `bot/cogs/tickets/cog.py` | Slash Sub | Administrator | `ticket_settings` | PASSED |
| **Tickets** | `/ticket create` | `bot/cogs/tickets/cog.py` | Slash Sub | None | `tickets`, `ticket_participants` | PASSED |
| **Utility** | `/help`, `,help` | `bot/cogs/utility/help.py` | Slash / Prefix | None | None | PASSED |
| **Utility** | `/ping`, `,ping` | `bot/cogs/utility/cog.py` | Slash / Prefix | None | None | PASSED |
| **Vault** | `,vault drill` | `bot/cogs/vault/cog.py` | Prefix | Bot Owner | In-memory archive / DR channels | PASSED |
| **Welcome** | `/welcome setup` | `bot/cogs/welcome/cog.py` | Slash Sub | Manage Guild | `welcome_settings` | PASSED |
