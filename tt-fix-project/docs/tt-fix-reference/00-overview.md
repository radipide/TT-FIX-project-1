# TT FIX — Working Notes: System Overview & Certification

> These are our own paraphrased summary notes for quick orientation, **not**
> a copy of TT's documentation. TT's Help Library and the FIX schema XML are
> always the authoritative source — see `PROJECT.md` §5. Every claim below
> links to the live page it came from; open the link before relying on a
> tag number for real work.

## Source pages referenced in this note
- System Overview: https://library.tradingtechnologies.com/tt-fix/tt-fix-general/getting-started-tt-fix-general/system-overview/
- TT FIX Certification: https://library.tradingtechnologies.com/tt-fix/tt-fix-general/getting-started-tt-fix-general/tt-fix-certification/
- TT FIX Schema page: https://library.tradingtechnologies.com/tt-fix/general/System_Overview.html#fix-schemas
- FIX Trading Community (general FIX tag reference): http://www.fixtradingcommunity.org/

## What TT FIX is

TT FIX is Trading Technologies' FIX gateway layer: one FIX connection
standard that TT translates outward to many exchanges, so a client doesn't
need a bespoke integration per venue.

- TT FIX implements a **subset** of FIX 4.2 (Errata 20010501) and FIX 4.4 —
  only the messages and tags TT documents are supported; sending anything
  else can produce undefined behavior.
- TT publishes separate **production** and **UAT** versions of the FIX
  schema as downloadable XML. The schema file's second line is an XML
  comment stamped with a publication date and a git hash — always check
  this before trusting a schema copy, since it can go stale.
- TT FIX is split into distinct services running over separate sessions —
  this project cares about two of them: **Order Gateway** (order routing)
  and **Price Gateway** (market data / security definitions). See
  `01-order-routing.md` and `02-market-data.md`.

## Session-level mechanics worth internalizing early

- The TT FIX **Order Gateway only supports persistent FIX sessions**. On
  its first-ever start, it logs on with MsgSeqNum (tag 34) = 1. On any
  unscheduled restart afterward, standard FIX sequence-number negotiation
  kicks in (resend requests, gap fill) rather than resetting to 1.
- The TT FIX **Price Gateway** has a specific instrument-readiness
  handshake worth remembering: for each valid instrument, it sends a
  Security Status Request (`e`), and it will not process a price
  subscription for that instrument from client applications until it has
  received a Security Status (`f`) response. In other words, security
  status and security definition aren't just informational — they can gate
  whether your market data request even works.
- A price-message-only schema is separately downloadable at
  `https://library.tradingtechnologies.com/tt-fix/fix_price_messages.xml`
  if you only need the market-data message set.

## Message categories (from TT's own page structure)

TT's docs group FIX messages into three buckets, which map directly onto
the sessions:

1. **Session messages** — Logon (A), Logout (5), Heartbeat (0), Test
   Request (1), Sequence Reset (4), Session-Level Reject (3), Resend
   Request (2). Same on every session; this is the plumbing FIX itself
   defines, not something TT customizes much.
2. **Price Gateway messages** — Security Definition Request (c) / Security
   Definition (d), Security Status Request (e) / Security Status (f),
   Market Data Request (V) / Market Data Request Reject (Y) / Market Data
   Snapshot-Full Refresh (W) / Market Data Incremental Refresh (X).
3. **Order Gateway messages** — Execution Report (8), Business Message
   Reject (j), New Order Single (D), Order Cancel/Replace Request (G),
   Order Cancel/Reject (9), Order Cancel Request (F).

## Certification, in plain terms

- TT explicitly frames certification as **client-specific**, not a fixed
  script: "aims to meet each client's specific testing needs," and
  encourages running scenarios that resemble your actual production
  behavior rather than a generic checklist.
- If TT's out-of-the-box tag support doesn't match what you need, TT offers
  a **FIX Rules Engine** — administrator-configurable rules and symbol
  mappings — rather than TT changing the core protocol for one client.
  Relevant setup docs:
  - Administering FIX Rulesets: https://library.tradingtechnologies.com/user-setup/fxp-administering-fix-rulesets.html
  - Configuring FIX Rules: https://library.tradingtechnologies.com/user-setup/fxp-configuring-fix-rules.html
  - Defining Symbol Mappings: https://library.tradingtechnologies.com/user-setup/fxp-defining-symbol-mappings.html
- Practical implication for us: when we eventually hit certification, we
  should bring **our actual Phase 1/2 order flows** (market + limit orders,
  our specific CME instrument) as the test scenarios, not a generic FIX
  conformance suite.

## Open items to verify directly against TT once we have contacts/credentials
- Exact current schema version/date (check line 2 of the downloaded XML).
- Whether our onboarding includes access to the FIX Rules Engine or not.
- Confirm which specific certification scenarios TT wants for our use case.
