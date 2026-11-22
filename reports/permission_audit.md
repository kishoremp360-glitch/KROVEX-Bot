# KROVEX — Security Permission & Privilege Separation Audit

**Audit Date:** 2026-11-18  
**Subsystem:** Discord API Permissions & Privilege Separation  
**Branch:** `fix/owner-panel-security-config`  
**Status:** **AUDITED & COMPLIANT**  

---

## 1. Overview & Principle

KROVEX enforces strict least-privilege principles and privilege separation:
1. **No Universal Administrator Bypasses:** Features and commands request only the permissions technically required for their operations.
2. **Clear Boundary Between Voice & Admin:** General governance (OwnerPanel, Security Whitelist, Anti-Nuke Settings) operates completely independently of Voice Channel states. Voice channel validation is restricted strictly to voice-related commands.
3. **Hierarchy Enforcement:** In Discord, a bot can never moderate, kick, ban, or assign roles to members whose highest role is equal to or higher than the bot's highest role. KROVEX checks role hierarchy before all punishment and migration operations.

---

## 2. Granular Permissions Required by Security Subsystems

| Subsystem / Operation | Minimum Discord Permission | Purpose / Justification |
|---|---|---|
| **Audit Log Inspection** | `View Audit Log` | Identifies rogue actors for channel delete, role delete, bot add, webhook create |
| **Ban Execution** | `Ban Members` | Executes configured `ban` punishment against verified rogue actors |
| **Kick Execution** | `Kick Members` | Executes configured `kick` punishment against verified rogue actors |
| **Timeout Execution** | `Moderate Members` | Executes 10-minute timeout for configured `timeout` punishment |
| **Quarantine Role Provisioning** | `Manage Roles` | Creates and assigns `⚠️ Quarantined` isolation role |
| **Lockdown & Channel Overrides** | `Manage Channels` | Revokes `send_messages` / `view_channel` during emergency server lockdown |
| **Rogue Webhook Removal** | `Manage Webhooks` | Deletes unauthorized webhooks created by non-whitelisted actors |
| **Bot Role Provisioning** | `Manage Roles` | Creates, hoists, and elevates KROVEX dedicated security roles |

---

## 3. Dedicated KROVEX Role Hierarchy Audit

KROVEX provisions dedicated security roles:
1. `⚪ KROVEX` (OAuth2 Application Managed Role, `managed=True`, position determined by invite).
2. `🌸 KROVEX Prime Security™` (Custom hoisted security role, Silver/Pink branding).
3. `🌸 KROVEX Unbypassable Security™` (Custom hoisted security role, high barrier).

### Permission Hierarchy Compliance:
* When KROVEX is invited with Administrator (`permissions=8`), it possesses the technical authority to elevate custom roles below its own integration role.
* If invited with granular permissions, KROVEX automatically uses a non-Administrator fallback with granular permissions (`manage_roles`, `manage_channels`, `kick_members`, `ban_members`, `moderate_members`, `view_audit_log`, `manage_messages`).
* Unremovable role protection restores KROVEX dedicated roles if manually detached, preventing rogue administrators from stripping bot protections.

---

## 4. Privilege Matrix Summary

```
OwnerPanel Commands:
└── Server Sovereign (guild.owner_id) OR Bot Owner / Co-owner
    └── Full access to OwnerDashboardView (11 modular categories)
└── Ordinary Members: Rejected with "Access Denied"

Security Whitelist & Punishments:
└── Server Sovereign, Bot Owner, OR Administrator
    └── Interactive SecurityWhitelistView (Add, Remove, View)
    └── Interactive SecurityPunishmentConfigView (Configure, Save, Reset)
└── Ordinary Members: Rejected with "Administrators only"
```
