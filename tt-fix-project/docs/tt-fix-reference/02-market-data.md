# TT FIX — Working Notes: Market Data (Price Gateway)

> Our own summary, not a copy of TT's docs. Verify tag numbers against the
> schema XML before shipping. See `00-overview.md` for the source-of-truth
> policy.

## Source pages referenced in this note
- System Overview (Price Gateway section): https://library.tradingtechnologies.com/tt-fix/gateway/System_Overview.html
- FIX Price Messages schema download: https://library.tradingtechnologies.com/tt-fix/fix_price_messages.xml

## Core message set

| MsgType | Name | Direction | Purpose |
|---|---|---|---|
| c | Security Definition Request | Client → TT | Ask what instruments exist / subscribe to definition changes |
| d | Security Definition | TT → Client | Instrument reference data (tick size, contract size, etc.) |
| e | Security Status Request | Client → TT | Ask about / subscribe to instrument trading status |
| f | Security Status | TT → Client | Instrument status response |
| V | Market Data Request | Client → TT | Subscribe to prices for an instrument |
| Y | Market Data Request Reject | TT → Client | Subscription request rejected |
| W | Market Data Snapshot/Full Refresh | TT → Client | Full current book/top-of-book snapshot |
| X | Market Data Incremental Refresh | TT → Client | New/Change/Delete deltas to the book |

## The instrument-readiness handshake (important, easy to miss)

This is the detail most likely to cause a confusing "my subscription just
hangs" bug: for each valid instrument, the Price Gateway sends its own
Security Status Request (`e`) internally, and **will not process a market
data subscription request from client applications until it has received a
Security Status (`f`) response** for that instrument. In practice, this
means the sequencing that matters isn't just "get the Security Definition,
then request Market Data" — Security Status has a gating role too. If a
`V` request for an otherwise valid instrument goes nowhere, this handshake
is one of the first things to check (after checking entitlements).

## Design implications for our client (from `PROJECT.md` §6)

- Phase 1 uses **full refresh** (`W`) rather than incremental (`X`) for
  bid/ask display — this avoids having to correctly maintain a local book
  from deltas just to show top-of-book. Phase 3 (tick-level data) will need
  to switch to incremental and store every `X` message.
- Cache Security Definition (`d`) responses locally — tick size and
  contract size come from there, and the client shouldn't hardcode these
  per instrument.
- Because there's no historical replay available over FIX, a disconnect
  mid-session means the dashboard should show a visibly "stale/disconnected"
  state and resubscribe from scratch on reconnect — never silently keep
  showing the last known price as if it were live.
- The mock acceptor should reproduce the Security Definition → Security
  Status → Market Data Request sequencing above, so our client's request
  ordering gets exercised before it ever meets the real TT Price Gateway.

## Open items to verify directly against TT / the schema
- Exact tags for MarketDepth / MDUpdateType / SubscriptionRequestType
  values we intend to use — confirm against the downloaded schema, not
  from memory.
- Whether our CME instrument requires a specific ExDestination sub-market
  code (CME Group spans multiple underlying markets).
- Market data entitlement status for our account on CME — this is
  separate from order routing entitlement and can silently gate an
  otherwise-correct request.
