# TT FIX CME Trading Dashboard — Project Charter

**Owner:** Aditya
**Contributor:** Ankit
**Status:** Pre-UAT build (Phase 1)
**Last updated:** 2026-08-31

This file is the single source of truth for the project. If a decision, a scope
change, or a lesson learned isn't written here, treat it as not having
happened. Every other doc in this repo (code comments, PR descriptions, issue
threads) links back to this file — this file does not link forward to them.

---

## 1. What this project is

A Python application that connects to Trading Technologies (TT) FIX services
for a CME instrument, and:

1. Streams live top-of-book bid/ask into a simple web dashboard.
2. Lets a user place Market and Limit orders on the selected instrument from
   that dashboard.
3. Measures and reports order execution latency.

This is a learning + infrastructure project ahead of real UAT credentials.
The mock TT acceptor built alongside it is not throwaway code — it is the
permanent test harness for this project, and it stays in the repo after UAT
access is granted.

## 2. Why (the aim, in plain terms)

The end target is **tick-level data capture and controlled execution
testing** against TT FIX — not just a demo dashboard. Concretely, in order of
priority:

1. **Market execution correctness first.** Before anything clever, prove
   that a Market order and a Limit order round-trip correctly through TT FIX
   session mechanics, and that the Execution Report stream is parsed without
   ever silently dropping a fill.
2. **Tick-level data.** Move from top-of-book snapshots to full incremental
   tick capture (every `MarketDataIncrementalRefresh` message), stored with
   nanosecond local receipt timestamps, so execution quality can later be
   measured against the tape rather than against our own book.
3. **VWAP execution for large orders.** Once single-order execution is
   solid, build a simple slicing algo that breaks one large order into
   child orders against a volume curve, and compares its achieved price to
   the interval VWAP.
4. **Randomized multi-frequency order generation.** A test-order generator
   that fires orders at multiple configurable frequencies (e.g. Poisson
   arrival at several different mean rates) purely against the mock
   acceptor / UAT sim, to stress-test the order-handling and latency-logging
   code before it ever sees a real desk.

Items 3 and 4 are **not** in Phase 1 scope (see §3). They are documented here
so nobody re-litigates the roadmap later, and so early architecture choices
(see §6) don't quietly foreclose them.

## 3. Phase scope

### Phase 1 — this build (no UAT credentials required)
- [ ] Mock TT FIX acceptor (order routing + market data sessions)
- [ ] Market data client: Security Definition Request → Market Data Request
      → live bid/ask
- [ ] Order client: New Order Single (Market, Limit), Execution Report
      handling, Order Cancel Request
- [ ] Dashboard: instrument picker, live bid/ask, order entry form, order
      status table
- [ ] Latency harness: per-order send-to-ack timing, p50/p95/p99/max report
- [ ] This markdown, kept current

### Phase 2 — once UAT credentials arrive
- [ ] Point config at TT UAT endpoints, re-run everything above unchanged
- [ ] Confirm CME entitlements (market data + order routing separately)
- [ ] Run TT's basic conformance test outline, log results, send to
      fixintegration@trade.tt
- [ ] Rehearse session-level sequence-number-mismatch scenarios against the
      mock acceptor *before* TT runs them for real

### Phase 3 — beyond this repo's current scope
- [ ] Tick-level data capture and storage
- [ ] VWAP slicing algo + TCA (transaction cost analysis) against VWAP
- [ ] Multi-frequency randomized order generator for stress testing

**Rule:** don't start Phase 2 code until every Phase 1 checkbox is ticked and
demoed against the mock acceptor. Don't start Phase 3 until UAT round-trips
are verified end to end.

## 4. Non-goals (explicitly out of scope)

- Connecting directly to any exchange — everything goes through TT FIX.
- Production trading. Nothing in this repo talks to a production endpoint
  until it's explicitly relabeled and reviewed.
- A "smart" or ML-based execution algo. VWAP slicing here means a basic,
  auditable volume-curve schedule, not a model.
- Drop Copy integration (may become Phase 4, not designed for yet).

## 5. Source of truth for the FIX spec

The `docs/tt-fix-reference/` folder in this repo is our own paraphrased
working notes with links back to the originals — **not** a copy of TT's
documentation. TT's pages are copyrighted and the actual schema is the real
source of truth for exact tags. Always check, in this order:

1. The TT FIX schema XML files (get from TT once credentials exist; UAT and
   production schemas differ — check the version comment on line 2 of the
   file).
2. TT's own Help Library (https://library.tradingtechnologies.com/tt-fix/) —
   open the live page, don't trust a stale local copy.
3. `docs/tt-fix-reference/*.md` in this repo — our summary, for orientation
   only.

If our notes and the live TT docs ever disagree, the live docs win, and
whoever finds the mismatch fixes our notes in the same PR.

## 6. Architecture decisions and why

| Decision | Reasoning |
|---|---|
| Python + QuickFIX | Manager's instruction. QuickFIX handles the FIX session layer (logon, heartbeats, sequence numbers) so we don't reimplement it. |
| **`simplefix` instead of QuickFIX (revised 2026-08-31)** | QuickFIX's C++ build fails on this dev machine's MSVC toolchain (Visual Studio Build Tools 2026 / `cl.exe` 14.51) with STL-level template redefinition conflicts (`std::_Is_memfunptr`, `std::_Function_args` already defined) — a genuine incompatibility between QuickFIX's legacy pre-C++11 compatibility shims and this compiler version, not a config mistake. WSL was considered (per §9, which already anticipated this exact pain point) but not yet set up. Chose to keep moving in Phase 1 rather than block on WSL setup. `simplefix` only builds/parses individual messages — the session layer (logon, heartbeats, sequence numbers, TestRequest handling) is hand-rolled in `src/fix_session.py`. **Revisit before Phase 2/3** if resend logic, message persistence, or session robustness becomes limiting — those are things QuickFIX gives for free and `simplefix` does not. |
| Two separate FIX session objects (market data, order routing) | TT FIX is inherently multi-session; modeling it as one connection would be wrong from day one and require a rewrite. |
| **Single FIX session object for now (revised 2026-08-31)** | Keeping Phase 1 simple while learning the session layer from scratch with a hand-rolled (non-QuickFIX) implementation. This is a deliberate, documented deviation from the row above — split into two sessions before this is considered done, and definitely before Phase 2. |
| Mock acceptor before UAT | UAT credentials weren't available yet; the acceptor removes that dependency from the critical path and becomes the permanent test double. |
| Full-refresh market data (not incremental) in Phase 1 | Simpler to get correct; matches the Phase 1 goal (bid/ask display) without book-maintenance bugs. Revisit for Phase 3 tick capture, which needs incremental refresh. |
| Execution Reports are the only source of order truth | An order is not "live" because we sent it; it's live because TT said so. Prevents state drift on reconnect/replay. |
| Single `main` branch, no long-lived feature branches | Explicit project requirement — keep the history linear and easy to read for a two-person team. See §8. |
| FastAPI + WebSocket dashboard | Prices update multiple times a second; a push channel is required, polling-based tools (Streamlit/Dash) fight this. |
| **Streamlit instead of FastAPI+WebSocket (revised 2026-08-31)** | Faster to get a working Phase 1 dashboard while learning the FIX session layer from scratch. Uses `st.fragment(run_every=1)` for a 1-second polling refresh. This is a known limitation for genuinely high-frequency ticks — acceptable for Phase 1 top-of-book display, but should be revisited before Phase 3 tick-level capture, where the original FastAPI+WebSocket reasoning applies in full. |

## 7. Code hygiene rules for this repo

These are deliberately strict for a learning project — the point is to
practice the habit, not just ship a demo.

1. **One branch.** Everyone commits to `main`. No `feature/*`, no `dev`. If
   work is unfinished, commit it in a clearly-marked, non-breaking state
   (e.g. behind a config flag) rather than branching. This is a project
   requirement, not just a style preference — the two-person team explicitly
   wants one linear history that's easy to review.
2. **Commit messages describe the "why," not just the "what."** Bad:
   `fix bug`. Good: `fix: ClOrdID reused after reconnect, caused TT to
   reject duplicate order`.
3. **No secrets in git, ever.** TT SenderCompID, passwords, account numbers
   go in a local `.env` file, which is gitignored. `config.example.env` in
   the repo shows the shape with placeholder values only.
4. **No commented-out code blocks left in place.** Delete it — git history
   remembers it if it's needed again.
5. **Every module has a docstring explaining its one job.** If you can't
   state the job in one sentence, the module is doing too much.
6. **Type hints on every function signature.** This is a FIX/finance
   project; silent type confusion between a price and a quantity is exactly
   the kind of bug that's expensive.
7. **All timestamps in UTC, always logged with timezone.** FIX itself uses
   UTC (tag 52, tag 60) — don't introduce local time anywhere in the stack.

## 8. Git / GitHub workflow

- Repo is **public or private, one branch (`main`), no branch protection
  rules that require PRs** — direct commits are fine for a two-person
  learning project. (Revisit if the team grows.)
- Commit early, commit often, in small units.
- Tag milestones instead of branching: `git tag phase1-mock-acceptor-done`.
- `docs/`, `src/`, `tests/`, `PROJECT.md`, `README.md` at repo root — see
  `README.md` for the exact layout and setup steps.

## 9. Replicability requirement

Anyone (Ankit, a new team member, future-you on a new laptop) must be able
to go from a clean machine to a running mock-acceptor demo using only
`README.md`. Concretely, that means:

- All dependencies pinned in `requirements.txt` (exact versions, not
  ranges).
- No hardcoded paths, ports, or credentials in source — everything through
  `config.py` reading from `.env`.
- The mock acceptor must run with zero external services and zero
  credentials — `python scripts/run_mock_acceptor.py` and nothing else.
- README includes the exact OS/Python version this was built and tested on,
  and flags any OS-specific install steps (QuickFIX's C++ dependency is the
  likely pain point on Windows — WSL recommended).
- If a step in the README doesn't work on a fresh machine, that's a bug in
  the README, filed and fixed like any other bug.

## 10. Working with Claude on this project (prompt engineering notes)

This section exists because "no hallucination" was an explicit goal. Rules
for prompting Claude (or any LLM) on this codebase:

- **Always paste the actual TT FIX tag/message you're asking about**, or a
  link to the live TT doc page, rather than asking from memory. LLMs
  (including Claude) can misremember exact tag numbers or message field
  requirements — treat any tag number an LLM gives you as a claim to verify
  against the schema XML or the live TT page, not a fact.
  When you ask Claude to "fix" something, first ask Claude to state its
  understanding of the current behavior and cite the file/lines *before*
  proposing a change, and check it against the file yourself.
- **Ask Claude to point at its source for any FIX-specific claim.** A good
  pattern: "What's your source for tag X meaning Y — the schema file, the
  TT help page, or general FIX knowledge?" If the answer is "general FIX
  knowledge" and this is a TT-specific behavior, treat it as unverified.
- **When asking "how not to do X"**, ask for the failure mode and why it
  fails, not just the fix — e.g. "why is polling a bad pattern for FIX
  execution report handling" gets a more durable answer than just "give me
  the async version."
- **Keep this file (`PROJECT.md`) attached/pasted whenever starting a new
  Claude conversation about this repo.** It's the context that prevents
  Claude from re-suggesting things already decided against in §4 and §6.
- **Review every generated FIX message construction line by line against
  the schema** before running it against even the mock acceptor. This is
  the highest-value place to catch a hallucinated tag number.

## 11. Open questions for manager / TT onboarding

- Which specific CME product/instrument for Phase 1 (this determines
  ExDestination — CME sub-markets differ)?
- FIX 4.2 or 4.4?
- Will UAT sessions include CME market data entitlement separately from
  order routing entitlement?
- Confirm whether "aggregated fills" per session setting should be
  requested as individual Execution Reports for easier parsing.

## 12. Changelog

- 2026-08-30 — Initial charter written. Phase 1 scope defined.
- 2026-08-31 — Switched Phase 1 implementation from QuickFIX to `simplefix`
  and from FastAPI+WebSocket to Streamlit, due to unresolvable QuickFIX
  build failures on Windows/MSVC. Kept a single FIX session object for now
  instead of the two-session (market data / order routing) design. See §6
  for full reasoning on all three deviations. Revisit before Phase 2/3.
