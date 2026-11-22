# KROVEX — Central Defect & Vulnerability Register

**Branch:** `qa/krovex-complete-audit`  
**Severity Classification:**
* **P0 — Critical:** Credential exposure, unauthorized owner access, security bypass, production data corruption.
* **P1 — High:** Major protection failure, startup crash, core moderation/voice broken, database inconsistency.
* **P2 — Medium:** Non-critical command failure, interactive component timeout, recoverable service error.
* **P3 — Low:** Visual discrepancy, embed formatting nuance, non-blocking UX refinement.

---

## Defect Log

| Bug ID | Phase | Source Component | Severity | Description | Status | Proposed / Implemented Fix |
|---|---|---|---|---|---|---|
| **BUG-001** | Phase 1/Roles | `bot/services/bot_role_service.py` | **P2** | Legacy role migration raised 403 Forbidden when legacy role was above bot top role | **RESOLVED** | Added hierarchy position guard (`top_pos > legacy_pos`) and appearance-only edit fallback |
| **BUG-002** | Phase 2 | `bot/database/repositories/sqlite_repos.py` | **P1** | Security methods (`log_incident`, `is_trusted`, `get_recent_incidents`, etc.) misplaced in `PlaylistRepository` | **RESOLVED** | Relocated all security logging and verification methods to `SecurityRepository` |
| **BUG-003** | Phase 2 | `bot/services/security_service.py` | **P2** | Missing `on_webhooks_update` event listener for anti-webhook threshold enforcement | **RESOLVED** | Implemented `on_webhooks_update` with audit log parser, incident tracking, and rogue webhook deletion |
| **BUG-004** | Phase 3 | `bot/database/models.py` | **P1** | `ModerationLog` dataclass missing `duration_seconds` argument causing runtime TypeError on `/timeout` logging | **RESOLVED** | Added `duration_seconds: Optional[int] = None` to `ModerationLog` dataclass and repository fetcher |
| **BUG-005** | Phase 3 | `bot/cogs/moderation/cog.py` & `automod_service.py` | **P2** | Bot Owner immunity not evaluated in moderation hierarchy and AutoMod exemptions | **RESOLVED** | Added Bot Owner and Server Sovereign immunity checks to `_check_hierarchy` and `_is_exempt` |

---

## Bug Summary Metrics

* **P0 (Critical):** 0
* **P1 (High):** 2 (All Resolved)
* **P2 (Medium):** 3 (All Resolved)
* **P3 (Low):** 0
* **Total Defects:** 5 (All Resolved)
