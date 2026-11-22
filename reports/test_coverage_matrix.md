# KROVEX — Master Test Coverage Matrix

| Subsystem / Phase | Target Test Suites | Total Tests | Current Status | Coverage Focus |
|---|---|---|---|---|
| **Phase 1: Core System & Startup** | `test_gateway_and_lifecycle.py`, `test_config.py`, `test_database.py`, `test_sqlite_architecture.py`, `test_bot_integrity.py` | 29 | **READY** | Lifecycle, gateway reconnects, DB connection pool, config loading |
| **Phase 2: Security & Anti-Nuke** | `test_security_cog.py`, `test_automod_cog.py`, `test_services.py` | 18 | QUEUED | Anti-nuke limits, webhook abuse, spam buckets, audit-log delay |
| **Phase 3: Moderation** | `test_moderation_cog.py`, `test_advanced_logging.py` | 10 | QUEUED | Ban, kick, timeout, purge, warn history, hierarchy enforcement |
| **Phase 4: Fun & Minigames** | `test_minigames_cog.py`, `test_ratings_fun.py`, `test_anime_social.py` | 24 | QUEUED | TicTacToe, ConnectFour, Blackjack, Coinflip, ratings, session timeout |
| **Phase 5: Economy & Leveling** | `test_economy_cog.py`, `test_economy_concurrency.py`, `test_leveling_cog.py`, `test_shop_cog.py`, `test_shop_buy_authorization.py`, `test_shop_refunds.py` | 23 | QUEUED | Balance, transactions, streaks, XP leveling, shop purchases, refunds |
| **Phase 6: Voice & OwnerVC** | `test_ownervc_three_dropdowns.py`, `test_vc_staff_panel.py`, `test_vc_automation.py`, `test_vc_control_authorization.py`, `test_ownervc_cog.py` | 37 | QUEUED | 3-dropdown OwnerVC, VC Loop, voice bans, temp channels, staff roles |
| **Phase 7: Music, Social & Community** | `test_music_engine.py`, `test_music_queue_reliability.py`, `test_spotify_api_verification.py`, `test_tickets_cog.py`, `test_ticket_close_authorization.py`, `test_ticket_rating_authorization.py`, `test_welcome_expansion.py`, `test_goodbye_setup_error.py`, `test_soul_foundation.py`, `test_soul_discord_integration.py` | 158 | QUEUED | Player lifecycle, Spotify resolution, tickets, welcome cards, SOUL AI |
| **Phase 8: Owner & Administration** | `test_server_admin_cog.py`, `test_vault_cog.py`, `test_setup_wizard.py`, `test_setup_wizard_repair.py`, `test_krovex_auto_roles.py` | 18 | QUEUED | Owner panel, Disaster Recovery vault, setup wizard, bot role hoisting |
| **Phase 9: Interaction & UX** | `test_premium_help_ux.py`, `test_unified_context_reply.py`, `test_application_emojis.py`, `test_krovex_logging_redesign.py`, `test_dm_queue.py` | 66 | QUEUED | Help pagination, buttons, modals, embeds, DM delivery queues |
| **Phase 10: Regression & Tree** | `test_command_restructuring.py`, `test_slash_command_renames.py`, `test_slash_ux_renaming.py`, `test_custom_command_foundation.py`, `test_mimic.py`, `test_mention_service.py` | 68 | QUEUED | Root command tree headroom (43/100), alias resolution, custom commands |
