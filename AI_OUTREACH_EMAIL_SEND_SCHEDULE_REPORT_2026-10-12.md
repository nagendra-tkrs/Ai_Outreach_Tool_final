# AI Client Outreach Tool — Email Send & Scheduling Subsystem Report

**Date:** 2026-10-12
**Scope:** Complete deep-dive on the two subsystems that put email into the world — **sending mail** and **scheduling mail to send**. Read-only; no messages were sent and no state was changed.
**Project root:** `C:\Users\Hello\OneDrive\Desktop\new  and final ai outreach tool\Ai_Outreach_Tool`

> **Evidence legend:** **[R]** live runtime · **[S]** source code (file:line) · **[I]** inferred

---

## 1. Subsystem Map at a Glance

```
                         ┌─────────────────────────────────────────────┐
                         │  OPERATOR (UI)                               │
                         │  CompanyDetail.jsx                           │
                         │   • handleSendEmail        (L665)           │
                         │   • handleActivateSchedule (L694)           │
                         └───────────────┬─────────────────────────────┘
                                         │ HTTP
        ┌────────────────────────────────┼────────────────────────────────┐
        │                                ▼                                │
        │   POST /outreach/{id}/send  ──► send_outreach_email()           │  (MANUAL SEND)
        │   POST .../outreach/schedule ─► schedule_sequence_steps()        │  (ARM)
        │                                                                     │
        │   ┌─────────────── 60-second asyncio loop ───────────────┐        │
        │   │  _scheduler_loop (L520) ─► process_scheduled_emails   │        │  (AUTO)
        │   │      └► process_automated_follow_ups (reconciler)     │        │
        │   │      └► _dispatch_scheduled_message (atomic claim)    │        │
        │   └────────────────────────────────────────────────────────┘        │
        │                                                                     │
        │   Every send → record_email_dispatch() → activate_followups_on_send()│
        │   Every send → aiosmtplib → SMTP → sent/failed                     │
        │   Every send → tracking pixel + click rewrite + List-Unsubscribe    │
        └─────────────────────────────────────────────────────────────────────┘
```

**Runtime fact [R]:** the 60-second loop is **currently disabled** (safe-mode runner intercepts `start_scheduler`). The manual send route is live. Nothing is scheduled to auto-send.

---

## 2. Entry Point 1 — Manual Send

### 2.1 Route [S]
`POST /api/outreach/{message_id}/send` — `outreach_routes.py` **L290**
```python
recipient_email = payload.get("recipientEmail")      # L292
cc_recipients     = payload.get("ccRecipients")       # L293
bcc_recipients    = payload.get("bccRecipients")      # L294
result = await send_outreach_email(message_id, {...}) # L296
```
- **No authentication** on this route. Anyone who can reach `:5000` can send. **[S]**
- The operator may override `recipientEmail`, `ccRecipients`, `bccRecipients` at send time; these override the stored message (`email_service.py` L246, L262–263). [S]

### 2.2 Frontend trigger [S]
`CompanyDetail.jsx` `handleSendEmail` (**L665**):
- Blocks re-send if `editingMessage.status === 'sent'` (L668).
- `POST /outreach/{id}/send` with `recipientEmail`, `ccRecipients`, `bccRecipients` (L676–680).
- On success: clears the draft flag, refetches outreach + company (L684–686).

### 2.3 Core function `send_outreach_email` — `email_service.py` **L205** (full ordered flow)

| Step | Line | Action |
|---|---|---|
| 1 | L218–224 | Resolve `message_id` → 400 if invalid, 404 if missing |
| 2 | **Duplicate-send guard** L228–232 | If `status == 'sent'` → **HTTP 409** "already been sent" |
| 3 | **Quarantine hard-stop** L239–244 | If quarantined → **HTTP 409**, message left untouched |
| 4 | L246–249 | Resolve target recipient; **400 if empty** |
| 5 | L251–253 | Optional domain-match enforcement (if `ENFORCE_RECIPIENT_DOMAIN_MATCH`) |
| 6 | **Recipient syntax** L256–260 | `validate_recipient_email` → **400** if malformed |
| 7 | L262–267 | Normalise CC/BCC (accepts list or comma-string) |
| 8 | **Suppression** L271 | `assert_not_suppressed(target, cc)` → **403** if suppressed |
| 9 | L273 | `get_smtp_config()` — 400 if SMTP unconfigured / password missing or masked |
| 10 | **Send limits** L277 | `assert_send_limits` → **429** daily/per-domain exceeded |
| 11 | L279 | Set `status = 'sending'`, `error = ''` (marks in-flight) |
| 12 | L282–284 | Build tracking pixel + unsubscribe URL from `API_BASE_URL` |
| 13 | L287 | **Rewrite all http(s) links** through `/api/track/click/{id}` |
| 14 | L289–309 | Build `EmailMessage` (From/To/Cc/Bcc/Subject, HTML+text, **List-Unsubscribe** header L301–302) |
| 15 | L311–320 | `aiosmtplib.send(...)` (skipped only if `isTest` sandbox) |
| 16 | L324–336 | On success: `status='sent'`, `sentAt`, `messageId`, `isTestSend`, CC/BCC persisted |
| 17 | L338–347 | Build `dispatch_result`; call `record_email_dispatch(message, result)` |
| 18 | L350–368 | **On any exception:** set `status='failed'` + sanitized error, record dispatch, re-raise |

**Key point:** the only states that reach SMTP are those that passed *all* guards. A `draft`/`approved`/`failed` message can be sent manually; only `sent` and quarantined are hard-blocked. [S]

---

## 3. Entry Point 2 — Schedule (Arm) Mail to Send

### 3.1 Route [S]
`POST /api/companies/{company_id}/outreach/schedule` — `outreach_routes.py` **L49**
```python
schedules = payload.get("schedules", [])                # L52
updated = await schedule_sequence_steps(company_id, schedules)  # L53
# then a READ-ONLY scan for quarantined messages the arming refused to touch (L58–72)
```
- Body shape (frontend `handleActivateSchedule` L697–703):
  ```json
  {"schedules":[{"step":1,"delayDays":0},
                 {"step":2,"delayDays":3},
                 {"step":3,"delayDays":6}]}
  ```
- `quarantinedSkipped` (L58–84) is **read-only**: it only *reports* quarantined messages the arming refused to touch; it never modifies their status/quarantine metadata. [S]

### 3.2 Core function `schedule_sequence_steps` — `scheduler_service.py` **L120**

For each step in `schedules`:
1. `delay_days = int(s["delayDays"])` (clamped ≥ 0). `step` required.
2. `new_status = "approved" if delay_days == 0 else "scheduled"` (L147).
3. **Atomic arming** (L154–164) — the ONLY arming path:
   ```python
   find_one_and_update(
     {"companyId": comp_oid, "step": step,
      "status": {"$in": ["draft","approved","scheduled"]},
      "quarantined": {"$ne": True}, "quarantine.active": {"$ne": True}},
     {"$set": {"status": new_status, "delayDays": delay_days, "updatedAt": now}},
   )
   ```
   The quarantine filter is **inside** the atomic update, so no race can arm a quarantined message. [S]
4. If nothing matched (L165–181): if a *quarantined* message exists for that step, log a warning and **skip** (leave it untouched). [S]
5. `delay_days > 0` → compute `scheduledAt = base_time + delay_days`, set on message (L186–191), and mirror onto the record via `_sync_record_schedule` (L192). [S]
6. `delay_days == 0` (manual Step 1) → **`$unset scheduledAt`** so it can never auto-fire (L195–198). [S]

### 3.3 Due-time calculation [S]
- **Policy defaults:** `DEFAULT_FOLLOWUP_DELAYS = {2: 3, 3: 7}` (`outreach_tracking_service.py` L56) — 3-day / 7-day drip.
- **Explicit `delayDays` on the message is authoritative** (`_followup_delay` L59); a *missing* `delayDays` falls back to the policy default; an explicit `0` is kept.
- **Anchor time** (`_step_base_time` L87): for Step 2/3, the schedule is anchored to the **previous step's actual `sentAt`** when available, else `now`. So a Step-2 with `delayDays=3` goes out 3 days after Step 1 was actually sent.
- **Note:** the UI modal defaults are `step2Days:3, step3Days:6` (`CompanyDetail.jsx` L206) — Step 3 defaults to **6** in the UI but **7** in the backend policy. Minor inconsistency. [S]

### 3.4 `followup_config.py` — defined but unused [S]
`backend/app/config/followup_config.py` defines `FOLLOW_UP_1_DELAY_DAYS=3`, `FOLLOW_UP_2_DELAY_DAYS=7` from env. **Nothing imports it** — the tracking service hardcodes `{2:3, 3:7}` (L56). Two sources of truth. [S]

---

## 4. The 60-Second Scheduler (Automatic Send)

### 4.1 Startup [S]
`main.py` **L31**: `start_scheduler(60)` inside the FastAPI `lifespan`. `start_scheduler` (`scheduler_service.py` **L535**) creates `_scheduler_loop` as an `asyncio.Task`. `_scheduler_loop` (L520) runs `process_scheduled_emails()` **once immediately on start**, then every 60 s.

**Runtime [R]:** the safe-mode runner replaces `app.main.start_scheduler` with a no-op **before** `uvicorn.run`, so the loop never starts. Log confirms: `[safe-mode] start_scheduler() call intercepted and DISABLED`.

### 4.2 `process_scheduled_emails` — `scheduler_service.py` **L440**
Two phases per tick:

**Phase A — due `scheduled` messages** (L454–509):
- Select up to 10 messages: `status='scheduled'`, `scheduledAt <= now`, `quarantined != True`, `quarantine.active != True` (L454–461).
- Skip quarantined (L466); skip if the contact already replied → `cancel_pending_followups` (L476–481).
- **Evidence gate** (L484): if company evidence/service missing → log + skip (no fabrication).
- Dispatch via `_dispatch_scheduled_message` (L495); on `failed`, mark the record's step FAILED (L498–509).

**Phase B — record-level follow-up reconciliation** → `process_automated_follow_ups` (L512).

### 4.3 `_dispatch_scheduled_message` — `scheduler_service.py` **L252** (atomic claim + send)
1. **Quarantine check** (L264) — refuse to dispatch even if bad data put one in `scheduled`.
2. **Sending window** (L271) — outside 09:00–18:00 → `deferred` (no send).
3. **Prior-step gate** (L276) — follow-up before its predecessor is sent → `not_ready`.
4. **Atomic claim** (L284–293):
   ```python
   find_one_and_update(
     {"_id": message_id, "status": "scheduled",
      "quarantined": {"$ne": True}, "quarantine.active": {"$ne": True}},
     {"$set": {"status": "sending", "updatedAt": now}})
   ```
   Only one worker can transition `scheduled → sending`; if it loses the race → `skipped`.
5. `send_outreach_email(...)` (L298) — the *same* guarded path as manual send.
6. On `HTTPException` → `_release_or_fail` (L304): 429 → back to `scheduled` (deferrable); else → `failed`. On other exceptions → `failed` (L308).

### 4.4 `process_automated_follow_ups` — `scheduler_service.py` **L312** (reconciler)
This worker **never generates a message and never activates a draft**. Per follow-up step (2→`followUp1`, 3→`followUp2`):
- Select due records: prior step `SENDING→SENT`, this follow-up `PENDING` with `scheduledAt <= now`, `replyStatus='NO_REPLY'` (L332–339).
- Re-fetch + re-check reply/sent (L344–350).
- **Evidence gate** (L353): fail → mark the record's follow-up `BLOCKED` (never fabricate).
- Find the authoritative `scheduled` message (L376, `exclude_quarantined=True`):
  - **If the message is `draft` (inactive):** reconcile the record — `$unset` the stale `scheduledAt`, leaving the follow-up `PENDING` with no schedule (L393–407). **It never arms the draft.**
  - If no armed message and no draft → leave pending (L408–412).
- If `scheduledAt` still in the future → skip (L414).
- Dispatch via `_dispatch_scheduled_message` (L420); on `failed` mark the record step FAILED (L429).

---

## 5. Follow-up Activation on Send

### 5.1 `activate_followups_on_send` — `outreach_tracking_service.py` **L71**
Called from `record_email_dispatch` after a **Step-1** send (L242) and after a **Step-2** send (L260). For each follow-up step (2, 3):
- Find the step message by company + step (+ recipient match) (`_find_step_message` L40).
- **Quarantined → never armed** (L95–99): record stays `PENDING`, message untouched.
- `sent` → mirror as `SENT` (idempotent). `failed` → mirror `FAILED`.
- `scheduled` + `scheduledAt` → keep existing `scheduledAt`, mirror as `PENDING` (L109–111).
- **else (draft/any non-terminal) → arm atomically** (L116–136):
  ```python
  find_one_and_update(
    {"_id": msg["_id"], "status": {"$in": ["draft","scheduled"]},
     "quarantined": {"$ne": True}, "quarantine.active": {"$ne": True}},
    {"$set": {"status":"scheduled", "scheduledAt": now + delayDays,
              "delayDays": delay, "updatedAt": now}})
  ```
  If it loses a race (sent/failed/quarantined concurrently) → record stays `PENDING` (L131–135). [S]

### 5.2 `cancel_pending_followups` — `outreach_tracking_service.py` **L140**
On reply (`update_reply_status` L366) or scheduler reply-skip: armed Step 2/3 messages (`status in scheduled/approved`) → back to `draft` with `cancelledReason` (L152–160); the record's pending follow-ups → `CANCELLED` (L164–167). Already-sent steps untouched. [S]

### 5.3 `record_email_dispatch` — `outreach_tracking_service.py` **L171**
Creates/updates the `outreachrecords` projection on every send (success or failure):
- New record seeded with `initialEmail/followUp1/followUp2 = PENDING`, `replyStatus='NO_REPLY'`, `campaignStatus='PENDING'` (L200–220).
- Step 1 success → `initialEmail=SENT`, `campaignStatus='INITIAL_SENT'`, then `activate_followups_on_send` (L242).
- Step 2 success → `followUp1=SENT`, `campaignStatus='FOLLOW_UP_1_SENT'`, arm Step 3 (L260).
- Step 3 success → `followUp2=SENT`, `campaignStatus='FOLLOW_UP_2_SENT'`.
- `isTestSend` kept consistent (L223–228); stats exclude test sends (L372 `real_only`). [S]

---

## 6. Email Content, Tracking & Unsubscribe (part of every send)

### 6.1 Link rewriting [S] — `email_service.py` `rewrite_tracking_links` **L29**
Every `href="http(s)..."` in the outgoing HTML is rewritten to
`{base_url}/api/track/click/{message_id}?url=<quoted-original>` (L49). `mailto:`, `#`, relative links and the tracking pixel are untouched (L48). The click endpoint validates the target before redirecting.

### 6.2 Tracking pixel & unsubscribe header [S]
- Tracking pixel: `<img src="{base}/api/track/open/{message_id}.png">` (L283).
- `List-Unsubscribe: <{base}/api/track/unsubscribe/{message_id}>` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (L301–302).

### 6.3 Tracking routes [S] — `tracking_routes.py`
| Route | Line | Behaviour |
|---|---|---|
| `GET /track/open/{id}` | L16 | `$inc openCount`, set `openedAt`; returns 1×1 GIF (L13) |
| `GET /track/click/{id}?url=` | L45 | `$inc clickCount`, set `clickedAt`; **open-redirect guard** — only `http/https` + netloc allowed (L62–69), else redirect to `/` |
| `GET /track/unsubscribe/{id}` | L73 | Writes a **suppression** record for the message's `recipientEmail` (L84–90); redirects to `/unsubscribed` |

### 6.4 Suppression enforcement [S] — `send_guard.py`
`assert_not_suppressed` (L242) blocks the target **and any CC** (L255–264) → HTTP 403. `add_suppression` (L176) upserts by lowercase email.
**Runtime [R]:** the `suppressions` collection is currently **empty** — no unsubscribe has been processed yet.

---

## 7. Safety Guards — Complete Checklist (with line numbers)

| # | Guard | Location | Blocks |
|---|---|---|---|
| 1 | Duplicate send | `email_service.py` L228 | Re-send of `sent` (409) |
| 2 | Quarantine (send boundary) | `email_service.py` L239 | Any quarantined message (409) |
| 3 | Empty recipient | `email_service.py` L247 | Missing To (400) |
| 4 | Recipient syntax | `send_guard.py` L93 / `email_service.py` L256 | Malformed address (400) |
| 5 | Domain mismatch (optional) | `send_guard.py` L363 / `email_service.py` L253 | Corp-domain mismatch (400, if enabled) |
| 6 | Suppression / opt-out | `send_guard.py` L242 / `email_service.py` L271 | Suppressed target/CC (403) |
| 7 | SMTP config present | `email_service.py` L108/L126 | Unconfigured SMTP (400) |
| 8 | Daily + per-domain limits | `send_guard.py` L100 / `email_service.py` L277 | Over-quota (429) |
| 9 | Sending window | `send_guard.py` L140 / `scheduler_service.py` L271 | Outside 09:00–18:00 (defer) |
| 10 | Prior-step sent | `scheduler_service.py` L222 | Follow-up before predecessor (defer) |
| 11 | Evidence gate | `scheduler_service.py` L206 | Missing evidence/service (skip/block) |
| 12 | Quarantine (arming) | `scheduler_service.py` L154 | Arming a quarantined message |
| 13 | Quarantine (dispatch select) | `scheduler_service.py` L454/L466 | Selecting a quarantined message |
| 14 | Atomic claim (exactly-once) | `scheduler_service.py` L284 | Double dispatch |
| 15 | Test-send isolation | `send_guard.py` L106 / `outreach_tracking_service.py` L372 | Test sends pollute limits/stats |
| 16 | Open-redirect (click) | `tracking_routes.py` L62 | Non-http(s) redirect target |
| 17 | Quarantine release auth | `quarantine_service.py` L23 | Unauthorized release (401/403/503) |

---

## 8. State Model

### 8.1 `outreachmessages.status` — `models/outreach_message.py` L18 [S]
`draft` → `approved` (Step 1, manual) / `scheduled` (Steps 2/3, armed) → `sending` (claimed) → `sent` (terminal) / `failed` (terminal, no auto-retry). Only `scheduled` is auto-dispatched; `draft`/`approved` never are.

### 8.2 `outreachrecords` — `models/outreach_record.py` L12 [S]
Mirrors the message: `initialEmail` / `followUp1` / `followUp2` each `{status, sentAt, error, messageId, scheduledAt}`, plus `replyStatus`, `campaignStatus`, `isTestSend`. **The message is authoritative; the record is a projection** kept consistent by `record_email_dispatch` + the reconciler.

### 8.3 Two confirmed state-consistency gaps [S]+[R]
1. **Stale `scheduledAt` on demoted drafts:** `_pause_followups_for_recipient_change` (`outreach_service.py` L231) and the `_sync_followup_recipients` conflict branch (L119) set `status='draft'` but **never clear `scheduledAt`**. The reconciler clears records (L398) but **not messages**. → **20 live `draft` messages currently carry a `scheduledAt`** (DB audit D1). Not an auto-send risk today (dispatch selects only `status='scheduled'`), but latent.
2. **UI vs backend Step-3 default delay:** UI modal defaults `step3Days:6` (`CompanyDetail.jsx` L206); backend policy default is **7** (`outreach_tracking_service.py` L56). If a message has no explicit `delayDays`, the two disagree.

---

## 9. All Paths That Can Put Email Into the World

| # | Path | Trigger | Auth | Currently active? |
|---|---|---|---|---|
| 1 | `POST /outreach/{id}/send` | Operator UI / any HTTP client | **None** | **YES** |
| 2 | `scheduler_service.process_scheduled_emails` (60s loop) | Automatic | n/a | **NO (safe mode)** |
| 3 | `record_email_dispatch` → `activate_followups_on_send` | Arms the *next* step only | n/a | Yes (but only arms; doesn't send) |
| 4 | `POST /settings/test-smtp` | Operator | **None** | **YES** (sends a real test email when not sandbox) |

**The only fully-automatic send path is #2, and it is disabled right now.** Path #1 is live and unauthenticated.

---

## 10. Failure Handling & Recovery

- **SMTP failure** (`email_service.py` L350–368): message → `failed` with a sanitized error (password redacted, `sanitize_smtp_error` L22); dispatch recorded; exception re-raised.
- **Claimed but crashed** (`scheduler_service.py` `_release_or_fail` L231): a message stuck in `sending` is returned to `scheduled` (deferrable, e.g. 429) or marked `failed` (permanent). Guards against a message being orphaned in `sending`.
- **Rate-limit (429):** `_dispatch_scheduled_message` L302 treats 429 as deferrable → back to `scheduled` for retry on a later tick.
- **Send window:** outside 09:00–18:00 → `deferred` (no state change; retried next tick).
- **No retry on `failed`:** a `failed` message is never auto-retried; it requires a new manual send.

---

## 11. Confirmed Findings & Risks (send/schedule-specific)

| ID | Finding | Severity | Evidence | Confidence |
|---|---|---|---|---|
| **S1** | **Manual send route is unauthenticated** — anyone on `:5000` can send to any address | Critical | `outreach_routes.py` L290 | Confirmed |
| **S2** | **Scheduler is one `run.py` away from auto-send**; disabled only by the temp runner | High | `main.py` L31; process disabled [R] | Confirmed |
| **S3** | **20 `draft` messages carry stale `scheduledAt`** (demotion doesn't clear it) | Medium | `outreach_service.py` L131/L231; DB D1 | Confirmed |
| **S4** | **UI Step-3 default (6) ≠ backend policy default (7)** | Low | `CompanyDetail.jsx` L206 vs `outreach_tracking_service.py` L56 | Confirmed |
| **S5** | **`followup_config.py` defined but unused** — two sources of truth for delays | Low | `followup_config.py` L4 vs L56 | Confirmed |
| **S6** | **No rate-limiting / abuse protection** on the unauthenticated send & test-smtp routes (only per-day volume limits) | Medium | `outreach_routes.py` L290; `settings_routes.py` L135 | Confirmed |
| **S7** | **No per-user audit trail** — `record_email_dispatch` records *what* sent but not *who* triggered it (no user identity exists) | Medium | `outreach_tracking_service.py` L171 | Confirmed |
| **S8** | **In-process scheduler has no distributed lock** — safe only in a single-process deployment | Medium | `scheduler_service.py` L535 | Confirmed |
| **S9** | **`test-smtp` uses real SMTP** in the live config (sandbox flag not set) — a "test" email really is sent | Low | `.env` has no `ALLOW_ETHEREAL_TEST` [R]; `email_service.py` L102 | Confirmed |
| **S10** | **Invalid recipients** (`"Not publicly available"` ×6, empty ×8) — blocked by guard #4 but broken data | Medium | DB D2/D3 | Confirmed |

---

## 12. Safe Workarounds (no code change)

- **Send today:** use the UI **"Send Email Now"** button — manual, operator-initiated, guarded. Do **not** call the send endpoint from scripts.
- **Keep auto-send off:** continue running the backend via the **safe-mode runner**; do **not** start it with `run.py` (which enables the 60 s scheduler).
- **To arm a drip deliberately:** use **"Automate Drip Schedule"** in the UI — this is the intended, guarded arming path.
- **To clear the 20 stale `scheduledAt` drafts:** a one-off `$unset` of `scheduledAt` on `status='draft'` messages — **requires owner approval** (not done here).

---

## 13. Verification Steps for Recommended Fixes

- **S3 (stale `scheduledAt`):** after fixing the demotion paths, run
  `db.outreachmessages.count_documents({status:'draft', scheduledAt:{$ne:null}})` → expect **0**; add a unit test that demotes a follow-up and asserts `scheduledAt` is unset.
- **S1/S2 (auth):** `curl -X POST http://127.0.0.1:5000/api/outreach/{id}/send` without a token → expect **401/403**; with a valid token → 200.
- **S4 (delay default):** assert UI and backend resolve the same Step-3 default; add a test.
- **S9 (test-smtp):** with `ALLOW_ETHEREAL_TEST=true`, `POST /settings/test-smtp` should return `isTest:true` and send nothing real.

---

## 14. Checks NOT Completed (read-only)

- **Did not send any email** (manual or scheduled) — the send path was traced, not exercised.
- **Did not call `POST /settings/test-smtp`** (would send a real email).
- **Did not enable the scheduler** or start/stop any service.
- **Did not re-run the test suite** — the send/schedule guards are covered by `test_auto_followups.py`, `test_scheduling_policy.py`, `test_quarantine_guard.py`, `test_primary_email_and_sync.py` (per the earlier audit), but no fresh run was performed here.

---

## 15. No-Changes Confirmation

**No emails were sent. No messages were scheduled, activated, or dispatched. No database records, service states, files, or configuration were modified.** All analysis was read-only (source inspection + the earlier read-only DB audit). The scheduler remains **disabled**.
