"""
A minimal stand-in for TT's FIX acceptor, for development before UAT
credentials exist. This is NOT throwaway code - it stays in the repo as
the permanent test double (see PROJECT.md section 1 and section 3).

What it does:
  - Accepts logons on both sessions (order routing, market data).
  - On a Security Definition Request, replies with one fake Security
    Definition.
  - On a Market Data Request, immediately sends a snapshot, then a random
    walk of snapshots every ~1 second.
  - On a New Order Single, replies with an ack Execution Report after a
    randomized delay (to make the latency harness meaningful), then a fill.

Run with: python scripts/run_mock_acceptor.py
"""
from __future__ import annotations

import random
import threading
import time

import quickfix as fix
import quickfix44 as fix44


class MockAcceptorApplication(fix.Application):
    def __init__(self) -> None:
        super().__init__()
        self._sessions: dict[str, fix.SessionID] = {}
        self._mid_price = 5000.00
        self._order_seq = 0

    def onCreate(self, sessionID):
        pass

    def onLogon(self, sessionID):
        self._sessions[str(sessionID)] = sessionID
        print(f"[mock] logon: {sessionID}")

    def onLogout(self, sessionID):
        self._sessions.pop(str(sessionID), None)
        print(f"[mock] logout: {sessionID}")

    def toAdmin(self, message, sessionID):
        pass

    def fromAdmin(self, message, sessionID):
        pass

    def toApp(self, message, sessionID):
        pass

    def fromApp(self, message, sessionID):
        msg_type = fix.MsgType()
        message.getHeader().getField(msg_type)
        mtype = msg_type.getValue()

        if mtype == fix.MsgType_SecurityDefinitionRequest:
            self._reply_security_definition(message, sessionID)
        elif mtype == fix.MsgType_MarketDataRequest:
            self._start_market_data_stream(sessionID)
        elif mtype == fix.MsgType_NewOrderSingle:
            self._handle_new_order(message, sessionID)

    # --- security definition ---

    def _reply_security_definition(self, message, sessionID):
        req_id = fix.SecurityReqID()
        message.getField(req_id)
        symbol = fix.Symbol()
        message.getField(symbol)
        exchange = fix.SecurityExchange()
        message.getField(exchange)

        response = fix44.SecurityDefinition()
        response.setField(fix.SecurityReqID(req_id.getValue()))
        response.setField(fix.SecurityResponseID("secdef-resp-1"))
        response.setField(fix.Symbol(symbol.getValue()))
        response.setField(fix.SecurityExchange(exchange.getValue()))
        response.setField(fix.SecurityType(fix.SecurityType_FUTURE))
        fix.Session.sendToTarget(response, sessionID)

    # --- market data ---

    def _start_market_data_stream(self, sessionID):
        thread = threading.Thread(
            target=self._stream_prices, args=(sessionID,), daemon=True
        )
        thread.start()

    def _stream_prices(self, sessionID):
        tick = 0.25
        while str(sessionID) in self._sessions:
            self._mid_price += random.choice([-1, 1]) * tick
            bid = round(self._mid_price - tick, 2)
            ask = round(self._mid_price + tick, 2)
            self._send_snapshot(sessionID, bid, ask)
            time.sleep(1.0)

    def _send_snapshot(self, sessionID, bid: float, ask: float):
        snapshot = fix44.MarketDataSnapshotFullRefresh()
        snapshot.setField(fix.Symbol("ES"))

        bid_group = fix44.MarketDataSnapshotFullRefresh.NoMDEntries()
        bid_group.setField(fix.MDEntryType(fix.MDEntryType_BID))
        bid_group.setField(fix.MDEntryPx(bid))
        snapshot.addGroup(bid_group)

        ask_group = fix44.MarketDataSnapshotFullRefresh.NoMDEntries()
        ask_group.setField(fix.MDEntryType(fix.MDEntryType_OFFER))
        ask_group.setField(fix.MDEntryPx(ask))
        snapshot.addGroup(ask_group)

        fix.Session.sendToTarget(snapshot, sessionID)

    # --- orders ---

    def _handle_new_order(self, message, sessionID):
        cl_ord_id = fix.ClOrdID()
        message.getField(cl_ord_id)
        symbol = fix.Symbol()
        message.getField(symbol)
        side = fix.Side()
        message.getField(side)
        qty = fix.OrderQty()
        message.getField(qty)

        self._order_seq += 1
        order_id = f"mock-order-{self._order_seq}"

        # Randomized ack delay so the latency harness has something to
        # measure - tune this to simulate different conditions.
        delay_s = random.uniform(0.005, 0.080)
        threading.Timer(
            delay_s,
            self._ack_and_fill,
            args=(sessionID, cl_ord_id.getValue(), order_id, symbol.getValue(),
                  side.getValue(), qty.getValue()),
        ).start()

    def _ack_and_fill(self, sessionID, cl_ord_id, order_id, symbol, side, qty):
        ack = fix44.ExecutionReport()
        ack.setField(fix.OrderID(order_id))
        ack.setField(fix.ClOrdID(cl_ord_id))
        ack.setField(fix.ExecID(f"{order_id}-ack"))
        ack.setField(fix.ExecType(fix.ExecType_NEW))
        ack.setField(fix.OrdStatus(fix.OrdStatus_NEW))
        ack.setField(fix.Symbol(symbol))
        ack.setField(fix.Side(side))
        ack.setField(fix.LeavesQty(qty))
        ack.setField(fix.CumQty(0))
        ack.setField(fix.AvgPx(0))
        fix.Session.sendToTarget(ack, sessionID)

        # Immediately fill, for simplicity - extend this to partials later.
        fill = fix44.ExecutionReport()
        fill.setField(fix.OrderID(order_id))
        fill.setField(fix.ClOrdID(cl_ord_id))
        fill.setField(fix.ExecID(f"{order_id}-fill"))
        fill.setField(fix.ExecType(fix.ExecType_TRADE))
        fill.setField(fix.OrdStatus(fix.OrdStatus_FILLED))
        fill.setField(fix.Symbol(symbol))
        fill.setField(fix.Side(side))
        fill.setField(fix.LeavesQty(0))
        fill.setField(fix.CumQty(qty))
        fill.setField(fix.AvgPx(self._mid_price))
        fix.Session.sendToTarget(fill, sessionID)
