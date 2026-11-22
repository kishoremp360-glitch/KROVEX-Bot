# KROVEX — Per-Server Security Punishment Configuration Report

**Audit Date:** 2026-11-18  
**Subsystem:** Security Punishment Matrix & Event Governance  
**Branch:** `fix/owner-panel-security-config`  
**Status:** **IMPLEMENTED & VERIFIED**  
**Core Principle:** *Detection is automatic. Punishment is server-owner controlled. Every server has independent security settings.*

---

## 1. Problem Statement

Previously, KROVEX enforced a single global database column `punishment TEXT NOT NULL DEFAULT 'quarantine'` across all security events. Newly added servers were subjected to forced destructive punishments (quarantine or hardcoded kick) without explicit server owner consent. Server owners could not configure independent punishments per security event.

---

## 2. Architecture & Design

### 2.1. Non-Destructive Initial State (Default Policy)
* When a server is newly initialized or an event has not been explicitly configured:
  * **Punishment:** `not_configured` / `log_only` / `none`.
  * **Zero Destructive Actions:** The bot will **never silently ban, kick, timeout, or quarantine**.
  * **Detection & Logging:** Real-time event tracking, incident recording (`security_incidents`, `security_logs`), and channel notifications remain 100% operational.
  * **Status:** Reports clearly that the server owner has not yet configured a punishment policy.

### 2.2. Per-Event Punishment Matrix (`event_punishments`)
In [`bot/database/sqlite_manager.py`](file:///f:/Death%20Bot/bot/database/sqlite_manager.py), the `security_settings` table was enhanced with:
```sql
event_punishments TEXT NOT NULL DEFAULT '{}'
```
Each guild independently stores a JSON mapping of events to punishment choices:
```json
{
  "channel_delete": "ban",
  "mass_kick": "timeout",
  "anti_bot": "kick",
  "anti_raid": "quarantine",
  "anti_spam": "warn"
}
```

### 2.3. Supported Events & Choices
* **Supported Security Events:**
  1. `anti_nuke` — Global anti-nuke fallback
  2. `channel_delete` — Mass channel deletion
  3. `role_delete` — Mass role deletion
  4. `mass_ban` — Mass member ban threshold
  5. `mass_kick` — Mass member kick threshold
  6. `anti_bot` — Unauthorized bot addition
  7. `anti_webhook` — Rogue webhook creation
  8. `anti_raid` — Rapid member join rate
  9. `anti_spam` — Chat message spam
  10. `anti_phishing` — Suspicious & malicious links
  11. `anti_mention_spam` — Mass mention flooding
  12. `account_age` — New account minimum age requirement
* **Supported Punishment Choices:**
  * `not_configured` — Log Only / No action (Default)
  * `warn` — Direct message security warning
  * `timeout` — 10-minute temporary timeout
  * `quarantine` — Immediate role isolation via `⚠️ Quarantined`
  * `kick` — Server kick
  * `ban` — Permanent guild ban

### 2.4. Punishment Execution Safety
Before executing any configured punishment in [`bot/services/security_service.py`](file:///f:/Death%20Bot/bot/services/security_service.py):
1. **Verification of Explicit Policy:** If punishment is `not_configured`, `log_only`, or `none`, the bot logs the incident and returns immediately without touching the member.
2. **Role Hierarchy Protection:** Checks `guild.me.top_role.position > member.top_role.position`. If the target's role is equal to or higher than the bot's, execution aborts with a diagnostic warning.
3. **Bot Permission Check:** Checks `guild.me.guild_permissions` for the required scope (`ban_members`, `kick_members`, `moderate_members`, `manage_roles`). Never silently substitutes an alternate action.

---

## 3. Interactive UX in Security Panel

In [`bot/cogs/security/panel.py`](file:///f:/Death%20Bot/bot/cogs/security/panel.py):
* **`SecurityPunishmentConfigView`:**
  * Event Select Dropdown: Pick any of the 12 supported events.
  * Punishment Select Dropdown: Pick from the 6 supported punishment choices.
  * **Save Policy Button:** Commits the configuration to SQLite for that specific guild.
  * **Reset Policy Button:** Restores that event to `not_configured`.
  * Live status table showing current policies for every event.

---

## 4. Verification Evidence

* `test_new_guild_defaults_to_non_destructive_log_only` passed.
* `test_per_event_punishment_configuration_independent` passed.
* `test_configured_punishment_executes_safely` passed.
* `test_role_hierarchy_blocks_higher_target` passed.
* `test_punishment_reset_to_not_configured` passed.
