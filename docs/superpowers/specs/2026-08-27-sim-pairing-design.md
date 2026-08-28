# SIM Pairing — Design Spec

## Overview

A `SIM Pairing` tab that keeps a fleet of SIMs conversationally active. SIMs managed by the external **TmLite** MCP server are paired deterministically, each pair is given a conversation subject, and an LLM writes one short French SMS at a time that is sent from one SIM of the pair to the other over TmLite.

Both endpoints of every conversation are SIMs the operator already controls. Traffic never leaves the operated fleet: there is no path in this design by which a message reaches a number that was not produced by TmLite's own SIM list.

The design has two rules that everything else follows from:

1. **Pairing and sending are separate services.** `SimPairingService` decides who talks to whom and never sends. `SimPairConversationService` is the only code that sends.
2. **Cadence lives in a database queue, not in the trigger.** The scheduler firing more often, a restart, or a manual click cannot make a pair exchange messages faster than its configured interval.

*Status: written after implementation, from the shipped code, to give the feature the same design record as the other five. It describes behaviour that exists.*

## Dependency: TmLite

The feature requires an **enabled `McpServer` row named exactly `TmLite`** with `transport == "http"`. Both services raise `RuntimeError` when it is absent, and — unlike `sipp-stress` — nothing auto-registers it. It is created by hand in the Config tab.

Three of its tools are used:

| Tool | Arguments | Used for |
|------|-----------|----------|
| `list_gateways` | `limit`, `skip` | Mapping a SIM to a country |
| `list_sims` | `limit`, `skip` | Eligibility, state, phone number |
| `send_sms` | `from_sim_id`, `to_number`, `text` | Delivery |

Both list calls are paged 100 at a time up to 10 000 records and stop on the first short page. Tool results are unwrapped by `SimPairingService._items()`, which accepts `{"items": [...]}`, `{"data": [...]}` or a bare list, because the shape is not guaranteed by the MCP contract.

## Architecture

### Models (`app/models/sim_pairing.py`)

**SimPairingGroup** — a TmLite SIM group whose SIMs may be paired.
- `name`: String(200), unique; `enabled`: Boolean, default True.
- Group names select *eligible SIMs*. They are not conversation subjects — a pair may span two groups.

**SimPairingTopic** — a conversation subject (`name`, String(200), unique).

**SimPairingSim** — the local identity of a SIM.
- `sim_id`: Integer PK (TmLite's id); `display_name`: String(100), unique; `country`.
- The display name is assigned once and never changes. It exists only in this database; **nothing ever renames a SIM in TmLite**, so carrier-facing configuration stays untouched.

**SimPair**
- `sim_a_id` / `sim_b_id`: Integer; `sim_a_name` / `sim_b_name`: String(100) — denormalised at creation, refreshed by sync.
- `country`, `group_a`, `group_b`, `topic`.
- `target_messages`: Integer, default 10 — how long this conversation should be. Direction alternates strictly, so an even target splits evenly between the two SIMs: 10 means 5 each.
- `sent_count`: Integer — a stored counter rather than a `COUNT()` per run, because it is read on every queue ordering.
- `status`: `active` | `archived`; `archived_reason`, `archived_at`.

A pair that reaches its target is **not stopped**. The target is a floor, not a cap: it changes the *order* in which pairs are served, so no pair goes past its target while another is still short of it. Crossing the target writes one `target_reached` history row.

**SimPairHistory** — an append-only audit log: `pair_id`, `event` (`created`, `archived`, `message_sent`, `message_failed`), `details` JSON.

**SimPairMessage** — one row per generated SMS: `from_sim_id`, `to_sim_id`, `content`, `provider`, `model`, `status` (`generated` | `sent` | `failed`), `error`, `sent_at`. A generation or delivery failure writes a row with empty content and the error, so a failed attempt is visible rather than silent.

**SimPairMessageQueue** — the durable work queue: `pair_id`, `status` (`pending` | `sent` | `failed`), `due_at`, `attempts`, `last_error`, `sent_at`.

**Config** (existing singleton row) gains four columns:
- `pairing_openrouter_api_key`: String(500), Fernet-encrypted, exposed only as `pairing_openrouter_api_key_set: bool`
- `pairing_openrouter_model`: String(150), default `google/gemini-2.5-flash`, rejected empty (422)
- `pairing_conversation_enabled`: Boolean, default **False** — the feature is off until deliberately switched on
- `pairing_conversation_interval_minutes`: Integer, default 180, constrained to 30–1440 (422 outside) — a **minimum**, which is why jitter only ever adds to it
- `pairing_target_messages`: Integer, default 10, constrained to 2–100 — stamped onto pairs at creation, so changing it never rewrites conversations already under way
- `pairing_max_messages_per_run`: Integer, default 10, constrained to 1–50 — a ceiling on run duration, **not** a cadence knob
- `pairing_sim_cooldown_minutes`: Integer, default 20, constrained to 0–240 (0 disables the rule)
- `pairing_quiet_hours_enabled`: Boolean, default **True**; `pairing_quiet_start_hour` / `pairing_quiet_end_hour`: Integer, default 22 and 7, constrained to 0–23

### Pairing (`SimPairingService.sync`)

Every run opens a `SimPairingRun` row and closes it with a summary dict or an error, so an unattended 15-minute job leaves a trail.

**Eligibility.** A SIM qualifies when all of the following hold:
- its `state` is neither `OFFLINE` nor `DISABLED`;
- its `sim_group_name` matches a tracked, enabled `SimPairingGroup` (case-insensitive);
- a country resolves for it — by `gateway_id`, falling back to an upper-cased `gateway_name` match. A SIM with no resolvable country is dropped rather than paired blind.

**Naming.** `_ensure_sim_names()` gives every eligible SIM one persistent label drawn from a fixed list of 20 West African first names, skipping names already taken. Once the list is exhausted the fallback is `SIM {id}`. Existing records keep their name and only have `country` refreshed.

**Archiving before creating.** Every active pair is re-checked: if either SIM stopped being eligible, or the two countries no longer agree, the pair is archived with a reason and an audit row. Pairs are never deleted — their message history stays readable. Surviving pairs have their denormalised names refreshed if the underlying label changed.

**Creation.** Over eligible SIM ids in sorted order, every unordered pair is considered and created when:
- both SIMs are in the same country;
- neither SIM already has **3 pairs**;
- the pair does not already exist (compared as an unordered `frozenset`, so A↔B and B↔A are one pair).

The subject is `topics[created % len(topics)]` — round-robin **within a run**. Known consequence: because the counter restarts each run, subjects early in the alphabetical list are assigned more often than later ones across many small runs. Accepted; subject distribution is not a correctness property.

Sync is idempotent: running it twice in a row creates nothing the second time.

### Conversation (`SimPairConversationService.run_due`)

Preconditions, each returning a `reason` string rather than raising: another run holds the module-level `asyncio.Lock`; `pairing_conversation_enabled` is false; no OpenRouter key; no active pairs.

**Flow**
1. Load active pairs, optionally filtered by `country`. **Sending does not re-sync.** The dedicated `sim_pairing_sync` job already refreshes eligibility every 15 minutes; syncing here would enumerate the whole TmLite fleet a second time per run, and the `IDLE` guard below already makes every individual send safe.
2. `_enqueue_pairs()` — for every pair with no `pending` queue row, create one. `due_at` is the last sent message's `sent_at` plus the interval **multiplied by a random 1.0–1.35 jitter**, or *now* for a pair that has never spoken. **This is where the interval is enforced.** A pending row keeps its planned time across restarts and across manual runs.
3. `_due_candidates()` — read `pending` rows with `due_at <= now`, ordered by:
   1. `sent_count >= target_messages` ascending — Postgres sorts `false` first, so **pairs below their target are always served before pairs that have reached it**;
   2. `due_at`, then `created_at`.
   It over-fetches `batch × 4` (capped at 200), because the per-SIM rules below drop candidates and a strict fetch would waste the run's capacity.
4. If *now* falls inside the quiet window, stop here and return a reason. The queue was still maintained at step 2, so the schedule stays accurate overnight; only delivery pauses. A manual run does not bypass this, exactly as it does not bypass the per-pair interval. A **preview still works at night** — it sends nothing.
5. Open one TmLite client, list SIMs once, then `_select_batch()` picks what may actually be sent.
6. For each chosen item: generate, persist, send, commit.

**Direction** alternates strictly. `_next_direction()` looks at the last *sent* message: if it came from SIM A, SIM B speaks next; otherwise SIM A does. A pair with no history starts with A. This is what makes a target of 10 mean 5 from each SIM, with no extra bookkeeping.

**`_select_batch()`** is a pure function — no session, no client — which is what makes the pacing rules testable without mocks. Three rules in order:

1. Both SIMs must be `IDLE` with a `phone_number`. Otherwise the item is **deferred**: `due_at` pushed 15 minutes, `last_error` recorded. This is the only rule that writes to the database, because it is the only one that signals an anomaly.
2. **A SIM speaks at most once per run.** A SIM belongs to up to 3 pairs; without this it would emit on all of them within the same minute.
3. **A SIM waits out `pairing_sim_cooldown_minutes`** since it last sent *or received* a message.

Rules 2 and 3 mark the item as *held*: nothing is written, the item stays due, and it is first in line next run. They are ordinary pacing, not failure.

**Failure.** Any exception increments `attempts`, records `last_error`, and either defers the item 15 minutes or, at 3 attempts, marks it `failed`. A `SimPairMessage` with `status = "failed"` and a `message_failed` history row are written. Each item commits independently, so one failure cannot roll back a sibling's successful send.

The run returns `{sent, skipped, held, failed, active_pairs, queued, overdue, pairs_under_target}`.

**Quiet hours** are fleet-wide and expressed in **UTC**. The SIMs span several West African countries; applying one window to all of them is a deliberate simplification, not an oversight — no per-country local time is computed anywhere. `_quiet_window()`, `_is_quiet()` and `_shift_out_of_quiet()` are pure functions. Equal bounds describe an *empty* window, never a fleet silent for 24 hours. A window is allowed to span midnight (22 → 7) and is evaluated accordingly.

The window is applied in two places, and both are needed. `_enqueue_pairs()` shifts a due time that lands inside the window to just after it, spread over `WAKE_SPREAD_MINUTES` (90) so a night of held pairs does not wake as a single burst — shifting at enqueue rather than at send time is what keeps the backlog figures honest, since an item held overnight reads as *due in the morning*, not as *overdue*. The run-time guard at step 4 then catches what enqueueing cannot: items queued before the setting changed, and 15-minute retries that would otherwise land inside the window (`_retry_at()` shifts those too).

**Capacity.** The scheduler polls every 15 minutes, and only outside the quiet window, so fleet capacity is `pairing_max_messages_per_run × 4 × sending_hours` messages/day — at the defaults, `10 × 4 × 15` = **600/day**, not 960. A pair wants `1440 ÷ interval` messages/day. Below `capacity ÷ (1440 ÷ interval)` active pairs the system is *interval-bound*, which is the healthy regime; above it the queue accumulates overdue items and every pair's real cadence stretches past the configured interval. At the defaults that line sits at **75 pairs**. `GET /queue/stats` is what makes that visible, the page computes the two figures from the live settings rather than leaving them to be derived, and it warns when `overdue` exceeds one run's capacity.

Reaching a target of 10 takes at least `9 × interval` regardless of capacity — 27 hours at the default 180 minutes.

### Message generation

OpenRouter, reached through the `openai` SDK pointed at `https://openrouter.ai/api/v1`. This is a **fourth provider path**, deliberately separate from `LlmService`: pair messages must not be able to consume the script-generation key, and the model choice is per-feature.

Context is the last 12 *sent* messages of the pair, oldest first, rendered as `Name: text`. A pair with no history is given `(This is the first message.)`.

The prompt fixes the content rules:
- one short **French** SMS continuing a fictional, consensual conversation between two adult test personas;
- the named sender and the pair's subject;
- **no requests for money, credentials, personal data, or contact with third parties**;
- no claims about real-world facts;
- plain text only, no quotes or markdown.

`temperature=0.8`, `max_tokens=120`. The blocking SDK call runs in `asyncio.to_thread`; `RateLimitError` retries twice with 5s and 10s backoff. The result is stripped of wrapping quotes and **rejected** if empty or longer than 240 characters — a too-long message is an error, never a truncation, because a cut-off SMS reads as broken rather than as a message.

### Scheduling

Two APScheduler jobs on a fixed 15-minute `IntervalTrigger`, registered unconditionally in `main.py`'s lifespan and not user-configurable:

- `sim_pairing_sync` → `SimPairingService.sync()`
- `sim_pair_conversation` → `SimPairConversationService.run_due()`

15 minutes is the *polling* rate, not the send rate: the queue's `due_at` is what decides whether anything happens. Both jobs are near-no-ops when the feature is unconfigured.

## API Endpoints

All under `/api/v1/sim-pairing`.

| Method | Path | Description |
|--------|------|-------------|
| GET / POST / DELETE | `/groups`, `/groups/{id}` | Tracked SIM groups; duplicate name → 409 |
| GET / POST / DELETE | `/topics`, `/topics/{id}` | Conversation subjects; duplicate name → 409 |
| GET | `/pairs` | All pairs, newest first |
| GET | `/pairs/{id}/history` | Audit events, newest first |
| GET | `/pairs/{id}/messages` | The conversation, oldest first |
| GET | `/queue` | Up to 100 queue rows, by status then due date |
| GET | `/queue/stats` | `pending`, `overdue`, `failed`, `pairs_under_target` — the backlog figures |
| GET | `/runs` | The last 20 sync runs |
| POST | `/sync` | Run pairing now — never sends |
| POST | `/conversations/run` | Process due items now, optional `?country=` |
| POST | `/conversations/preview` | Generate one candidate SMS, send nothing |

`POST /conversations/run` **obeys the same cadence as the scheduler**. A manual click cannot make a pair speak before its `due_at`; it only removes the wait for the next 15-minute tick.

`POST /conversations/preview` is a strict dry run: no sync, no TmLite call, no `SimPairMessage`, no queue mutation. It does call OpenRouter, so it costs tokens.

## Frontend (`src/pages/PairingPage.tsx`)

One page, five cards, all calls through `src/lib/api.ts`:

1. **SIM groups to track** — add/remove group names, with copy stating that groups select SIMs and are not subjects.
2. **Pairs and history** — every pair as `Name ↔ Name`, its country, subject, **progress as `sent_count/target_messages`** (green once the target is reached), status and archive reason, with per-pair *Messages* and *History* panels, plus a "Sync now" button. Pairs, messages and the queue poll every 30s.
3. **Conversation automation** — OpenRouter key (write-only, shows `(configured)`), model, interval, target, maximum per run, per-SIM cooldown, the quiet-hours panel (checkbox plus two UTC hours), the enable checkbox, and three actions: save, "Preview one SMS (no send)", "Continue due pairs now". The two send-adjacent buttons are disabled while automation is off. Each pacing field carries the arithmetic it implies, so the daily ceiling is readable from the form rather than discovered from a backlog.
4. **Message queue** — the backlog figures, the next items with their status and planned time, and a warning when `overdue` exceeds one run's capacity.
5. **Conversation subjects** — add/remove topics.

## Error Handling

- Missing or misconfigured TmLite → `RuntimeError` from the service, surfaced to the page through the mutation error.
- Automation disabled, no key, no active pairs, or a run already in progress → a **200 with a `reason`**, not an error. These are ordinary states, not failures.
- A SIM that is not `IDLE` → deferred, not failed.
- A generation or delivery error → recorded on the message, the queue row and the history, then the run continues.
- Invalid interval or empty model → 422 from the config router.

## Testing

- `tests/test_api_sim_pairing.py` — group CRUD, including the 409 on a duplicate name.
- `tests/test_sim_pair_quiet_hours.py` — the window helpers: disabled and equal-bound windows, a window spanning midnight, a window inside one day, an early-morning due time waking the same day, a late-evening one waking the next, and twenty shifted times not collapsing onto one instant.
- `tests/test_sim_pair_batch.py` — `_select_batch()`: one message per SIM per run, the cooldown holding and then expiring, `cooldown = 0` disabling the rule, a non-`IDLE` SIM being deferred rather than held, a SIM missing from TmLite altogether, and the batch ceiling stopping the walk without marking the remainder.

No test performs a network call. Keeping the pacing rules in a pure function is what allows that: the rules are decided from three plain arguments — the candidate list, the SIM map, the last-activity map — none of which requires a session or a client.

**Remaining gap:** the surrounding I/O of both services is untested — eligibility filtering, the 3-pair cap, archiving on ineligibility, name persistence across runs, `due_at` computation, the 3-attempt failure path, and the lock rejecting a concurrent run. All are reachable with a mocked FastMCP client and a mocked OpenRouter client.

## Out of Scope

Inbound SMS (nothing reads replies — the transcript is what this system sent, not what arrived), per-pair subject or target editing, manual pair creation, per-country intervals, **per-country quiet hours** (the window is fleet-wide UTC by decision, not by omission), and any non-French output.

## File Structure

```
backend/app/
├── models/sim_pairing.py                     7 tables
├── schemas/sim_pairing.py                    Pydantic schemas
├── routers/sim_pairing.py                    /api/v1/sim-pairing
├── services/sim_pairing_service.py           eligibility, pairing, naming — never sends
└── services/sim_pair_conversation_service.py queue, generation, delivery — the only sender

frontend/src/pages/PairingPage.tsx
```
