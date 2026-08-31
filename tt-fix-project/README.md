# TT FIX CME Trading Dashboard

Read [`PROJECT.md`](./PROJECT.md) first — it's the actual project charter
(aims, scope, decisions, hygiene rules). This README is just "how do I run
it."

Built and tested on: **Python 3.11, Windows**.

Note: the original plan (see `PROJECT.md` §6) was QuickFIX + FastAPI +
a mock acceptor. That's still the long-term direction, but QuickFIX's C++
core would not build against this machine's MSVC toolchain (a genuine
STL-level incompatibility, not a config issue — see the changelog in
`PROJECT.md` §12). Phase 1 currently runs on `simplefix` (message-only, no
built-in session layer) with a hand-rolled session in `src/fix_session.py`,
and a Streamlit dashboard instead of FastAPI. There is no mock acceptor yet
— you need real TT SIM/UAT credentials to test end to end.

## 1. Clone and set up

```powershell
git clone <this-repo-url>
cd tt-fix-project
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy config.example.env .env
```

Edit `.env` with your real TT SIM/UAT values once you have them
(`SENDER_COMP_ID`, `TARGET_COMP_ID`, `TT_USERNAME`, `TT_PASSWORD`, `HOST`,
`PORT`). Always point at TT's UAT/SIM endpoint while developing, never
production.

## 2. Run the dashboard

```powershell
streamlit run src\dashboard.py
```

Open the URL Streamlit prints (usually **http://localhost:8501**). Click
**Connect**, then **Subscribe** to a CME symbol to start seeing live
bid/ask. From there you can submit Market or Limit orders and watch
Execution Reports arrive below.

If `.env` isn't set up yet, the dashboard will tell you exactly what's
missing instead of failing silently.

## Repo layout

```
PROJECT.md                        # the actual charter - read this
README.md                         # this file
requirements.txt
config.example.env                # copy to .env, fill in real values
.gitignore

docs/tt-fix-reference/            # our own paraphrased FIX notes + links
  00-overview.md
  01-order-routing.md
  02-market-data.md

src/
  config.py                       # loads .env
  fix_session.py                  # hand-rolled FIX session on top of simplefix:
                                   #   logon/logout, heartbeats, TestRequest
                                   #   handling, market data subscription,
                                   #   NewOrderSingle (market/limit)
  dashboard.py                    # Streamlit UI

tests/                             # (add tests here as they're written)
```

## Known rough edges (read before debugging for an hour)

- **Single FIX session, not two.** `PROJECT.md` §6 calls for separate
  market data and order routing sessions. Phase 1 currently uses one
  session for both, as a documented, deliberate simplification (see
  `PROJECT.md` §6/§12). Split this before Phase 2.
- **No mock acceptor.** Testing currently requires real TT SIM/UAT
  credentials. Building a lightweight mock FIX acceptor (even a simple
  socket server that answers Logon and echoes a fake quote) would let you
  test `fix_session.py` without waiting on TT — worth doing before Phase 2.
- **Market data parsing assumes entry order.** `fix_session.py`'s
  `_handle_market_data` reads repeating-group entries positionally
  (`nth=i`) assuming Bid/Offer arrive in a consistent order per update.
  This holds for typical top-of-book feeds but isn't guaranteed by the FIX
  spec in general — worth hardening if TT's actual feed behaves
  differently (verify against TT's live docs once UAT access exists, per
  `PROJECT.md` §10).
- **Streamlit refresh is polling-based** (`st.fragment(run_every=1)`,
  1-second interval). Fine for Phase 1 top-of-book display; revisit before
  Phase 3 tick-level capture, where the original FastAPI+WebSocket
  reasoning in `PROJECT.md` §6 applies in full.

## Git workflow

One branch (`main`), no feature branches — see `PROJECT.md` section 8 for
why. Commit directly, small and often.
