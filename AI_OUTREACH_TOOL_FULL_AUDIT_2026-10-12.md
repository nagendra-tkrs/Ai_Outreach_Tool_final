# AI Client Outreach Tool — Full Audit Report

**Date:** 2026-10-12
**Auditor role:** Senior Software Architect / Full-Stack Engineer / QA / DB Auditor / Security Reviewer
**Scope:** Read-only investigation. No files, database records, service states, or email settings were modified.
**Project root:** `C:\Users\Hello\OneDrive\Desktop\new  and final ai outreach tool\Ai_Outreach_Tool`

> **Evidence legend used throughout**
> - **[R]** = Verified from the **live running runtime** (process/port/DB query)
> - **[S]** = Verified from **source code** (file + line)
> - **[H]** = **Historical** figure from a prior report/log (not guaranteed current)
> - **[I]** = **Inferred** but not directly verified

---

## 1. Executive Summary

The AI Client Outreach Tool is a two-tier application: a **React + Vite** frontend (`frontend/`) and a **Python FastAPI** backend (`backend/`) backed by **MongoDB** (`ai_client_outreach`). It automates B2B lead ingestion (Excel), web crawling, AI research (local Ollama), decision-maker discovery, personalized 3-step outreach generation, email dispatch (SMTP), drip scheduling, and tracking.

The application is **currently running in SAFE MODE**: the backend was started through a temporary runner (`safe_server_20261012.py`) that intercepts and disables the 60-second background scheduler. **No automatic scheduling or email dispatch is occurring right now.** This was verified at the process level.

The most significant confirmed finding is that **the backend has no authentication or authorization on any route** — including routes that send emails, delete all companies, and change SMTP settings. The only authenticated action is quarantine release (guarded by a shared `ADMIN_RELEASE_KEY` header, which **is** set in the live `.env`). Combined with the fact that the scheduler is one `run.py` invocation away from auto-dispatching due messages, this is the highest-risk area.

The previously reported **Step 1/2/3 synchronization defect has been substantially fixed in the current source**: the frontend now keeps per-step working copies with dirty flags and merges server refetches without clobbering unsaved edits, and the backend propagates Step-1 recipient/CC changes to eligible Step 2/3 messages. A **residual data-consistency gap remains**: 20 draft messages still carry a `scheduledAt` timestamp after being demoted back to `draft` (the demotion paths set `status='draft'` but never clear `scheduledAt`).

The **live database is being actively modified** during this audit (a new 21-company import appeared mid-audit), so all counts are a moving target and are reported as "current as of audit time."

---

## 2. Verified Current Runtime Status

| Service | Status | Evidence |
|---|---|---|
| **MongoDB** | Running — pid 12177, port **27017**, dbPath **`C:\data\db`**, log `...\Temp\opencode\mongod_datadb.log` | [R] process command line |
| **Backend (FastAPI)** | Running on **http://127.0.0.1:5000** via **SAFE MODE** runner `...\Temp\opencode\safe_server_20261012.py` (pids 13016 + 13048). Health `GET /api/health` → 200 `{"success":true,...}`. | [R] ports + process cmdline |
| **Frontend (Vite)** | Running on **http://localhost:5173** (binds IPv6 `::1`; `localhost` works, `127.0.0.1` does not). node pids 10652/12736. | [R] |
| **Ollama** | Running — pid 10200, port **11434**. | [R] |
| **Scheduler** | **DISABLED** — the safe-mode runner monkeypatches `app.main.start_scheduler` to a no-op before `uvicorn.run`. Backend log confirms: `[safe-mode] start_scheduler() call intercepted and DISABLED`. | [R] |

**Two backend processes** (13016, 13048) are both running the safe-mode runner; only **13048** is bound to port 5000. 13016 is a duplicate/stale process (not serving). [R]

**Running code == on-disk source:** backend `app/` files were last modified **2026-10-10 05:14 AM**; the backend server started **2026-10-12 10:31 AM** — i.e. *after* the source was final. Therefore the running backend contains exactly the code on disk (including the Step 1/2/3 sync implementation). [R]+[S]

### Git state
- Branch: `main`; HEAD `5442325d6e7defe64e222efc6a4b3088b49f1d7f` ("Fix SMTP settings, email service resolution, and complete test suite"). Only 2 commits total. [R]
- **32 modified tracked files** (+3180 / −703) and **16 untracked files** (new modules: `followup_config.py`, `suppression.py`, `quarantine_service.py`, `send_guard.py`, 11 test files, `QuarantineReleaseModal.jsx`, `frontend/src/utils/`). [R]
- The working tree carries the entire follow-up-automation / quarantine-guard / test-isolation work as **uncommitted** changes. [R]

---

## 3. Architecture & Feature Inventory

### 3.1 Stack
- **Frontend:** React 19, Vite 8, Tailwind CSS 4, axios, react-router-dom 7. Entry `frontend/src/main.jsx` → `App.jsx`. [S]
- **Backend:** Python 3.12+, FastAPI, uvicorn, Motor (async MongoDB), pydantic, aiosmtplib, openpyxl, httpx, beautifulsoup4, dnspython. [S]
- **DB:** MongoDB 6.0.19, database `ai_client_outreach` (connection string from `MONGODB_URI`, default `mongodb://127.0.0.1:27017/ai_client_outreach`). [S]
- **AI:** local **Ollama** (`http://127.0.0.1:11434`); default model `qwen2.5-coder:7b-instruct`. [S]
- **Search:** DuckDuckGo HTML (free), public-web fallback. [S]

### 3.2 Routes (frontend `App.jsx` L13–19) [S]
| Path | Component |
|---|---|
| `/` | Dashboard |
| `/import` | ExcelImport |
| `/companies` | CompanyList |
| `/companies/:companyId` | CompanyDetail |
| `/outbox` | Outbox |
| `/settings` | Settings |

### 3.3 Backend API surface (all under `/api`) [S]
| Area | Routes | File |
|---|---|---|
| Health | `GET /health` | `app/routers/health.py` L6 |
| Companies | `GET /companies`, `GET /companies/{id}`, `DELETE /companies/{id}`, `DELETE /companies` | `company_routes.py` L7/18/33/39 |
| Crawl | `POST /companies/{id}/crawl`, `GET .../crawl`, `GET .../pages`, `GET .../pages/{id}` | `crawl_routes.py` L12/19/26/38 |
| Research | `POST .../research`, `GET .../research` | `research_routes.py` L10/29 |
| Contacts | `GET/POST .../contacts`, `POST .../contacts/discover`, `PUT/DELETE .../contacts/{id}`, `POST .../contacts/{id}/verify`, `GET .../contacts/pattern`, `POST .../contacts/apply-pattern` | `contact_routes.py` L21/30/47/57/74/110/122/130 |
| Outreach | `POST .../outreach/generate`, `POST .../outreach/schedule`, `GET .../outreach`, `PUT /outreach/{id}`, `POST /outreach/{id}/regenerate`, `POST /outreach/{id}/send`, `DELETE /outreach/{id}`, `POST /outreach/bulk-generate` | `outreach_routes.py` L38/49/88/230/274/290/284/218 |
| Tracking | `GET /outreach/records`, `GET /outreach/records/{id}`, `PATCH /outreach/records/{id}/reply`, `GET /outreach/stats`, `GET /outreach/export`, `GET /outreach/all` | `outreach_routes.py` L98/125/156/171/177/199 |
| Import | `GET /import/template`, `POST /import/excel`, `GET /import/{id}`, `GET /import/{id}/invalid-report`, `POST /import/{id}/confirm` | `import_routes.py` L19/30/85/91/104 |
| Settings | `GET/POST /settings`, `POST /settings/test-smtp` | `settings_routes.py` L17/55/135 |
| Quarantine | `POST /outreach/quarantine/reconcile-audit-logs`, `POST /outreach/{id}/release-quarantine` | `outreach_routes.py` L311/318 |
| Tracking pixels | `GET /track/open/{id}`, `GET /track/click/{id}`, `GET /track/unsubscribe/{id}` | `tracking_routes.py` L16/45/73 |

### 3.4 MongoDB collections in use [S]
`companies`, `contacts`, `outreachmessages`, `outreachrecords`, `crawledpages`, `companyresearches`, `researchjobs`, `importbatches`, `settings`, `suppressions`, `quarantine_audit_logs`.
**Not present anywhere in `app/`:** `smtpsettings`, `users`, `sessions` — i.e. **no user/session store exists**. [S]

### 3.5 Feature → implementation map
| Feature | Frontend | Backend service/route | DB collections | Status |
|---|---|---|---|---|
| Excel ingestion | `ExcelImport.jsx` | `excel_service.py`, `import_service.py`, `import_routes.py` | `importbatches`, `companies` | Implemented |
| Web crawl | `CompanyDetail.jsx` crawl tab | `crawler/orchestrator.py`, `crawl_routes.py` | `crawledpages`, `researchjobs`, `companies` | Implemented |
| AI research | `CompanyDetail.jsx` research tab | `research_service.py`, `ai_service.py` | `companyresearches` | Implemented |
| Decision-maker discovery | `CompanyDetail.jsx` contacts tab | `contact_service.py`, `decision_maker_engine.py`, `web_search_service.py` | `contacts` | Implemented |
| 3-step outreach generation | `CompanyDetail.jsx` outreach tab | `outreach_service.py:generate_outreach_sequence` | `outreachmessages` | Implemented |
| Step 1/2/3 sync | `outreachEditor.js`, `CompanyDetail.jsx` | `outreach_service.py:_sync_followup_recipients`, `_sync_followup_cc` | `outreachmessages` | **Fixed (residual gap §4/§6)** |
| Manual send | `handleSendEmail` | `email_service.py:send_outreach_email` | `outreachmessages` | Implemented |
| Drip scheduling | `handleActivateSchedule` | `scheduler_service.py:schedule_sequence_steps` | `outreachmessages` | Implemented |
| Auto dispatch (60s) | — | `scheduler_service.py:_scheduler_loop` | `outreachmessages` | **Disabled (safe mode)** |
| Follow-up activation on send | — | `outreach_tracking_service.py:activate_followups_on_send` | `outreachmessages`, `outreachrecords` | Implemented |
| Reply → cancel follow-ups | `Outbox.jsx` | `update_reply_status`, `cancel_pending_followups` | `outreachmessages`, `outreachrecords` | Implemented |
| Quarantine & release | `QuarantineReleaseModal.jsx` | `quarantine_service.py` | `outreachmessages`, `quarantine_audit_logs` | Implemented |
| Tracking (open/click/unsubscribe) | `Outbox.jsx` | `tracking_routes.py` | `outreachmessages`, `suppressions` | Implemented |
| Suppression / unsubscribe | — | `send_guard.py:assert_not_suppressed` | `suppressions` | Implemented |
| Settings & SMTP | `Settings.jsx` | `settings_routes.py`, `email_service.py:get_smtp_config` | `settings` | Implemented |
| **Authentication / sessions** | — | — | — | **NOT IMPLEMENTED** |

---

## 4. Critical Investigation — Step 1 / 2 / Step 3 Synchronization

### 4.1 Contract: who inherits what [S]
- **Recipient:** Step 2/3 do **not** hard-code a recipient. On generation they inherit the contact's email (`outreach_service.py` L483–486). On a **Step-1 recipient edit**, the backend propagates the new recipient to eligible unsent Step 2/3 via `_sync_followup_recipients` (`outreach_service.py` L98). A follow-up that already holds a **different valid** address is **never overwritten** — it is flagged `requiresReview` / `recipientConflict` and, if armed, demoted to `draft` (L119–140).
- **CC:** Step-1 CC edits are mirrored onto eligible Step 2/3 via `_sync_followup_cc` (L207). **BCC is never synchronized** (documented, L172).
- **Content (subject/body):** Each step stores its **own** subject/bodies. Edits to one step never rewrite another step's content (enforced by the per-message `update_one` and the whitelist in `update_outreach_message` L726–741). Regeneration preserves manually-edited drafts (`isManuallyEdited`, L455–462).
- **Authoritative state:** the `outreachmessages` document is the single source of truth for status/scheduledAt; `outreachrecords` mirrors it (`record_email_dispatch`, `outreach_tracking_service.py` L171).

### 4.2 Frontend state model (current code) [S]
`CompanyDetail.jsx`:
- Per-step working copies: `draftsByStep` + `dirtySteps` (L212–213), mirrored in refs (`dirtyStepsRef`, `selectedStepRef`, L216–217) so async refetches never read stale state.
- `updateEditingMessage` (L226) applies a local edit, stores the draft, and marks the step dirty.
- `handleStepSelect` (L519) resolves the step's message via `resolveStepMessage` — **draft wins over server** (`outreachEditor.js` L42).
- `fetchOutreach` (L300) merges server data with `mergeServerMessages`, which **skips any dirty step** (`outreachEditor.js` L51), and only replaces the visible editor when the current step is clean.
- `handleSaveDraft` (L569) builds the payload, `PUT /outreach/{id}`, updates state, then **conditionally refetches** via `shouldRefetchAfterSave` (L630) so a successful Step-1 recipient/CC sync refreshes Steps 2/3.
- `getActiveStepMessage` (L189) re-resolves a stale binding so the sent/locked banner always reflects the selected step.

**Conclusion [S]:** The originally reported symptoms — *editing Step 1 does not update Step 2/3*, *switching steps shows old Step-1 content*, *unsaved edits lost* — are **addressed** by the current per-step-draft + merge-on-refetch + conditional-refetch design, **provided the running backend contains this code** (it does — see §2).

### 4.3 Confirmed residual defect — stale `scheduledAt` on demoted follow-ups [S]+[R]
Two backend demotion paths set `status='draft'` but **never clear `scheduledAt`**:
- `_pause_followups_for_recipient_change` (`outreach_service.py` L231–277) — sets `status='draft'`, `requiresReview`, `previousRecipient`; leaves `scheduledAt`.
- `_sync_followup_recipients` conflict branch (`outreach_service.py` L119–140) — sets `status='draft'` + conflict flags; leaves `scheduledAt`.

The record reconciler clears stale `scheduledAt` on **records** (`scheduler_service.py` L398–402) but **not on messages**. This is why the live DB contains **20 `draft` messages that still carry a `scheduledAt`** (§5). Not an auto-send risk today (dispatch selects only `status='scheduled'`), but a latent consistency gap.

### 4.4 Race conditions [S]
- The save flow is a single `PUT` followed by a conditional `GET` refetch; the refetch uses `mergeServerMessages`, so a concurrent edit to a *dirty* step is preserved. A save to a *clean* step after a concurrent server change could in principle be overwritten by the refetch, but the dirty-flag merge makes this unlikely in practice. **[I]**
- The axios interceptor unwraps `response.data` (`api.js` L8); `handleSaveDraft` reads `res?.recipientSync ?? res?.data?.recipientSync` (L613) — consistent. The bug documented in `outreachEditor.js` L62–66 (reading `body.data.recipientSync`) is explicitly guarded.

---

## 5. MongoDB & Data Integrity (read-only)

> **The live DB is being actively written during this audit.** A new import batch (`TKSR_Potential_Clients_20_Companies.xlsx`, 21 companies) appeared mid-audit (05:41), taking companies 33 → 54. Counts below are **current as of audit time** and will keep changing while the app is used.

### 5.1 Current counts [R]
| Collection | Count |
|---|---|
| companies | **54** |
| contacts | **76** |
| outreachmessages | **72** (58 draft, 14 sent) |
| outreachrecords | **13** |
| crawledpages | **1738** |
| companyresearches | 56 |
| researchjobs | 45 |
| importbatches | **17** |
| settings | 1 |
| suppressions | 0 |
| quarantine_audit_logs | 0 |

**Historical figures (not current):** the task brief cited 121 companies / 72 messages / 24 quarantined / 13 records / 43 contacts / 944 pages / 17 batches and an earlier "33 companies". Those were accurate at earlier points in time but are **superseded** by the current 54/76/72/13/1738. The mid-audit import proves the DB is a moving target. [H]+[R]

### 5.2 Confirmed data-integrity findings [R]
| # | Finding | Count | Severity |
|---|---|---|---|
| D1 | **Draft messages carrying `scheduledAt`** (status/scheduledAt inconsistency; see §4.3) | **20** | Medium |
| D2 | **Messages with literal `"Not publicly available"` recipient** (invalid address stored as recipient) | **6** | Medium |
| D3 | **Messages with empty `recipientEmail`** | **8** | Medium |
| D4 | **Duplicate company** — `D4 ReadOnly Corp` ×2 (same `normalizedWebsite` `d4readonly.example`) | 1 group | Low |
| D5 | Duplicate "contacts" are only placeholder strings (`"not publicly available"` ×13, `"not publicly verified"` ×2) — **not real duplicate people** | — | Informational |
| D6 | **0 `suppressions` and 0 `quarantine_audit_logs`** — no unsubscribe/suppression and no quarantine release has ever been audited | 0 | Informational |
| D7 | Quarantine batches present: `quarantine-20261009` (20), `quarantine-import-6ac8770e…` (2), `quarantine-import-6acc7309…` (2, from the new import) | 24 total | By design |
| D8 | **0 `scheduled` messages and 0 overdue** — nothing will auto-send even if the scheduler is enabled | 0 | Good |
| D9 | 0 orphaned `outreachrecords` (all `companyId` exist); 0 duplicate (company+recipient) records | 0 | Good |
| D10 | All 13 records: `initialEmail.status=SENT`, `replyStatus=NO_REPLY`, `isTestSend=False`; 12 `followUp1=PENDING`, 1 `SENT` | — | Consistent |

**Note on D2/D3:** these invalid/empty recipients are **blocked from sending** by `send_guard.validate_recipient_email` (`send_guard.py` L93) and `send_outreach_email` (L256), so they are **not** an accidental-send risk — but they are broken data that will silently fail if an operator ever arms them. [S]+[R]

### 5.3 Import-batch consistency [R]
- 3 `completed` batches match their `importedRows` to actual company counts (30, 21, and the earlier 30). 
- The 14 `uploaded`-status batches (`flex.xlsx`, `badurl.xlsx`, `noev.xlsx`, `dups.xlsx`, `exact.xlsx` — residue from earlier testing) have `importedRows=None` and `actualCompanies=0`; they were **uploaded but never confirmed**, so they created no companies. This is expected behavior for the upload→confirm workflow, but the rows are effectively orphaned audit records. [R]

---

## 6. Scheduler & Email Safety

### 6.1 Lifecycle [S]
`draft` → (operator `POST /outreach/schedule` **or** automatic on Step-1 send) → `approved` (Step 1, delay 0, manual) / `scheduled` (Steps 2/3, delay>0) → `sending` (atomic claim) → `sent`/`failed`. Only `scheduled` messages are auto-dispatched (`scheduler_service.py` L454–461). `draft` is never dispatched.

### 6.2 Guards (defense in depth) [S]
- **Duplicate-send:** `send_outreach_email` rejects `status=='sent'` with HTTP 409 (`email_service.py` L228).
- **Quarantine hard-stop** at three boundaries: arming (`schedule_sequence_steps` L154), dispatch selection (`process_scheduled_emails` L454), and the **final send boundary** (`send_outreach_email` L239). `is_message_quarantined` (`send_guard.py` L288) treats `quarantined=True` **or** `quarantine.active=True` as quarantined; a missing `quarantined` field (legacy) is eligible.
- **Missing-recipient protection:** `validate_recipient_email` blocks empty/invalid recipients (`send_guard.py` L93; `send_outreach_email` L256).
- **Evidence gate:** `_company_evidence_gate` (`scheduler_service.py` L206) blocks dispatch when evidence/service missing — the record is marked `BLOCKED`, never a fabricated fallback.
- **Sending window:** `is_within_sending_window` (L140) defers outside 09:00–18:00.
- **Daily + per-domain limits:** `assert_send_limits` (L100), defaults 50/day and 5/domain/day.
- **Suppression:** `assert_not_suppressed` (L242) blocks suppressed targets and CCs.
- **Prior-step gate:** `_prior_step_sent` (L222) prevents a follow-up before its predecessor is sent.
- **Idempotent atomic claim:** `scheduled → sending` via `find_one_and_update` (L284) — two workers cannot dispatch the same message.
- **Test-send isolation:** `isTestSend` sends never consume limits or stats (`get_outreach_stats` L372 uses `real_only`).

### 6.3 Can a draft be accidentally reactivated? [S]
No. The reconciler `process_automated_follow_ups` explicitly **never activates a draft** — it only clears the record's stale `scheduledAt` (L398–402). Arming is exclusively via `schedule_sequence_steps` (operator) or `activate_followups_on_send` (on a real Step-1/2 send).

### 6.4 Can a scheduled follow-up send with a missing/stale recipient? [S]
No — dispatch selection requires `status='scheduled'` and the send boundary re-validates the recipient. A scheduled message with an invalid recipient would fail at `send_outreach_email` L256 (400) and be marked `failed`.

### 6.5 All paths that can auto-send [S]
1. `POST /outreach/{id}/send` (manual, `outreach_routes.py` L290) — **unauthenticated**.
2. `scheduler_service.process_scheduled_emails` → `_dispatch_scheduled_message` (the 60s loop) — **currently disabled**.
3. `record_email_dispatch` is called only after a real send; it arms follow-ups for the *next* send but does not itself send.

**The scheduler is the only fully-automatic path and it is disabled right now.** The manual send route is one unauthenticated HTTP call away from sending to any address. [S]+[R]

---

## 7. Excel Lead Ingestion

### 7.1 Supported contract [S] (`utils/validators.py`, `excel_service.py`)
- **Required columns (4):** `Company Name`, `Website`, `Evidence`, `Recommended Service` (`REQUIRED_COLUMNS` L4).
- **Optional columns (8):** `Industry`, `Country`, `Contact Name`, `Contact Email`, `Revenue`, `Employee Count`, `Notes`, `Source` (`OPTIONAL_COLUMNS` L20) — the 12-column template (`TEMPLATE_HEADERS` L35).
- **Header aliases** (`HEADER_ALIASES` L36): e.g. `company`→Company Name, `url`→Website, `reason`/`trigger`→Evidence, `service`/`tksr service`→Recommended Service, `email`/`contactmail`→Contact Email, `headcount`→Employee Count.
- **Accepted service values** (`VALID_RECOMMENDED_SERVICES` L11): the 6 canonical TKSR services; synonyms resolved via `SERVICE_SYNONYMS` L80 / `_SERVICE_KEYWORD_RULES` L91 (`resolve_service` L106).
- **Row validation** (`validate_row` L190): company name required; website required + must parse to a hostname containing `.` (`is_valid_url` L162); evidence required (non-empty); service required + must be in the accepted set.
- **Duplicates** (`excel_service.py` L254–272): in-file by name/website → `duplicate_in_file`; already-in-DB → `existing_in_db`.
- **Revenue / Employee Count:** stored as **raw strings, no parsing/validation** (free-text). [S]

### 7.2 Authoritative vs AI-overwritten [S]
`import_service.confirm_import` (L36) inserts rows **as-is** from the parsed Excel — it does **not** call AI or overwrite `evidence`/`recommendedService`/`companyName`/`website`. Imported values are authoritative at import time. (AI research may later enrich the company, but that is a separate step.) [S]

### 7.3 Import workflow [S]
`POST /import/excel` (validates extension `.xlsx/.xls/.csv`, ≤10 MB → 413; creates an `importbatches` doc, `import_routes.py` L30) → operator reviews → `POST /import/{id}/confirm` (`confirm_import`) inserts companies. Partial import is supported (valid rows import; invalid rows downloadable via `invalid-report`). [S]

### 7.4 Confirmed gaps [S]
- **No `Revenue`/`Employee Count` parsing** — free-text only; no numeric validation.
- **No email-format validation on `Contact Email`** at import (only `Website` URL is validated). A malformed contact email would be stored and later rejected at send time.
- **Uploaded-but-unconfirmed batches are orphaned** (§5.3) — they persist as `uploaded` rows with no companies.
- The earlier **test-isolation incident** (a `delete_many` in `test_excel_import_hardening.py` not fully scoped to its own fixture) was a *test* defect, not a production import defect; it does not affect live data. [S]

---

## 8. AI Generation & Ollama

### 8.1 Configuration [S]
- `ai_service.get_ai_config` (L334) reads provider/model from env + `settings.global_settings.ai`. `can_use_ai` (L406) is true only for `provider=='ollama'`. `call_ai` (L411) → `call_ollama` (L358) POSTs to `/api/chat` with `format:json`, default model **`qwen2.5-coder:7b-instruct`**, timeout `OLLAMA_REQUEST_TIMEOUT` (default 180000 ms).
- `decision_maker_engine.py` L24 hardcodes **`qwen2.5:1.5b`**.
- `company_researches.py` L25 defaults `aiModel="llama3"`.

> **Confirmed inconsistency [S]:** three different model names are used in different code paths (`qwen2.5-coder:7b-instruct` vs `qwen2.5:1.5b` vs `llama3`). If the local Ollama server does not have all three loaded, the decision-maker engine or research path will fail with a "model not found" error. This is a **probable runtime defect**.

### 8.2 Prompting & anti-hallucination [S]
- Prompts are **inline strings** (no external template files) — `generate_outreach_sequence` L333–410 and `regenerate_outreach_message` L816–835. The system prompt enforces evidence-only personalization, exact service name, no signature, and strict JSON.
- `sanitize_evidence` (L107) strips/truncates evidence to 320 chars and rejects placeholders ("None"/"N/A"/"-").
- `apply_tksr_signature` (L146) strips any LLM sign-off and appends the canonical TKSR signature.
- **Fallback ladder:** on any Ollama failure, callers fall back to deterministic `generate_fallback_outreach` / `generate_fallback_research` (`ai_service.py` L422/481) — content is generated from evidence+service only, never fabricated.

### 8.3 Output validation [S]
- Deterministic defaults (`build_primary_email` L181, `build_followup_email` L270) guarantee complete, signed copy when the LLM omits/malforms content.
- `check_contact_and_greeting_consistency` (`send_guard.py` L383) flags greeting discontinuities and suspicious non-person names.
- **No explicit length enforcement** on LLM output beyond prompt instructions ("<130 words"); overly long content is not programmatically truncated. [S]

### 8.4 Is AI content validated before save/send? [S]
Partially. There is evidence/service validation and deterministic fallback, but **no hard schema/length validation** of the LLM JSON beyond "did it return a sequence array" (`outreach_service.py` L418). Malformed-but-present content is accepted and signed. [S]

---

## 9. Authentication, Security & Privacy

### 9.1 No authentication anywhere [S] — **CRITICAL**
- **No router uses `Depends(auth)` / OAuth / API-key / session.** The subagent confirmed "No authentication on any router." The only `Depends` in the codebase is `verify_admin_release_key` on the two quarantine routes.
- There is **no `users`/`sessions` collection** and no login/logout/Google auth. `Layout.jsx` has no auth gate; all pages are public.
- **Consequences:** anyone who can reach port 5000 can:
  - **Send email** to any address (`POST /outreach/{id}/send`, `outreach_routes.py` L290).
  - **Delete all companies** (`DELETE /companies`, `company_routes.py` L39`) or any company (L33).
  - **Change SMTP settings** and **send test emails** (`POST /settings`, `/settings/test-smtp`, `settings_routes.py` L55/135).
  - Trigger crawls/research (cost, external HTTP).
- The frontend is served on `localhost` and the backend binds `127.0.0.1` by default (`run.py` L11), which limits exposure to the local machine — but any local process/user, or any port-forward, is exposed. [S]

### 9.2 Quarantine release auth [S]
- `verify_admin_release_key` (`quarantine_service.py` L23) compares the `X-Admin-Key` header to the server-side `ADMIN_RELEASE_KEY` env var using `hmac.compare_digest`, **fails closed** if unset, and never logs the key. This is the **only** authenticated action. It is well-implemented.
- **`ADMIN_RELEASE_KEY` IS set** in the live `.env` (verified: present and non-empty; value never printed). So quarantine release is **enabled** with a **single shared static key** — no rotation, no per-user identity, no audit of *who* holds it. [R]

### 9.3 Secret handling [S]
- SMTP password is stored in `settings.smtp.pass`; `get_settings` returns it **masked** (`mask_secret`, `settings_routes.py` L9/L44). `send_outreach_email` never logs the password; `sanitize_smtp_error` (`email_service.py` L22) redacts it from SMTP errors.
- `send_test_email` supports an Ethereal sandbox behind `ALLOW_ETHEREAL_TEST`/`ENABLE_ETHEREAL` (`email_service.py` L102). The test suite sets `ALLOW_ETHEREAL_TEST=true` (conftest), so **tests never touch real SMTP**.
- The frontend holds the admin key in memory only and zeroes it on close/submit (`QuarantineReleaseModal.jsx` L45/55/105). [S]

### 9.4 Input validation / injection [S]
- ObjectId validation (`is_valid_object_id`, `bson_utils.py` L4) on path params.
- Sort-field allowlist on tracking records (`outreach_tracking_service.py` L318) — no arbitrary field injection.
- **Open-redirect guard** on click tracking (`tracking_routes.py` L62–69`) — only http/https with a netloc.
- Search queries use regex-escaped user input in tracking search (`outreach_tracking_service.py` L305).
- **No rate-limiting** on the unauthenticated send/delete/settings routes (only send-volume limits per day, not per-route abuse). [S]

### 9.5 CORS [S]
`main.py` L45–60: `allow_origins` = `[FRONTEND_URL, http://localhost:5173, http://127.0.0.1:5173, http://localhost:3000]`, `allow_credentials=True`. Not a wildcard, but permless given there is no auth. [S]

### 9.6 File upload [S]
`POST /import/excel` enforces an extension whitelist (`.xlsx/.xls/.csv`), non-empty, and ≤10 MB (413). Parsed via openpyxl/xlrd. Reasonable. [S]

### 9.7 Privacy [R]
- The DB stores personal data (names, emails, titles, LinkedIn URLs, evidence). `suppressions` is empty (no unsubscribes processed yet). No personal data was printed in this report (emails masked). [R]

---

## 10. Testing & Coverage

### 10.1 Inventory [S]
- **Backend pytest suite** (`backend/tests/`): 20 files. Test counts (from fixtures/functions): `test_phase2_email_discovery` (56), `test_hardening_regression` (28), `test_excel_import_hardening` (18), `test_quarantine_release` (16), `test_phase1_official_crawl` (13), `test_phase3_end_to_end` (12), `test_auto_followups` (10), `test_primary_email_and_sync` (10), `test_evidence_integrity` (10), `test_email_discovery_fixes` (10), `test_future_import_quarantine` (9), `test_quarantined_draft_edit` (9), `test_api_integration` (6), `test_decision_maker_pipeline` (5), `test_phase1_excel_foundation` (8), `test_phase2_outreach_architecture` (9), `test_smtp_settings_verification` (8), `test_quarantine_guard` (7), `test_scheduling_policy` (5+), `test_new_company_import_e2e` (1). **Total ≈ 250+ tests.**
- **Frontend `node --test`** (`frontend/src/utils/`): `outreachEditor.test.js` (25 tests) + `outreachStats.test.js` (6 tests) ≈ **31 tests**.

### 10.2 Isolation & side effects [S]
- `tests/conftest.py` patches `app.config.database.DB_NAME` → `ai_client_outreach_test_suite` (L23) and drops that DB at session start/end (L40–46). Autouse `setup_test_environment` (L49) sets `ALLOW_ETHEREAL_TEST=true`, raises send limits, widens the send window, and disables domain-match enforcement. **No test writes to the production `ai_client_outreach` DB.**
- All SMTP is patched (`aiosmtplib.send` → `AsyncMock`); Ollama/AI is patched where needed; DDG/web search is mocked. Tests require a **real MongoDB at 127.0.0.1:27017** but use only the test DB.
- **Residual risk [S]:** the earlier `test_excel_import_hardening.py` `delete_many` scoping incident shows test-isolation is mostly good but not bulletproof; a future fixture could leak. Also, because the patch is a module-level `DB_NAME` swap, any code path that captures the DB name *before* conftest runs (e.g. an already-imported `db` global) could bypass it. [I]

### 10.3 Coverage gaps [S]
- **No test for authentication** (there is no auth to test).
- **No test for the Excel `Contact Email` format** (only website URL is validated).
- **No test for the stale-`scheduledAt`-on-demotion** behavior (§4.3) — this is the exact regression that produced D1.
- **No test asserting the three Ollama model names are consistent** (§8.1).
- Frontend tests cover the editor helpers well (25 tests) but there are **no component/DOM tests** for `CompanyDetail`/`Outbox`/`Settings`.

### 10.4 Verifiable results
- A prior full backend run was reported as **251 passed** (historical, from the task's earlier session) — **not re-verified in this read-only audit** (the suite was not re-run). [H]
- `backend/phase5_benchmark_results.json` is a decision-maker-discovery benchmark (many `NOT_FOUND` emails), **not** a unit-test result file. [R]

---

## 11. Deployment & Environment Readiness

### 11.1 Configuration [S]
- `backend/.env.example` documents: `NODE_ENV`, `PORT`, `MONGODB_URI`, `FRONTEND_URL`, crawler limits, search (DDG), AI (Ollama), research timeouts, and `ADMIN_RELEASE_KEY`. The live `.env` contains exactly: `NODE_ENV`, `PORT`, `MONGODB_URI`, `FRONTEND_URL`, `ADMIN_RELEASE_KEY` (all values redacted; `ADMIN_RELEASE_KEY` is set). [R]
- `run.py` defaults to `127.0.0.1:5000` (localhost-only by design). [S]
- Frontend `vite.config.js` proxies `/api` → `http://localhost:5000`. [S]

### 11.2 What is missing / unverified [S]
- **No production deployment config** (no Dockerfile, no Vercel config, no CI). README documents local dev only.
- **No `users`/sessions** → no multi-user or audit trail of *who* sent what.
- **No `smtpsettings` collection** — SMTP lives only in the single `settings.global_settings` doc.
- **Scheduler deployment:** the 60s loop runs **in-process** (`asyncio.create_task` in `start_scheduler`). It does not survive a multi-worker deployment and has no distributed lock — in a multi-process deployment, duplicate sends are only prevented per-process by the atomic claim. [S]
- **DB backups / persistence:** none configured; the DB is a single local `mongod` with no replica set (note: `quarantine_service` correctly detects standalone and uses the non-transactional audit path). [R]

### 11.3 Production vs dev [S]
- `ALLOW_ETHEREAL_TEST` gates the sandbox SMTP; the live `.env` does **not** set it (not in the key list), so the running backend uses **real SMTP** config from settings. [R]
- `ENFORCE_RECIPIENT_DOMAIN_MATCH` defaults to `false`. [S]

---

## 12. Architecture & Maintainability

- **Large, tightly-coupled files [S]:** `frontend/src/pages/CompanyDetail.jsx` (~2600 lines, 4 tabs + editor + modals in one component); `backend/app/services/decision_maker_engine.py` (**3269 lines**); `contact_service.py` (1324); `web_search_service.py` (693); `scheduler_service.py` (545). High cognitive load; hard to test in isolation.
- **Duplicated logic [S]:** recipient/CC normalization appears in both `outreach_service.py` (`_normalize_cc_list` L166) and `CompanyDetail.jsx` (`handleAddCcEmail` L529); email validation regex duplicated in `send_guard.py` L32, `outreachEditor.js` L140, and `email_validation_service.py`.
- **State-management complexity [S]:** the outreach editor's per-step draft + dirty + refetch-by-design is correct but subtle; it is documented in `outreachEditor.js` comments. A regression here is easy (see §4.3).
- **DB consistency strategy [S]:** `outreachmessages` is authoritative for status/schedule; `outreachrecords` is a mirrored projection kept consistent by `record_email_dispatch` + the reconciler. This is sound in principle but has the stale-`scheduledAt` gap (§4.3).
- **Dead / obsolete code [S]:** `backend/src/` (the entire legacy Node/Express backend) and `backend_node_backup/` coexist with the FastAPI backend; `backend/package.json` + `backend/package-lock.json` + `backend/server.log`/`server.err.log` are leftovers. `followup_config.py` (env-based 3/7 defaults) is **defined but unused** — `outreach_tracking_service.py` hardcodes `DEFAULT_FOLLOWUP_DELAYS = {2:3, 3:7}` (L56) instead of importing it.
- **Observability [S]:** logging is `logging.info/warning/error` with no structured logs, no request IDs, no metrics. The scheduler logs dispatch activity.
- **Dependency risks [S]:** `requirements.txt` pins nothing (no versions); `ddgs`/`duckduckgo` search lib used in `decision_maker_engine.py` is not clearly declared. [S]

---

## 13. Evidence-Based Risk Register

| ID | Issue | Severity | Category | User impact | Root cause | Evidence | Confidence | Fix | Reg test | Fix risk | Deps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **R1** | **No authentication/authorization on any route** | **Critical** | Security | Anyone reaching :5000 can send email, delete all companies, change SMTP, trigger crawls | No auth layer exists; no users/sessions | `outreach_routes.py` L290; `company_routes.py` L39; `settings_routes.py` L55; subagent router scan; no `users`/`sessions` collections | **Confirmed** | Add authn + authz on all mutating routes | Yes | Medium (must not break local dev) | Auth provider/session store |
| **R2** | **Scheduler is one `run.py` away from auto-send; manual send is unauthenticated** | **High** | Email safety | If scheduler enabled + a due `scheduled` message exists, email goes out automatically; anyone can POST a send | `start_scheduler(60)` on startup; `POST /outreach/{id}/send` public | `main.py` L31; `scheduler_service.py` L440; `outreach_routes.py` L290 | **Confirmed** | Keep scheduler disabled until auth exists; gate send behind auth | Yes | Low | R1 |
| **R3** | **20 draft messages carry stale `scheduledAt`** | Medium | Data integrity | Latent: if any future selection uses `scheduledAt` alone, a "draft" could fire; confusing UI | Demotion paths set `status='draft'` without clearing `scheduledAt`; reconciler clears records not messages | `outreach_service.py` L131/L242; `scheduler_service.py` L398; DB audit D1 | **Confirmed** | Clear `scheduledAt` in both demotion paths; add message-level reconciler | Yes (this is the §4.3 regression) | Low | None |
| **R4** | **Invalid recipients on messages** (`"Not publicly available"` ×6, empty ×8) | Medium | Data integrity | Those steps can never send; operator confusion | Contact discovery stores placeholders; import doesn't validate contact email | DB audit D2/D3; `send_guard.py` L93 | **Confirmed** | Block placeholder recipients at contact/import time; add a cleanup job | Yes | Low | None |
| **R5** | **Inconsistent Ollama model names** (`qwen2.5-coder:7b-instruct` vs `qwen2.5:1.5b` vs `llama3`) | Medium | AI reliability | Decision-maker engine / research may fail with "model not found" | Three hardcoded defaults | `ai_service.py` L33/358; `decision_maker_engine.py` L24; `company_researches.py` L25 | **Confirmed** | Centralize model name in one config | Yes | Low | None |
| **R6** | **Duplicate company** `D4 ReadOnly Corp` ×2 | Low | Data integrity | Double-counting, confusing UI | Residue from earlier testing; no unique constraint | DB audit D4 | **Confirmed** | Add partial unique index on normalizedWebsite; dedupe existing | Yes | Low | None |
| **R7** | **`ADMIN_RELEASE_KEY` is a single static shared key** (no rotation/per-user) | Medium | Security | Quarantine release is authenticated but not auditable per-user | Design uses one env key | `quarantine_service.py` L23; `.env` has it set | **Confirmed** | Move to per-user credentials + audit log of actor | Yes | Medium | R1 |
| **R8** | **No `Revenue`/`Employee Count` parsing; no `Contact Email` format validation at import** | Low | Validation | Malformed data stored, fails later at send | Import only validates name/website/evidence/service | `validators.py` L190; `excel_service.py` | **Confirmed** | Add email format + numeric parsing | Yes | Low | None |
| **R9** | **`followup_config.py` defined but unused** (hardcoded 3/7 in tracking service) | Low | Maintainability | Two sources of truth for delays | Refactor leftover | `followup_config.py` L4 vs `outreach_tracking_service.py` L56 | **Confirmed** | Use the config module or delete it | No | Low | None |
| **R10** | **Legacy Node backend + logs coexist** (`backend/src/`, `backend_node_backup/`) | Low | Maintainability | Confusion about which backend is live | Migration artifact | File tree | **Confirmed** | Archive/remove from active tree | No | Low | None |
| **R11** | **No length/schema hard-validation of LLM output** | Low | AI quality | Overly long or malformed copy could be saved/sent | Only "is it a sequence array" is checked | `outreach_service.py` L418 | **Confirmed** | Add JSON-schema + length validation | Yes | Low | None |
| **R12** | **Two backend processes running** (13016 stale, 13048 serving) | Low | Ops | Confusion; resource waste | Duplicate start of safe runner | Process list | **Confirmed** | Kill the stale pid | No | Low | None |

---

## 14. Recommended Fix Plan

### P0 — Data loss / unauthorized sends / critical security
1. **Add authentication + authorization to every route** (R1, R2). At minimum: a session/token middleware; protect `POST /outreach/{id}/send`, `DELETE /companies*`, `POST /settings*`, `POST /import/*/confirm`. Keep the scheduler **disabled** until auth is in place.
2. **Do not start the backend via `run.py` (which enables the 60s scheduler) until auth exists** (R2). Keep using the safe-mode runner.

### P1 — Core workflow defects
3. **Clear `scheduledAt` when demoting a follow-up to `draft`** (R3) in `_pause_followups_for_recipient_change` and the `_sync_followup_recipients` conflict branch; add a message-level reconciler. This is the direct fix for the §4.3 / D1 regression.
4. **Block placeholder/invalid recipients at the source** (R4): validate `Contact Email` format at import and reject `"Not publicly available"`-style placeholders at contact discovery.

### P2 — Reliability & validation
5. **Centralize the Ollama model name** (R5) into one config used by `ai_service`, `decision_maker_engine`, and `company_researches`.
6. **Add a partial unique index on `companies.normalizedWebsite`** and dedupe the existing `D4` duplicate (R6).
7. **Add JSON-schema + length validation** for LLM output before save/send (R11).

### P3 — Maintainability
8. **Delete or wire up `followup_config.py`** (R9); remove/archived the legacy Node backend (R10).
9. **Split `CompanyDetail.jsx` and `decision_maker_engine.py`** into smaller modules.
10. **Pin `requirements.txt` versions** and declare the search dependency.

### Safe manual workarounds (no code change)
- **Until auth exists:** keep the backend on the safe-mode runner and bind to `127.0.0.1` only; do not port-forward; do not run `run.py`.
- **To send an email today:** use the UI's "Send Email Now" button (manual, operator-initiated) — this is the intended path and is guarded by send_guard.
- **To clear the 20 stale `scheduledAt` messages safely:** a one-off `$unset` of `scheduledAt` on `status='draft'` messages (requires owner approval — not done in this audit).
- **To remove the duplicate `D4 ReadOnly Corp`:** delete one of the two docs (requires owner approval).

### Verification steps for each fix
- **R3 fix:** `db.outreachmessages.count_documents({status:'draft', scheduledAt:{$ne:null}})` → 0; add a unit test that demotes a follow-up and asserts `scheduledAt` is unset.
- **R1/R2 fix:** `curl -X POST http://127.0.0.1:5000/api/companies` without a token → 401/403; with a valid token → 200.
- **R5 fix:** assert all three services resolve the same model string; run a real generation end-to-end.
- **R6 fix:** `db.companies.createIndex({normalizedWebsite:1},{unique:true, partialFilterExpression:{normalizedWebsite:{$type:'string'}}})` succeeds; re-count duplicates → 0.

### Questions requiring owner approval
1. What authentication mechanism is desired (session cookie, API key, OAuth/Google)? Should there be multiple users or a single operator?
2. Should the scheduler be re-enabled at all, or should all sends remain manual for now?
3. Approval to run the one-off cleanup for the 20 stale-`scheduledAt` messages and the duplicate `D4` company.
4. Is the legacy `backend/src/` Node backend safe to archive/delete?

### Checks that could NOT be completed safely (marked NOT VERIFIED)
- **Re-running the backend test suite** to confirm current pass/fail (not run; would write to the *test* DB, but the audit was strictly read-only and the suite was not executed). Historical "251 passed" is unverified here.
- **Re-running the frontend `node --test`** (not run; same reason).
- **Verifying the live `.env` secret values** (intentionally never printed; only key *names* and the presence of `ADMIN_RELEASE_KEY` were checked).
- **Verifying the actual SMTP credentials work** (would require sending a test email — forbidden).
- **Verifying which Ollama models are actually loaded** (would require calling Ollama; not done — the model-name inconsistency is a source-level finding).
- **Frontend production build** (`npm run build`) — not run (would create build artifacts).

---

## 15. Final Summary

### The five most important confirmed issues
1. **No authentication or authorization on any backend route** — anyone on the machine can send email, delete all companies, or change SMTP settings (`outreach_routes.py` L290, `company_routes.py` L39, `settings_routes.py` L55). **[Critical]**
2. **The 60-second auto-dispatch scheduler is disabled only by a temporary runner** — the moment the backend is started normally (`run.py`, `main.py` L31), any due `scheduled` message will send automatically. Currently 0 scheduled messages, so the immediate exposure is low, but the design is one command away from auto-send. **[High]**
3. **20 draft messages carry a stale `scheduledAt`** because the follow-up demotion paths set `status='draft'` without clearing `scheduledAt` (`outreach_service.py` L131/L242). Not a send risk today, but a latent consistency gap and the direct cause of the §4.3 regression. **[Medium]**
4. **Invalid recipients persist on live messages** — 6 messages store the literal string `"Not publicly available"` as the recipient and 8 have empty recipients; they can never send and will silently fail if armed. **[Medium]**
5. **Three different Ollama model names** are hardcoded across services (`qwen2.5-coder:7b-instruct`, `qwen2.5:1.5b`, `llama3`), so at least two code paths will fail with "model not found" unless all three models are loaded. **[Medium]**

### The most urgent risk
**The combination of (1) unauthenticated mutating routes and (2) the scheduler being one `run.py` invocation away from automatically sending email.** Until authentication exists, the backend must stay on the safe-mode runner and must not be started via `run.py`.

### Recommended first fix
**Add authentication + authorization to all routes and keep the scheduler disabled** (P0). This is the single change that closes the largest attack surface and prevents unauthorized/automatic sends. Immediately after, fix the stale-`scheduledAt` demotion bug (R3) since it is a small, low-risk, high-clarity fix with an obvious regression test.

### Evidence still missing
- Current backend/frontend test results (not re-run; only historical "251 passed" exists).
- Live `.env` secret values (intentionally not read).
- Which Ollama models are actually loaded (would require calling Ollama).
- Whether the SMTP credentials work (would require sending email — forbidden).
- Frontend production build status.

### Confirmation of no changes
**No application files, database records, service states, Git state, or email settings were modified during this audit.** All database queries were read-only (aggregates/counts only; emails masked). No services were started, stopped, or restarted. No emails were sent. No packages were installed. The only writes were to the **temp directory** (`C:\Users\Hello\AppData\Local\Temp\opencode\`) for read-only audit scripts, and this report file. The live database was **only read**; the mid-audit increase in companies (33 → 54) was caused by a **new import performed through the running application by the user**, not by this audit.
