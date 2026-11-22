# KROVEX — Security Fixes Pre-Implementation Audit Report

**Audit Date:** 2026-11-18  
**Working Branch:** `fix/owner-panel-security-config`  
**Engineer:** Senior Discord.py, Security Systems & Database Reliability Engineer  

---

## 1. Environment & Git State Inspection

* **Current Branch:** `fix/owner-panel-security-config` (branched cleanly from `qa/krovex-complete-audit` at commit `37f2540`).
* **Working Tree:** Clean (zero untracked or uncommitted changes).
* **Previous Phase Audits:**
  * Phase 1 (Core System & Startup): 39/39 tests passed (`reports/phase_01_core.md`).
  * Phase 2 (Security & Anti-Nuke): 16/16 tests passed (`reports/phase_02_security.md`).

---

## 2. Source Code & Root Cause Inspection

### 2.1. Issue 1: OwnerPanel Voice Channel Requirement Bug
* **Inspected File:** [`bot/cogs/admin/owner_panel.py`](file:///f:/Death%20Bot/bot/cogs/admin/owner_panel.py#L821-L847)
* **Code Trace:**
  ```python
  # Determine target voice channel: user's voice channel or first guild voice channel
  channel = None
  if hasattr(user, "voice") and user.voice and isinstance(user.voice.channel, discord.VoiceChannel):
      channel = user.voice.channel
  elif guild.voice_channels:
      channel = guild.voice_channels[0]

  if channel is None:
      embed = EmbedBuilder.warning(
          title="Voice Channel Required",
          description="No voice channel detected. Please join a voice channel or create one to initialize the Owner & Staff Moderation Dashboard.",
      )
      ...
      return

  from bot.cogs.ownervc.dashboard import OwnerVCControlView, build_owner_vc_embed
  view = OwnerVCControlView(self.bot, channel)
  ```
* **Root Cause Assessment:**
  `_execute_ownerpanel` was improperly wired to instantiate and render `OwnerVCControlView` (the voice-channel staff controls from `bot.cogs.ownervc.dashboard`).
  The actual, comprehensive `OwnerDashboardView` (with 11 categories: Overview, Security, AutoMod, Logging, Tickets, Economy, Music, SOUL AI, Config, Diagnostics, Telemetry, and VC staff management) is implemented directly above it in lines 236–746, but was completely bypassed!
* **Required Fix:** Re-route `_execute_ownerpanel` to initialize `OwnerDashboardView(self.bot, guild)` and render its embed. Zero voice channel connection required.

---

### 2.2. Issue 2: Security Whitelist Access Failure & Missing Management UX
* **Inspected Files:** [`bot/cogs/security/cog.py`](file:///f:/Death%20Bot/bot/cogs/security/cog.py#L114-L126), [`bot/cogs/security/panel.py`](file:///f:/Death%20Bot/bot/cogs/security/panel.py)
* **Code Trace:**
  ```python
  @staticmethod
  def _is_admin(ctx: UnifiedContext) -> bool:
      if ctx.is_interaction:
          return ctx.interaction.user.guild_permissions.administrator
      return ctx.author.guild_permissions.administrator if ctx.author else False
  ```
* **Root Cause Assessment:**
  `_is_admin` checked only the raw Discord role bit `guild_permissions.administrator`. It failed to grant access to the actual **Server Sovereign** (`user.id == guild.owner_id`) or **Bot Owner / Co-owner** (`self.bot.is_owner_or_co_owner(user)`).
  In addition, `/security whitelist` merely displayed a static text embed without interactive capabilities to Add, Remove, View, or Cancel changes.
* **Required Fix:**
  1. Upgrade `_is_admin` to validate Server Owner, Bot Owner, and Administrators.
  2. Implement an interactive `SecurityWhitelistView` supporting user/role addition, removal, and confirmation, with strict per-guild database isolation.

---

### 2.3. Issue 3: Forced Default Security Punishments & Lack of Per-Server Configuration
* **Inspected Files:**
  * [`bot/database/sqlite_manager.py`](file:///f:/Death%20Bot/bot/database/sqlite_manager.py#L242): `punishment TEXT NOT NULL DEFAULT 'quarantine'`.
  * [`bot/services/security_service.py`](file:///f:/Death%20Bot/bot/services/security_service.py#L134): single global punishment lookup with fallback to `'quarantine'`, plus hardcoded `'kick'` in lines 250 & 288.
* **Root Cause Assessment:**
  All security events share a single global setting or hardcoded destructive actions. Newly added guilds are subjected to forced destructive punishments (quarantine/kick) without explicit server owner consent.
* **Required Fix:**
  1. Add `event_punishments TEXT NOT NULL DEFAULT '{}'` to `security_settings` in SQLite.
  2. Implement the **KROVEX Non-Destructive Initial Policy**:
     * Newly configured events start with `not_configured` / `log_only`.
     * Zero destructive actions (no kicks, bans, timeouts, or quarantines) occur unless the server owner explicitly configures a punishment.
     * Security detection and audit logging remain 100% active.
  3. Support per-event punishment matrix:
     * Events: `anti_nuke`, `channel_delete`, `role_delete`, `mass_ban`, `mass_kick`, `anti_bot`, `anti_webhook`, `anti_raid`, `anti_spam`, `anti_phishing`, `anti_mention_spam`, `account_age`.
     * Allowed Choices: `not_configured`, `log_only`, `warn`, `timeout`, `quarantine`, `kick`, `ban`.
  4. Build interactive `SecurityPunishmentConfigView` within the Security Panel.

---

## 3. Pre-Implementation Safety Checklist

- [x] Inspection executed without modifying production data or environment variables.
- [x] Zero credentials exposed.
- [x] Backward-compatible database migration planned (`ALTER TABLE security_settings ADD COLUMN event_punishments TEXT NOT NULL DEFAULT '{}'`).
- [x] Dedicated branch verified: `fix/owner-panel-security-config`.
- [x] Step-by-step implementation plan established.
