"""SQLite database manager, schema migrations, and backup engine for Death Bot."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Dict, List, Optional
import aiosqlite

from bot.utils.logger import get_logger

logger = get_logger("death_bot.database.sqlite")

DB_DIR = Path(__file__).resolve().parent.parent.parent / "db"
_env_db_path = os.getenv("DATABASE_PATH")
DEFAULT_DB_PATH = Path(_env_db_path).resolve() if _env_db_path else (DB_DIR / "death_bot.sqlite")
BACKUPS_DIR = DB_DIR / "backups"


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Guild Settings
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    prefix TEXT NOT NULL DEFAULT '!',
    language TEXT NOT NULL DEFAULT 'en',
    embed_color INTEGER NOT NULL DEFAULT 10309341,
    disabled_channels TEXT NOT NULL DEFAULT '[]',
    disabled_commands TEXT NOT NULL DEFAULT '[]',
    mod_roles TEXT NOT NULL DEFAULT '[]',
    admin_roles TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- User Profiles
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0,
    bank INTEGER NOT NULL DEFAULT 0,
    daily_streak INTEGER NOT NULL DEFAULT 0,
    last_daily TIMESTAMP,
    reputation INTEGER NOT NULL DEFAULT 0,
    bio TEXT NOT NULL DEFAULT '',
    badges TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Guild Member Levels (MEE6 / ProBot style)
CREATE TABLE IF NOT EXISTS member_levels (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    xp INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 0,
    messages_count INTEGER NOT NULL DEFAULT 0,
    last_xp_at TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

-- Level Rewards / Roles
CREATE TABLE IF NOT EXISTS level_rewards (
    guild_id INTEGER NOT NULL,
    level INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, level)
);

-- Moderation Cases
CREATE TABLE IF NOT EXISTS moderation_logs (
    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT 'No reason provided',
    duration_seconds INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active BOOLEAN NOT NULL DEFAULT 1
);

-- Warnings
CREATE TABLE IF NOT EXISTS warnings (
    warn_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Music Guild Settings
CREATE TABLE IF NOT EXISTS music_settings (
    guild_id INTEGER PRIMARY KEY,
    default_volume INTEGER NOT NULL DEFAULT 100,
    max_queue_size INTEGER NOT NULL DEFAULT 500,
    loop_mode TEXT NOT NULL DEFAULT 'off',
    twenty_four_seven BOOLEAN NOT NULL DEFAULT 0,
    dj_role_id INTEGER,
    vote_skip_ratio REAL NOT NULL DEFAULT 0.5
);

-- Playlists
CREATE TABLE IF NOT EXISTS playlists (
    playlist_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    tracks TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, user_id, name)
);

-- Voice Tracking
CREATE TABLE IF NOT EXISTS voice_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    status_channel_id INTEGER,
    log_channel_id INTEGER,
    leaderboard_channel_id INTEGER,
    auto_refresh_seconds INTEGER NOT NULL DEFAULT 60,
    tracked_channels TEXT NOT NULL DEFAULT '[]',
    ignored_channels TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS voice_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    joined_at TIMESTAMP NOT NULL,
    left_at TIMESTAMP,
    duration_seconds INTEGER NOT NULL DEFAULT 0
);

-- Voice Channel Staff Roles
CREATE TABLE IF NOT EXISTS vc_staff_roles (
    guild_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    added_by INTEGER NOT NULL,
    added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, role_id)
);

-- Voice Channel Staff Settings
CREATE TABLE IF NOT EXISTS vc_staff_settings (
    guild_id INTEGER PRIMARY KEY,
    allow_bulk_actions BOOLEAN NOT NULL DEFAULT 0,
    updated_by INTEGER,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Welcome & Goodbye System
CREATE TABLE IF NOT EXISTS welcome_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT 0,
    channel_id INTEGER,
    message_template TEXT NOT NULL DEFAULT 'Welcome {user} to {server}!',
    use_embed BOOLEAN NOT NULL DEFAULT 1,
    embed_color INTEGER NOT NULL DEFAULT 10309341,
    auto_roles TEXT NOT NULL DEFAULT '[]',
    send_dm BOOLEAN NOT NULL DEFAULT 0,
    dm_template TEXT NOT NULL DEFAULT 'Welcome to {server}!',
    goodbye_enabled BOOLEAN NOT NULL DEFAULT 0,
    goodbye_channel_id INTEGER,
    goodbye_template TEXT NOT NULL DEFAULT '{user} left the server.',
    goodbye_use_embed BOOLEAN NOT NULL DEFAULT 1
);

-- Invite Tracker Subsystem
CREATE TABLE IF NOT EXISTS invite_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    log_channel_id INTEGER,
    fake_threshold_hours INTEGER NOT NULL DEFAULT 24,
    join_message TEXT NOT NULL DEFAULT '{user} joined using invite code {code} by {inviter} ({total} invites)!',
    leave_message TEXT NOT NULL DEFAULT '{user} left (invited by {inviter}).'
);

CREATE TABLE IF NOT EXISTS invite_counts (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    regular INTEGER NOT NULL DEFAULT 0,
    bonus INTEGER NOT NULL DEFAULT 0,
    fake INTEGER NOT NULL DEFAULT 0,
    leaves INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS invite_cached (
    guild_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    inviter_id INTEGER,
    uses INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP,
    PRIMARY KEY (guild_id, code)
);

CREATE TABLE IF NOT EXISTS invite_rewards (
    guild_id INTEGER NOT NULL,
    target_invites INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, target_invites)
);

CREATE TABLE IF NOT EXISTS invite_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    inviter_id INTEGER,
    code TEXT,
    is_fake BOOLEAN NOT NULL DEFAULT 0,
    joined_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    left_at TIMESTAMP
);

-- Security & Anti-Nuke Subsystem
CREATE TABLE IF NOT EXISTS security_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    anti_nuke BOOLEAN NOT NULL DEFAULT 1,
    anti_raid BOOLEAN NOT NULL DEFAULT 1,
    anti_spam BOOLEAN NOT NULL DEFAULT 1,
    anti_phishing BOOLEAN NOT NULL DEFAULT 1,
    anti_bot BOOLEAN NOT NULL DEFAULT 1,
    anti_webhook BOOLEAN NOT NULL DEFAULT 1,
    anti_mention_spam BOOLEAN NOT NULL DEFAULT 1,
    account_age_threshold_hours INTEGER NOT NULL DEFAULT 24,
    join_rate_max INTEGER NOT NULL DEFAULT 5,
    join_rate_seconds INTEGER NOT NULL DEFAULT 10,
    mass_ban_threshold INTEGER NOT NULL DEFAULT 3,
    mass_kick_threshold INTEGER NOT NULL DEFAULT 3,
    channel_del_threshold INTEGER NOT NULL DEFAULT 3,
    role_del_threshold INTEGER NOT NULL DEFAULT 3,
    time_window_seconds INTEGER NOT NULL DEFAULT 15,
    punishment TEXT NOT NULL DEFAULT 'none',
    log_channel_id INTEGER,
    whitelist_users TEXT NOT NULL DEFAULT '[]',
    whitelist_roles TEXT NOT NULL DEFAULT '[]',
    event_punishments TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS security_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    actor_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    details TEXT NOT NULL,
    action_taken TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Advanced Automod Subsystem
CREATE TABLE IF NOT EXISTS automod_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    bad_words_enabled BOOLEAN NOT NULL DEFAULT 1,
    bad_words_list TEXT NOT NULL DEFAULT '[]',
    invites_blocked BOOLEAN NOT NULL DEFAULT 1,
    links_blocked BOOLEAN NOT NULL DEFAULT 0,
    caps_enabled BOOLEAN NOT NULL DEFAULT 1,
    caps_min_chars INTEGER NOT NULL DEFAULT 10,
    caps_percentage INTEGER NOT NULL DEFAULT 70,
    emojis_enabled BOOLEAN NOT NULL DEFAULT 1,
    emoji_limit INTEGER NOT NULL DEFAULT 8,
    mention_limit INTEGER NOT NULL DEFAULT 5,
    repeat_enabled BOOLEAN NOT NULL DEFAULT 1,
    repeat_threshold INTEGER NOT NULL DEFAULT 3,
    flood_interval_seconds REAL NOT NULL DEFAULT 1.0,
    log_channel_id INTEGER,
    exempt_roles TEXT NOT NULL DEFAULT '[]',
    exempt_channels TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS automod_rules (
    rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    rule_type TEXT NOT NULL, -- regex, word, domain
    pattern TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'delete', -- delete, warn, timeout
    duration_seconds INTEGER DEFAULT 300,
    enabled BOOLEAN NOT NULL DEFAULT 1
);

-- Reaction Roles / Button Roles
CREATE TABLE IF NOT EXISTS reaction_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    emoji TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    UNIQUE(message_id, emoji)
);

-- Custom Tags & Commands (Carl-bot / YAGPDB style)
CREATE TABLE IF NOT EXISTS custom_tags (
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    creator_id INTEGER NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, name)
);

-- Ticket Tool System
CREATE TABLE IF NOT EXISTS ticket_settings (
    guild_id INTEGER PRIMARY KEY,
    category_id INTEGER,
    staff_role_id INTEGER,
    transcript_channel_id INTEGER,
    ticket_counter INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    creator_id INTEGER NOT NULL,
    claimed_by INTEGER,
    status TEXT NOT NULL DEFAULT 'open', -- open, closed, claimed
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP
);

-- Audit / Logging Settings
CREATE TABLE IF NOT EXISTS logging_settings (
    guild_id INTEGER PRIMARY KEY,
    mod_log_channel INTEGER,
    message_log_channel INTEGER,
    member_log_channel INTEGER,
    server_log_channel INTEGER,
    voice_log_channel INTEGER,
    status_log_channel INTEGER,
    invite_log_channel INTEGER,
    logging_enabled BOOLEAN NOT NULL DEFAULT 1
);

-- Mimic: Per-Server Bot Identity Profiles
CREATE TABLE IF NOT EXISTS guild_mimic_profiles (
    guild_id INTEGER PRIMARY KEY,
    nickname TEXT,
    avatar_url TEXT,
    original_name TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Reminders & Timers
CREATE TABLE IF NOT EXISTS reminders (
    reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    remind_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Giveaways
CREATE TABLE IF NOT EXISTS giveaways (
    giveaway_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    prize TEXT NOT NULL,
    winners_count INTEGER NOT NULL DEFAULT 1,
    ends_at TIMESTAMP NOT NULL,
    host_id INTEGER NOT NULL,
    ended BOOLEAN NOT NULL DEFAULT 0
);

-- Economy Items & Inventory
CREATE TABLE IF NOT EXISTS economy_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    role_reward_id INTEGER,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS user_inventory (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(guild_id, user_id, item_id)
);

-- Command Usage Statistics
CREATE TABLE IF NOT EXISTS command_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER NOT NULL,
    command_name TEXT NOT NULL,
    invoked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_slash BOOLEAN NOT NULL DEFAULT 0,
    success BOOLEAN NOT NULL DEFAULT 1
);

-- VC Bans (voice channel permission-based bans)
CREATE TABLE IF NOT EXISTS vc_bans (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    banned_by INTEGER NOT NULL,
    reason TEXT NOT NULL DEFAULT 'No reason provided',
    banned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, user_id)
);

-- VC Ownership (temp channel owners)
CREATE TABLE IF NOT EXISTS vc_ownership (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

-- VC Temp Channels
CREATE TABLE IF NOT EXISTS vc_temp_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

-- VC Loop Configurations (Individual member VC loop automation)
CREATE TABLE IF NOT EXISTS vc_loops (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    activated_by INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

-- VC Loop Opt-Outs (Member privacy & anti-harassment protection)
CREATE TABLE IF NOT EXISTS vc_loop_optouts (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    opted_out_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

-- Trusted Users (security whitelist by user)
CREATE TABLE IF NOT EXISTS trusted_users (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    added_by INTEGER NOT NULL,
    added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

-- Security Incidents
CREATE TABLE IF NOT EXISTS security_incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    actor_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    punishment TEXT NOT NULL DEFAULT 'none',
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- AutoMod Violations
CREATE TABLE IF NOT EXISTS automod_violations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    rule_type TEXT NOT NULL,
    matched_content TEXT NOT NULL DEFAULT '',
    action_taken TEXT NOT NULL DEFAULT 'delete',
    channel_id INTEGER,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Flood Tracking (in-memory supported by DB for persistence across restarts)
CREATE TABLE IF NOT EXISTS flood_tracking (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    window_start TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

-- Dashboard Panels (VC + Security control panels)
CREATE TABLE IF NOT EXISTS dashboard_panels (
    guild_id INTEGER NOT NULL,
    panel_type TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, panel_type)
);

-- Reaction Role Panels
CREATE TABLE IF NOT EXISTS reaction_role_panels (
    message_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    panel_type TEXT NOT NULL DEFAULT 'button',
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    max_roles INTEGER NOT NULL DEFAULT 0,
    exclusive BOOLEAN NOT NULL DEFAULT 0,
    required_role_id INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Reaction Role Items (buttons, select options, emojis)
CREATE TABLE IF NOT EXISTS reaction_role_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    emoji TEXT,
    label TEXT,
    description TEXT,
    style TEXT NOT NULL DEFAULT 'primary',
    UNIQUE(message_id, role_id)
);

-- Server Rules
CREATE TABLE IF NOT EXISTS server_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    rule_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, rule_index)
);

-- Audit Event Logs
CREATE TABLE IF NOT EXISTS audit_event_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    actor_id INTEGER,
    target_id INTEGER,
    details TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Logging Event Toggles
CREATE TABLE IF NOT EXISTS logging_event_toggles (
    guild_id INTEGER NOT NULL,
    event_name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    PRIMARY KEY (guild_id, event_name)
);

-- Logging Filters (ignored channels/roles/keywords)
CREATE TABLE IF NOT EXISTS logging_filters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    filter_type TEXT NOT NULL,
    target TEXT NOT NULL
);

-- Welcome Card Customization
CREATE TABLE IF NOT EXISTS welcome_card_settings (
    guild_id INTEGER PRIMARY KEY,
    image_url TEXT,
    card_theme TEXT NOT NULL DEFAULT 'neon_purple',
    welcome_count INTEGER NOT NULL DEFAULT 0
);

-- ========================================================
-- BATCH 03 TABLES: TICKETS, LEVELING, ECONOMY, SHOP, MINIGAMES
-- ========================================================

-- Advanced Ticket System
CREATE TABLE IF NOT EXISTS ticket_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '🎫',
    description TEXT NOT NULL DEFAULT '',
    category_channel_id INTEGER,
    staff_role_id INTEGER,
    naming_scheme TEXT NOT NULL DEFAULT 'ticket-{number}',
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS ticket_participants (
    ticket_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    added_by INTEGER NOT NULL,
    added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticket_id, user_id)
);

CREATE TABLE IF NOT EXISTS ticket_blacklists (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    reason TEXT NOT NULL DEFAULT 'No reason provided',
    blacklisted_by INTEGER NOT NULL,
    blacklisted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

-- Leveling & XP Configuration
CREATE TABLE IF NOT EXISTS leveling_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    channel_id INTEGER,
    message_template TEXT NOT NULL DEFAULT '🎉 Congratulations {user}, you leveled up to **Level {level}**!',
    min_xp INTEGER NOT NULL DEFAULT 15,
    max_xp INTEGER NOT NULL DEFAULT 25,
    cooldown_seconds INTEGER NOT NULL DEFAULT 60,
    multiplier REAL NOT NULL DEFAULT 1.0,
    stack_roles BOOLEAN NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS level_exemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    target_type TEXT NOT NULL, -- 'channel' or 'role'
    UNIQUE(guild_id, target_id, target_type)
);

-- Server-Specific Economy
CREATE TABLE IF NOT EXISTS economy_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    currency_name TEXT NOT NULL DEFAULT 'Coins',
    currency_symbol TEXT NOT NULL DEFAULT '🪙',
    daily_min INTEGER NOT NULL DEFAULT 100,
    daily_max INTEGER NOT NULL DEFAULT 300,
    weekly_min INTEGER NOT NULL DEFAULT 1000,
    weekly_max INTEGER NOT NULL DEFAULT 2500,
    work_min INTEGER NOT NULL DEFAULT 50,
    work_max INTEGER NOT NULL DEFAULT 200,
    crime_min INTEGER NOT NULL DEFAULT 200,
    crime_max INTEGER NOT NULL DEFAULT 800,
    rob_rate REAL NOT NULL DEFAULT 0.5,
    bank_cap INTEGER NOT NULL DEFAULT 50000
);

CREATE TABLE IF NOT EXISTS server_economy (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    wallet INTEGER NOT NULL DEFAULT 0,
    bank INTEGER NOT NULL DEFAULT 0,
    daily_streak INTEGER NOT NULL DEFAULT 0,
    last_daily TIMESTAMP,
    last_weekly TIMESTAMP,
    last_work TIMESTAMP,
    last_crime TIMESTAMP,
    last_rob TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS economy_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    target_id INTEGER,
    action TEXT NOT NULL,
    amount INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'system',
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Server Shop
CREATE TABLE IF NOT EXISTS shop_categories (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS shop_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL,
    role_id INTEGER,
    stock INTEGER NOT NULL DEFAULT -1, -- -1 for unlimited
    category_id INTEGER,
    max_per_user INTEGER NOT NULL DEFAULT 1,
    is_buyable BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS shop_purchases (
    purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    price_paid INTEGER NOT NULL,
    purchased_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'completed'
);

-- Interactive Minigames
CREATE TABLE IF NOT EXISTS minigame_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    min_bet INTEGER NOT NULL DEFAULT 10,
    max_bet INTEGER NOT NULL DEFAULT 5000,
    cooldown_seconds INTEGER NOT NULL DEFAULT 15,
    reward_multiplier REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS minigame_stats (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    game_type TEXT NOT NULL,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    coins_won INTEGER NOT NULL DEFAULT 0,
    coins_lost INTEGER NOT NULL DEFAULT 0,
    high_score INTEGER NOT NULL DEFAULT 0,
    last_played TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, game_type)
);

CREATE TABLE IF NOT EXISTS minigame_daily_challenges (
    guild_id INTEGER NOT NULL,
    day_date TEXT NOT NULL,
    challenge_type TEXT NOT NULL,
    target_count INTEGER NOT NULL DEFAULT 3,
    reward_coins INTEGER NOT NULL DEFAULT 500,
    PRIMARY KEY (guild_id, day_date, challenge_type)
);

-- Real-Time Mention Notification Settings
CREATE TABLE IF NOT EXISTS user_mention_settings (
    user_id INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Centralized Outgoing DM Queue (Phase 2A)
CREATE TABLE IF NOT EXISTS dm_queue (
    job_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    recipient_id INTEGER NOT NULL,
    guild_id INTEGER,
    message_type TEXT NOT NULL DEFAULT 'notification',
    content TEXT,
    embed_data TEXT,
    metadata TEXT,
    state TEXT NOT NULL DEFAULT 'pending', -- pending, processing, sent, failed
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    backoff_until REAL NOT NULL DEFAULT 0.0,
    error_message TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dm_queue_state_created ON dm_queue(state, created_at);

-- Rolling-window Persistent Rate Limit Audit Log (Max 2 sends per 60s window)
CREATE TABLE IF NOT EXISTS dm_rate_limit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    recipient_id INTEGER NOT NULL,
    guild_id INTEGER,
    sent_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dm_rate_limit_sent_at ON dm_rate_limit_log(sent_at);

-- Custom Commands (Stage 1)
CREATE TABLE IF NOT EXISTS custom_commands (
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    response_type TEXT NOT NULL DEFAULT 'text',
    content TEXT,
    embed_data TEXT,
    permission_level TEXT NOT NULL DEFAULT 'everyone',
    required_role_ids TEXT NOT NULL DEFAULT '[]',
    cooldown_seconds INTEGER NOT NULL DEFAULT 0,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    creator_id INTEGER NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, name)
);
CREATE INDEX IF NOT EXISTS idx_custom_commands_guild ON custom_commands(guild_id);
CREATE INDEX IF NOT EXISTS idx_custom_commands_enabled ON custom_commands(guild_id, is_enabled);

-- Custom Command Aliases (Stage 1)
CREATE TABLE IF NOT EXISTS custom_command_aliases (
    guild_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    target_command TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, alias),
    FOREIGN KEY (guild_id, target_command) REFERENCES custom_commands(guild_id, name) ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_custom_command_aliases_lookup ON custom_command_aliases(guild_id, alias);
CREATE INDEX IF NOT EXISTS idx_custom_command_aliases_target ON custom_command_aliases(guild_id, target_command);

-- KROVEX SOUL: AI Conversation Memory & Ephemeral Sessions (Phase 2)
CREATE TABLE IF NOT EXISTS soul_sessions (
    session_id TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    last_activity_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_soul_sessions_lookup ON soul_sessions(guild_id, channel_id, user_id);
CREATE INDEX IF NOT EXISTS idx_soul_sessions_activity ON soul_sessions(last_activity_at);

CREATE TABLE IF NOT EXISTS soul_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'model', 'system')),
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES soul_sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_soul_messages_session ON soul_messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS soul_guild_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    allowed_channels TEXT,
    personality_style TEXT NOT NULL DEFAULT 'tanglish_bro',
    cooldown_seconds REAL NOT NULL DEFAULT 3.0,
    max_history_turns INTEGER NOT NULL DEFAULT 10,
    daily_quota_limit INTEGER NOT NULL DEFAULT 500,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ========================================================
-- KROVEX ULTIMATE VOICE CONTROL CENTRE
-- ========================================================
CREATE TABLE IF NOT EXISTS vc_action_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    executor_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    scope TEXT NOT NULL,
    source_channel_id INTEGER,
    destination_channel_id INTEGER,
    target_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    details TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_vc_action_logs_guild ON vc_action_logs(guild_id, created_at);

CREATE TABLE IF NOT EXISTS vc_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    preset_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    created_by INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, preset_name)
);
CREATE INDEX IF NOT EXISTS idx_vc_presets_guild ON vc_presets(guild_id);

CREATE TABLE IF NOT EXISTS vc_temporary_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    revert_data TEXT NOT NULL DEFAULT '{}',
    expires_at REAL NOT NULL,
    created_by INTEGER NOT NULL,
    created_at REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_vc_temp_actions_active ON vc_temporary_actions(active, expires_at);

CREATE TABLE IF NOT EXISTS vc_channel_permission_backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    backup_type TEXT NOT NULL,
    overwrites_json TEXT NOT NULL,
    saved_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_vc_perm_backups ON vc_channel_permission_backups(guild_id, channel_id, backup_type);

CREATE TABLE IF NOT EXISTS vc_control_settings (
    guild_id INTEGER PRIMARY KEY,
    afk_channel_id INTEGER,
    afk_timeout_seconds INTEGER NOT NULL DEFAULT 300,
    meeting_exempt_roles TEXT NOT NULL DEFAULT '[]',
    announcement_speakers TEXT NOT NULL DEFAULT '[]',
    staff_roles TEXT NOT NULL DEFAULT '[]',
    updated_by INTEGER,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class SQLiteDatabaseManager:
    """Manages the primary SQLite connection, schema migrations, and 30-min automated backups."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self.backups_dir = BACKUPS_DIR
        self.is_connected: bool = False
        self._connection: Optional[aiosqlite.Connection] = None
        self._backup_task: Optional[asyncio.Task] = None
        self.on_backup_created: Optional[Any] = None

    async def connect(self) -> None:
        """Connect to SQLite database and run migration schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Connecting to primary SQLite database at %s...", self.db_path)
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row

        # Execute base schema and migrations
        await self._connection.executescript(SCHEMA_SQL)
        
        # Batch 03 dynamic column migrations for existing tables
        alter_stmts = [
            ("ticket_settings", "max_tickets_per_user", "INTEGER NOT NULL DEFAULT 1"),
            ("ticket_settings", "cooldown_seconds", "INTEGER NOT NULL DEFAULT 30"),
            ("ticket_settings", "naming_scheme", "TEXT NOT NULL DEFAULT 'ticket-{number}'"),
            ("ticket_settings", "closed_category_id", "INTEGER"),
            ("ticket_settings", "logs_channel_id", "INTEGER"),
            ("tickets", "category_id", "INTEGER"),
            ("tickets", "ticket_number", "INTEGER NOT NULL DEFAULT 1"),
            ("tickets", "close_reason", "TEXT"),
            ("tickets", "rating", "INTEGER"),
            ("tickets", "rating_feedback", "TEXT"),
            ("tickets", "closed_by", "INTEGER"),
            ("logging_settings", "status_log_channel", "INTEGER"),
            ("logging_settings", "invite_log_channel", "INTEGER"),
            ("logging_settings", "logging_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
            ("dm_queue", "metadata", "TEXT"),
            ("security_settings", "event_punishments", "TEXT NOT NULL DEFAULT '{}'"),
        ]
        for tbl, col, col_def in alter_stmts:
            try:
                await self._connection.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def};")
            except Exception:
                pass  # column already exists
        await self._connection.commit()

        self.is_connected = True
        logger.info("SQLite database connected and schema initialized successfully.")

        # Start background backup schedule (every 30 minutes)
        if not self._backup_task:
            self._backup_task = asyncio.create_task(self._backup_loop())

    async def close(self) -> None:
        """Close SQLite connection and cancel backup scheduler."""
        if self._backup_task:
            self._backup_task.cancel()
            self._backup_task = None

        if self._connection:
            await self._connection.close()
            self._connection = None
            self.is_connected = False
            logger.info("SQLite connection closed.")

    async def disconnect(self) -> None:
        """Alias for close() to maintain interface consistency."""
        await self.close()

    @property
    def connection(self) -> aiosqlite.Connection:
        if not self._connection or not self.is_connected:
            raise RuntimeError("SQLite database is not connected.")
        return self._connection

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        """Execute a single query with parameters."""
        cursor = await self.connection.execute(sql, params)
        await self.connection.commit()
        return cursor

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Fetch a single row as a dictionary."""
        async with self.connection.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    async def fetchall(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Fetch all rows as dictionaries."""
        async with self.connection.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def create_backup(self, custom_name: Optional[str] = None) -> Path:
        """Create a full verified backup snapshot of the SQLite database."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_filename = f"death_bot_{timestamp}.sqlite" if not custom_name else custom_name
        target_path = self.backups_dir / backup_filename

        # Use SQLite online backup API to ensure ACID snapshot integrity
        def _sync_backup():
            source = sqlite3.connect(self.db_path)
            dest = sqlite3.connect(target_path)
            with dest:
                source.backup(dest)
            dest.close()
            source.close()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _sync_backup)
        logger.info("Database backup created successfully: %s", target_path)
        return target_path

    async def _backup_loop(self) -> None:
        """Runs backup every 30 minutes and retains the last 20 snapshots."""
        while True:
            try:
                await asyncio.sleep(1800)  # 30 minutes
                backup_path = await self.create_backup()
                await self._prune_backups(keep=20)
                if self.on_backup_created:
                    try:
                        await self.on_backup_created(backup_path, "automatic")
                    except Exception as hook_err:
                        logger.error("Error executing on_backup_created hook: %s", hook_err)
            except asyncio.CancelledError:
                break
            except Exception as err:
                logger.error("Error running automated 30-min backup: %s", err)

    async def _prune_backups(self, keep: int = 20) -> None:
        """Prune old backup snapshots, retaining the newest `keep` backups."""
        backups = sorted(self.backups_dir.glob("*.sqlite"), key=os.path.getmtime)
        if len(backups) > keep:
            for old in backups[:-keep]:
                try:
                    old.unlink()
                    logger.debug("Pruned old database backup: %s", old.name)
                except Exception:
                    pass

