# KROVEX — OAuth2 Bot Invite Permissions Audit

**Audit Status:** Complete (Read-Only Inspection & Findings)  
**Target Subsystem:** OAuth2 Scopes, Bot Invite Generation, Permission Integers  
**Relevant Source Files:**
* [`bot/utils/permissions.py`](file:///f:/Death%20Bot/bot/utils/permissions.py)
* [`bot/cogs/utility/cog.py`](file:///f:/Death%20Bot/bot/cogs/utility/cog.py)
* [`bot/cogs/utility/help.py`](file:///f:/Death%20Bot/bot/cogs/utility/help.py)
* [`bot/config.py`](file:///f:/Death%20Bot/bot/config.py)

---

## 1. Executive Summary

Inspection of KROVEX's invite generation architecture reveals that **the bot invite URL deliberately does NOT request the Administrator permission**.

* **Current Implementation:** [`bot/utils/permissions.py`](file:///f:/Death%20Bot/bot/utils/permissions.py#L74-L115) enforces a strict **Least-Privilege Security Policy**.
* **Generated Permission Integer:** `1374690864374` (`administrator=False`).
* **Source Code Constraint:** Line 103 explicitly raises an error if Administrator is included:
  ```python
  if perms.administrator:
      raise ValueError("KROVEX invite permissions must NEVER include Administrator!")
  ```
* **Current OAuth2 URL:**
  ```
  https://discord.com/oauth2/authorize?client_id=1570428426974662718&scope=bot+applications.commands&permissions=1374690864374
  ```

---

## 2. Permission Comparison: Administrator (`8`) vs. Least-Privilege (`1374690864374`)

| Capability | Administrator (`permissions=8`) | Current Least-Privilege (`permissions=1374690864374`) |
|---|---|---|
| **Permission Value** | `8` | `1374690864374` |
| **Manage Roles** | Yes (Can create & grant Admin roles) | Yes (Can create roles, but **cannot grant Administrator**) |
| **Manage Channels** | Yes | Yes |
| **Kick / Ban / Timeout** | Yes | Yes |
| **Manage Messages / Purge** | Yes | Yes |
| **Connect / Speak / Mute / Deafen** | Yes | Yes |
| **View Audit Log** | Yes | Yes |
| **Bypass Channel Overwrites** | Yes (Sees all hidden/private channels) | No (Requires explicit view channel overwrite) |
| **Security Risk Profile** | **HIGH** (Token compromise yields complete server takeover) | **MINIMAL** (Restricted to justified operational scopes) |
| **Discord Verification Standard** | Flagged by Discord security auditors | Complies with Discord Least-Privilege best practices |

---

## 3. Impact on Bot Subsystems

### A. Bot Role Creation (`bot_role_service.py`)
* When KROVEX was invited with `1374690864374` (Least-Privilege), its integration role did not have Administrator.
* Because `KROVEX_ROLE_SPECS` specified `administrator=True`, Discord returned `403 Forbidden` on role creation.
* **The Fix:** In [`bot/services/bot_role_service.py`](file:///f:/Death%20Bot/bot/services/bot_role_service.py#L154-L181), we added a fallback to create dedicated roles with comprehensive granular permissions (`manage_roles`, `manage_channels`, `kick`, `ban`, `manage_messages`, `mute`, `deafen`, etc.) if Administrator is rejected. This guarantees role creation succeeds regardless of whether the bot has Administrator.

### B. Anti-Nuke & Server Governance (`bot/cogs/security/cog.py`)
* For Anti-Nuke and Emergency Lockdown to modify server-wide channels and roles, `manage_guild`, `manage_roles`, and `manage_channels` are required.
* All three are included in `1374690864374`.

### C. Voice Management & OwnerVC (`bot/cogs/ownervc/`)
* Mute, deafen, move members, and manage channel overwrites are all covered in `1374690864374`.

---

## 4. Reauthorization & Installation Behaviour

1. **Existing Server Installations:**
   * Changing the code or generating a new invite link **does not retroactively grant new permissions** to servers where the bot is already installed.
   * If a server owner wants KROVEX to have Administrator in an existing server, they must:
     * Either navigate to **Server Settings -> Roles -> KROVEX** and enable the **Administrator** switch, OR
     * Re-authorize the bot using the Administrator invite URL.
2. **Fresh Installations:**
   * If invited via the current in-bot `,invite` or `/util invite` link, Discord displays the specific permission list (Kick, Ban, Manage Channels, Manage Roles, etc.) without Administrator.

---

## 5. Architectural Decision Options

### Option A: Retain Least-Privilege (`permissions=1374690864374`) [Current Implementation]
* **Pros:** Highest security score; conforms to Discord's bot verification criteria; prevents catastrophic server exposure in the event of credential leakage.
* **Cons:** Cannot create custom roles with `administrator=True` (uses granular administrative permissions fallback instead); cannot see hidden private channels unless granted explicit access.

### Option B: Request Administrator (`permissions=8`)
* **Pros:** Simplifies server setup; guarantees all administrative role creation succeed on first try; bot can see and moderate every channel automatically.
* **Cons:** High security exposure; server owners cautious of security may hesitate to invite the bot.
* **OAuth2 Administrator URL:**
  ```
  https://discord.com/oauth2/authorize?client_id=1570428426974662718&scope=bot+applications.commands&permissions=8
  ```

### Option C: Dual-Invite Selection (Recommended Best Practice)
* Present server owners with two invitation choices in the `/invite` embed:
  1. **Recommended (Least Privilege):** `permissions=1374690864374`
  2. **Full Administrative Access:** `permissions=8`

---

## 6. Recommendations & Next Steps

1. **Keep the Granular Role Fallback in [`bot/services/bot_role_service.py`](file:///f:/Death%20Bot/bot/services/bot_role_service.py):** This ensures role setup never crashes or fails, even if a user invites KROVEX without checking Administrator.
2. **Clarify Invite Options:** If Administrator is desired by default, update `get_krovex_invite_permissions()` in [`bot/utils/permissions.py`](file:///f:/Death%20Bot/bot/utils/permissions.py) to include `administrator=True` upon your approval.
