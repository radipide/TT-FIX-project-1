# TT FIX — Working Notes: Order Routing (Order Gateway)

> Our own summary, not a copy of TT's docs. Verify tag numbers against the
> schema XML before shipping. See `00-overview.md` for the source-of-truth
> policy.

## Source pages referenced in this note
- Execution Report (8) message reference: https://library.tradingtechnologies.com/tt-fix/general/Msg_ExecutionReport_8.html
- TT FIX schema (order routing section): https://library.tradingtechnologies.com/tt-fix/tt-fix-order-routing/overview-tt-fix-order-routing/tt-fix-schema/

## Core message set

| MsgType | Name | Direction | Purpose |
|---|---|---|---|
| D | New Order Single | Client → TT | Submit a new order |
| G | Order Cancel/Replace Request | Client → TT | Amend a live order |
| F | Order Cancel Request | Client → TT | Cancel a live order |
| H | Order Status Request | Client → TT | Query order(s) status / rebuild state |
| 8 | Execution Report | TT → Client | Ack, fill, reject, cancel, replace confirmation |
| 9 | Order Cancel/Reject | TT → Client | Cancel or replace request was rejected |
| j | Business Message Reject | TT → Client | Application-level message rejected |

## Session start behavior

The Order Gateway **only supports persistent sessions**. First-ever startup
logs on with sequence number 1; any unscheduled restart after that goes
through normal FIX sequence-number negotiation (resend requests etc.)
instead of resetting. This matters for our mock acceptor — it should
reproduce both behaviors so we're not surprised in real certification.

## Execution Report notes worth flagging (from the ER-8 reference page)

- There is a **TT Self-Match Prevention by ID (TT SMP)** feature — an
  optional, user-defined alphanumeric tag used to detect and prevent an
  account from crossing its own orders. It's described as available "on a
  limited basis" and requires contacting a TT rep for access. Separate from
  this, exchange-based SMP uses its own FIX tags. Not needed for Phase 1,
  but worth knowing it exists before someone reinvents it.
- On the Execution Report, a **clearing account can override** the default
  account configured in TT's Setup application for the account in tag 1 —
  useful to know if fills ever show a different account than expected.
- For **TT parent synthetic Limit orders** where the limit price is set as
  an offset relative to a live value (e.g. current Bid/Ask/Last), the price
  tag may legitimately be **absent** on parent Execution Reports. If we
  build synthetic/offset orders later, don't treat a missing price tag as a
  parsing bug in that specific case.
- Certain child/parent aggregate fields (e.g. sum of working quantities of
  child orders) are only sent under specific conditions — generally, unless
  an Order Status Request (H) comes back with no orders, meaning some
  fields are conditionally present, not guaranteed on every message. Don't
  assume every Execution Report is fully populated; code defensively.

## Design implications for our client (from `PROJECT.md` §6)

- Every order gets a unique `ClOrdID`, never reused.
- Order state is a projection of Execution Reports received — not set
  optimistically at send time.
- On startup/reconnect, send an Order Status Request (H) to rebuild state
  from TT's view rather than trusting local state.
- The mock acceptor should be able to simulate: normal ack → fill, reject
  at ack, reject at cancel/replace, and a sequence-number mismatch on
  logon — since that last one is explicitly part of what TT tests at
  certification time.

## Open items to verify directly against TT / the schema
- Exact field list and conditions on Execution Report for our specific
  order types (Market, Limit) — pull from the live schema, not this note.
- Whether aggregated-fills-per-report or individual-Execution-Report-per-fill
  is configured for our session (this is a per-session Setup option).
