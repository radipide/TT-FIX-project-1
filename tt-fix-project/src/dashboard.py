"""
dashboard.py

Streamlit dashboard for the TT FIX project.

Run with:
    streamlit run src/dashboard.py

Reads connection details from .env (copy config.example.env to .env at the
repo root and fill in your real SIM/UAT values first - .env is gitignored
so real credentials never get committed).
"""

import os
import sys

import streamlit as st

# Allow running via `streamlit run src/dashboard.py` from the repo root.
sys.path.insert(0, os.path.dirname(__file__))
from fix_session import FixSession  # noqa: E402
from config import load_settings  # noqa: E402

st.set_page_config(page_title="TT FIX Dashboard", layout="wide")


def init_state():
    if "fix_session" not in st.session_state:
        st.session_state.fix_session = None
    if "connected" not in st.session_state:
        st.session_state.connected = False
    if "quotes" not in st.session_state:
        st.session_state.quotes = {}  # symbol -> {"bid": float, "ask": float}
    if "executions" not in st.session_state:
        st.session_state.executions = []


def connect(settings):
    fs = FixSession(
        host=settings.host,
        port=settings.port,
        sender_comp_id=settings.sender_comp_id,
        target_comp_id=settings.target_comp_id,
        account=settings.account,
        password=settings.tt_password or None,
        fix_version=settings.fix_version,
        heartbeat_interval=settings.heartbeat_interval,
    )

    def on_quote(symbol, bid, ask):
        prev = st.session_state.quotes.get(symbol, {})
        st.session_state.quotes[symbol] = {
            "bid": bid if bid is not None else prev.get("bid"),
            "ask": ask if ask is not None else prev.get("ask"),
        }

    def on_execution(report):
        st.session_state.executions.insert(0, report)

    def on_logon():
        st.session_state.connected = True

    def on_logout():
        st.session_state.connected = False

    fs.on_quote = on_quote
    fs.on_execution = on_execution
    fs.on_logon = on_logon
    fs.on_logout = on_logout

    fs.connect_and_logon()
    st.session_state.fix_session = fs


# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------

init_state()

st.title("TT FIX - Market Data & Order Entry")

try:
    settings = load_settings()
except RuntimeError as e:
    st.error(
        f"{e}\n\nCopy `config.example.env` to `.env` at the repo root and "
        "fill in your TT SIM/UAT credentials."
    )
    st.stop()

with st.sidebar:
    st.header("Connection")
    if not st.session_state.connected:
        if st.button("Connect"):
            try:
                connect(settings)
                st.rerun()
            except OSError as e:
                st.error(
                    f"Could not connect to {settings.host}:{settings.port} - {e}\n\n"
                    "Check HOST and PORT in .env, and that you're on TT's SIM/UAT "
                    "endpoint (not the placeholder example value)."
                )
    else:
        st.success("Connected")
        if st.button("Disconnect"):
            st.session_state.fix_session.disconnect()
            st.session_state.connected = False
            st.rerun()

    st.header("Instrument")
    symbol = st.text_input("CME Symbol", value=settings.default_symbol)
    if st.session_state.connected and st.button("Subscribe"):
        st.session_state.fix_session.subscribe_market_data(symbol)
        st.toast(f"Subscribed to {symbol}")


@st.fragment(run_every=1)
def live_quotes():
    st.subheader("Live Bid / Ask")
    if not st.session_state.quotes:
        st.info("No quotes yet - connect, then subscribe to an instrument.")
        return
    rows = [
        {"Symbol": sym, "Bid": q.get("bid"), "Ask": q.get("ask")}
        for sym, q in st.session_state.quotes.items()
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


live_quotes()

st.subheader("Place Order")
col1, col2, col3, col4 = st.columns(4)
with col1:
    order_symbol = st.text_input("Symbol", value=symbol, key="order_symbol")
with col2:
    side = st.selectbox("Side", ["buy", "sell"])
with col3:
    order_type = st.selectbox("Order Type", ["market", "limit"])
with col4:
    quantity = st.number_input("Quantity", min_value=1, value=1, step=1)

price = None
if order_type == "limit":
    price = st.number_input("Limit Price", min_value=0.0, value=0.0, step=0.25)

if st.button("Submit Order", disabled=not st.session_state.connected):
    fs = st.session_state.fix_session
    cl_ord_id = fs.send_new_order(
        symbol=order_symbol,
        side=side,
        quantity=int(quantity),
        order_type=order_type,
        price=price if order_type == "limit" else None,
    )
    st.success(f"Order sent - ClOrdID: {cl_ord_id}")

st.subheader("Execution Reports")
if st.session_state.executions:
    st.dataframe(st.session_state.executions, use_container_width=True, hide_index=True)
else:
    st.info("No execution reports yet.")
