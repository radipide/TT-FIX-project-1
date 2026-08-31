"""
Order Routing (Order Gateway) FIX session.

Rule enforced here (see PROJECT.md section 6): order state is a projection
of Execution Reports we have actually received from TT - never set
optimistically at send time. `self.orders` is only ever written from
fromApp().
"""
from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import quickfix as fix
import quickfix44 as fix44


@dataclass
class OrderState:
    cl_ord_id: str
    side: str
    order_type: str
    qty: float
    price: Optional[float]
    status: str = "PENDING_NEW"
    sent_ts_ns: Optional[int] = None
    ack_ts_ns: Optional[int] = None

    @property
    def latency_ms(self) -> Optional[float]:
        if self.sent_ts_ns is None or self.ack_ts_ns is None:
            return None
        return (self.ack_ts_ns - self.sent_ts_ns) / 1_000_000


class OrderRoutingApplication(fix.Application):
    def __init__(self, account: str, security_id: str, exchange: str) -> None:
        super().__init__()
        self.account = account
        self.security_id = security_id
        self.exchange = exchange
        self._session_id: Optional[fix.SessionID] = None
        self._connected = False
        self._id_counter = itertools.count(1)
        self._lock = threading.Lock()
        self.orders: dict[str, OrderState] = {}

    # --- lifecycle ---

    def onCreate(self, sessionID):
        self._session_id = sessionID

    def onLogon(self, sessionID):
        self._connected = True

    def onLogout(self, sessionID):
        self._connected = False

    def toAdmin(self, message, sessionID):
        pass

    def fromAdmin(self, message, sessionID):
        pass

    def toApp(self, message, sessionID):
        pass

    def fromApp(self, message, sessionID):
        msg_type = fix.MsgType()
        message.getHeader().getField(msg_type)
        if msg_type.getValue() != fix.MsgType_ExecutionReport:
            return

        cl_ord_id = fix.ClOrdID()
        message.getField(cl_ord_id)
        ord_status = fix.OrdStatus()
        message.getField(ord_status)

        with self._lock:
            state = self.orders.get(cl_ord_id.getValue())
            if state is None:
                return
            state.ack_ts_ns = time.perf_counter_ns()
            state.status = self._status_label(ord_status.getValue())

    @staticmethod
    def _status_label(ord_status: str) -> str:
        return {
            fix.OrdStatus_NEW: "WORKING",
            fix.OrdStatus_PARTIALLY_FILLED: "PARTIALLY_FILLED",
            fix.OrdStatus_FILLED: "FILLED",
            fix.OrdStatus_CANCELED: "CANCELED",
            fix.OrdStatus_REJECTED: "REJECTED",
            fix.OrdStatus_PENDING_CANCEL: "PENDING_CANCEL",
        }.get(ord_status, f"UNKNOWN({ord_status})")

    # --- outbound ---

    def _next_cl_ord_id(self) -> str:
        return f"ord-{int(time.time())}-{next(self._id_counter)}"

    def send_market_order(self, side: str, qty: float) -> str:
        return self._send_order(side=side, qty=qty, order_type="MARKET", price=None)

    def send_limit_order(self, side: str, qty: float, price: float) -> str:
        return self._send_order(side=side, qty=qty, order_type="LIMIT", price=price)

    def _send_order(
        self, side: str, qty: float, order_type: str, price: Optional[float]
    ) -> str:
        if not self._connected or self._session_id is None:
            raise RuntimeError("Order session is not logged on")

        cl_ord_id = self._next_cl_ord_id()
        order = fix44.NewOrderSingle()
        order.setField(fix.ClOrdID(cl_ord_id))
        order.setField(fix.Symbol(self.security_id))
        order.setField(fix.SecurityExchange(self.exchange))
        order.setField(fix.Side(fix.Side_BUY if side == "BUY" else fix.Side_SELL))
        order.setField(fix.OrderQty(qty))
        order.setField(fix.TimeInForce(fix.TimeInForce_DAY))
        order.setField(fix.Account(self.account))
        order.getHeader().setField(fix.SendingTime())

        if order_type == "MARKET":
            order.setField(fix.OrdType(fix.OrdType_MARKET))
        else:
            order.setField(fix.OrdType(fix.OrdType_LIMIT))
            order.setField(fix.Price(price))

        state = OrderState(
            cl_ord_id=cl_ord_id,
            side=side,
            order_type=order_type,
            qty=qty,
            price=price,
        )
        with self._lock:
            self.orders[cl_ord_id] = state

        state.sent_ts_ns = time.perf_counter_ns()
        fix.Session.sendToTarget(order, self._session_id)
        return cl_ord_id

    def snapshot_orders(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "cl_ord_id": o.cl_ord_id,
                    "side": o.side,
                    "order_type": o.order_type,
                    "qty": o.qty,
                    "price": o.price,
                    "status": o.status,
                    "latency_ms": o.latency_ms,
                }
                for o in self.orders.values()
            ]
