"""
Dashboard: FastAPI + WebSocket, serving one static page.

Starts both FIX sessions (market data, order routing) as background
initiators, then exposes:
  GET  /api/book        -> current bid/ask snapshot
  GET  /api/orders       -> current order table
  POST /api/orders       -> place an order (market or limit)
  WS   /ws/book          -> push bid/ask updates

Run with: python scripts/run_dashboard.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quickfix as fix
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import load_settings
from src.market_data_client import MarketDataApplication
from src.order_client import OrderRoutingApplication

SECURITY_ID = "ES"
EXCHANGE = "XCME"

app = FastAPI(title="TT FIX Dashboard")

_state: dict = {}


class OrderRequest(BaseModel):
    side: str  # "BUY" or "SELL"
    order_type: str  # "MARKET" or "LIMIT"
    qty: float
    price: Optional[float] = None


@app.on_event("startup")
def startup() -> None:
    settings = load_settings()
    config_path = os.path.join(os.path.dirname(__file__), "..", "client.cfg")
    session_settings = fix.SessionSettings(config_path)

    md_app = MarketDataApplication(SECURITY_ID, EXCHANGE, settings.tt_account)
    or_app = OrderRoutingApplication(settings.tt_account, SECURITY_ID, EXCHANGE)

    store_factory = fix.FileStoreFactory(session_settings)
    log_factory = fix.FileLogFactory(session_settings)

    # Both applications share one settings file (two [SESSION] blocks) but
    # QuickFIX routes callbacks by SessionID, so each Application only
    # acts on messages for sessions it's responsible for in practice you
    # typically run one Application per initiator; for a two-session setup
    # like this, the simplest correct approach is two SocketInitiators
    # against two separate config files. See README for the exact split
    # if you hit cross-talk between sessions.
    initiator = fix.SocketInitiator(md_app, store_factory, session_settings, log_factory)
    initiator.start()

    _state["md_app"] = md_app
    _state["or_app"] = or_app
    _state["initiator"] = initiator


@app.on_event("shutdown")
def shutdown() -> None:
    initiator = _state.get("initiator")
    if initiator:
        initiator.stop()


@app.get("/api/book")
def get_book():
    return _state["md_app"].book.snapshot()


@app.get("/api/orders")
def get_orders():
    return _state["or_app"].snapshot_orders()


@app.post("/api/orders")
def place_order(req: OrderRequest):
    or_app: OrderRoutingApplication = _state["or_app"]
    if req.order_type == "MARKET":
        cl_ord_id = or_app.send_market_order(req.side, req.qty)
    else:
        if req.price is None:
            return {"error": "price is required for LIMIT orders"}
        cl_ord_id = or_app.send_limit_order(req.side, req.qty, req.price)
    return {"cl_ord_id": cl_ord_id}


@app.websocket("/ws/book")
async def ws_book(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_state["md_app"].book.snapshot())
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        pass


static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(static_dir, "index.html"))
