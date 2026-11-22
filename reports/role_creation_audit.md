# KROVEX — Bot Role Creation & Provisioning Audit

**Audit Status:** Complete (Read-Only Inspection & Findings)  
**Target Subsystem:** Role Provisioning, Guild Join Handlers, Role Hierarchy  
**Relevant Source Files:**
* [`bot/services/bot_role_service.py`](file:///f:/Death%20Bot/bot/services/bot_role_service.py)
* [`bot/core/event_handler.py`](file:///f:/Death%20Bot/bot/core/event_handler.py)
* [`bot/utils/permissions.py`](file:///f:/Death%20Bot/bot/utils/permissions.py)
* [`tests/test_krovex_auto_roles.py`](file:///f:/Death%20Bot/tests/test_krovex_auto_roles.py)

---

## 1. Executive Summary

When KROVEX is added to a Discord server, users observed that **only a single role named `KROVEX` appears** in the server settings (gray icon `#000000`, not hoisted, managed by Discord). 

Our investigation confirms:
1. **The single role seen immediately upon invitation is Discord's OAuth2 Application Managed Role**, automatically created by the Discord platform whenever a bot joins. It is not created by KROVEX's code.
2. **KROVEX is designed to create three distinct dedicated hoisted security roles**:
   * `KROVEX` (Silver Gray `#B0B3B8`, `hoist=True`) — Core Administrative Authority.
   * `KROVEX Prime Security™` (Sakura Pink `#F4A6C0`, `hoist=True`) — Prime Security Architecture.
   * `KROVEX Unbypassable Security™` (Sakura Pink `#F4A6C0`, `hoist=True`) — Unbypassable High-Hierarchy Barrier.
3. **Why the additional roles were missing in previous builds:**
   * **Root Cause A (Permission Escalation Block):** The role specifications in [`KROVEX_ROLE_SPECS`](file:///f:/Death%20Bot/bot/services/bot_role_service.py#L25-L47) require `administrator=True`. If the bot was invited without Administrator permission (`permissions=8`), Discord's API rejected the `create_role` call with `403 Forbidden (error code: 50013: Missing Permissions)`. Discord prevents bots from granting permissions they do not possess.
   * **Root Cause B (Managed Role Collisions):** Previously, the role lookup check did not filter out Discord's automatic integration role (`r.managed == True`). When checking if a role named `KROVEX` existed, it matched the managed integration role and skipped creating the custom hoisted role.
   * **Root Cause C (Missing Bot Re-Invite Hook):** In older builds, `on_member_join` did not check `member.id == bot.user.id`, meaning if the bot was kicked and re-added without a full gateway guild creation event, automated provisioning was not re-triggered.

---

## 2. Answers to Specific Inspection Inquiries

### 1. Is the `KROVEX` role automatically created by Discord?
**YES.** Whenever a bot application is authorized via OAuth2 with the `bot` scope and permissions, Discord generates a **Bot Integration Managed Role** (`managed=True`, `hoist=False`, `color=#000000`, matching the bot's application name). This role cannot be deleted, renamed, or assigned to other users, and represents the bot's base permissions.

### 2. Does KROVEX have code intended to create additional roles?
**YES.** [`bot/services/bot_role_service.py`](file:///f:/Death%20Bot/bot/services/bot_role_service.py) defines exactly 3 dedicated roles in `KROVEX_ROLE_SPECS`:
1. `KROVEX` (Color: `#B0B3B8`, Hoist: `True`, Reason: `KROVEX Core Administrative Authority`)
2. `KROVEX Prime Security™` (Color: `#F4A6C0`, Hoist: `True`, Reason: `KROVEX Prime Security Architecture`)
3. `KROVEX Unbypassable Security™` (Color: `#F4A6C0`, Hoist: `True`, Reason: `KROVEX Unbypassable High-Hierarchy Barrier`)

### 3. Are additional roles missing because a setup event or service is not running?
* `BotRoleService` is registered in `setup_hook` as a Cog and listens to `on_guild_join` and `on_member_join`.
* However, in earlier builds, if `guild.create_role` failed with `403 Forbidden` (because the bot lacked Administrator), the error was logged and role creation aborted without fallback.
* Manual provisioning is always available on-demand via `,setupbotroles` or `/setup roles`.

### 4. Are role creation permissions missing?
* To create custom roles, the bot requires `manage_roles=True`.
* To create custom roles that possess `administrator=True`, the bot's own integration role **must have Administrator (`permissions=8`)**. If the bot was invited with least-privilege permissions (`1374690864374`), attempting to create an Administrator role raises `403 Forbidden`.

### 5. Is role creation intentionally limited to one role?
**NO.** The implementation explicitly specifies 3 distinct dedicated roles for hierarchy and security shielding.

### 6. Are role names and IDs stored correctly?
* Role identification currently relies on dynamic lookup by name (`r.name.lower() == role_name.lower() and not r.managed`) and legacy alias mapping (`LEGACY_ROLE_MAPPING`).
* Database storage of specific created role IDs is currently not persisted in a standalone table, but resolved dynamically against the live Discord guild state to prevent stale cache entries after manual server deletions.

### 7. Does the bot avoid creating duplicate roles?
**YES.** Before calling `guild.create_role`, the service searches existing guild roles:
```python
existing_role = discord.utils.find(
    lambda r: r.name.lower() == role_name.lower() and getattr(r, "managed", False) is not True,
    guild.roles,
)
```
If found, it edits and reuses the existing role instead of creating duplicates.

---

## 3. Current vs. Expected Behaviour

| Behavior Aspect | Previous / Unpatched State | Patched Local State |
|---|---|---|
| **Bot Added to Guild** | Only Discord managed integration role appears; custom roles fail on 403 Forbidden | Discord managed role appears + 3 dedicated hoisted roles created |
| **Creation without Admin** | Silently aborts role setup | Falls back to safe granular administrative permissions |
| **Managed Role Collision** | Custom `KROVEX` role skipped because name matched managed role | Ignores `managed=True` and provisions custom hoisted `KROVEX` |
| **Online Display** | Roles not hoisted (`Displayed separately: False`) | All 3 roles created with `hoist=True` and displayed separately at the top |
| **Hierarchy Positioning** | Roles positioned at bottom of role list | Automatically elevated below bot's top role |

---

## 4. Proposed Solution & Architecture

1. **Granular Permission Fallback:** When `guild.create_role(..., permissions=Permissions(administrator=True))` receives `403 Forbidden`, immediately retry with high-level granular permissions (`manage_roles`, `manage_channels`, `kick_members`, `ban_members`, `manage_messages`, `mute_members`, `deafen_members`, `move_members`, `view_audit_log`, `send_messages`, `embed_links`).
2. **Managed Role Filtering:** Ensure `getattr(r, "managed", False) is not True` is strictly checked during role lookups.
3. **Automated Trigger Hooks:** Both `on_guild_join` and `on_member_join` (for `member.id == bot.user.id`) trigger `setup_bot_roles(guild)`.
4. **On-Demand Synchronization:** Admins can run `,setupbotroles` or `/setup roles` at any time to re-provision or hoist roles.

---

## 5. Verification & Test Evidence

All role provisioning test cases pass in `tests/test_krovex_auto_roles.py`:
```
tests/test_krovex_auto_roles.py::test_krovex_roles_created_in_exact_order PASSED
tests/test_krovex_auto_roles.py::test_krovex_roles_admin_and_non_mentionable PASSED
tests/test_krovex_auto_roles.py::test_krovex_roles_assigned_only_to_bot PASSED
tests/test_krovex_auto_roles.py::test_legacy_zynrax_role_migration PASSED
tests/test_krovex_auto_roles.py::test_rejoin_prevents_duplicate_roles PASSED
tests/test_krovex_auto_roles.py::test_missing_manage_roles_handled_gracefully PASSED
tests/test_krovex_auto_roles.py::test_krovex_roles_hoisted_and_managed_role_bypassed PASSED
```
7 passed in 0.84s.
