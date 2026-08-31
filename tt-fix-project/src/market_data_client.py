"""
Market Data (Price Gateway) FIX session.

Responsibilities, and only these:
  - Log on to the market data session.
  - Request the security definition for one instrument.
  - Subscribe to top-of-book (full refresh) once the definition is known.
  - Publish the latest bid/ask into a thread-safe shared store the
    dashboard can read.

Deliberately uses full-refresh (MDUpdateType=0), not incremental, for
Phase 1 - see PROJECT.md section 6 for why. Do not add incremental-refresh
book maintenance here without updating that decision.

IMPORTANT: fromApp() runs on QuickFIX's own thread. Never block here -
only write into `self.book`, a plain dict guarded by a lock.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import quickfix as fix
import quickfix44 as fix44


class MarketDataBook:
    """Thread-safe holder for the latest bid/ask of one instrument."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bid: Optional[float] = None
        self._ask: Optional[float] = None
        self._last_update_ts: Optional[float] = None
        self._connected = False

    def update(self, bid: Optional[float], ask: Optional[float]) -> None:
        with self._lock:
            if bid is not None:
                self._bid = bid
            if ask is not None:
                self._ask = ask
            self._last_update_ts = time.time()

    def set_connected(self, connected: bool) -> None:
        with self._lock:
            self._connected = connected

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "bid": self._bid,
                "ask": self._ask,
                "last_update_ts": self._last_update_ts,
                "connected": self._connected,
            }


class MarketDataApplication(fix.Application):
    def __init__(self, security_id: str, exchange: str, account: str) -> None:
        super().__init__()
        self.security_id = security_id
        self.exchange = exchange
        self.account = account
        self.book = MarketDataBook()
        self._session_id: Optional[fix.SessionID] = None
        self._subscribed = False

    # --- QuickFIX lifecycle callbacks ---

    def onCreate(self, sessionID):
        self._session_id = sessionID

    def onLogon(self, sessionID):
        self.book.set_connected(True)
        self._request_security_definition()

    def onLogout(self, sessionID):
        self.book.set_connected(False)
        self._subscribed = False

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

        if mtype == fix.MsgType_SecurityDefinition:  # 'd'
            self._subscribe_market_data()
        elif mtype == fix.MsgType_MarketDataSnapshotFullRefresh:  # 'W'
            self._handle_snapshot(message)
        elif mtype == fix.MsgType_MarketDataIncrementalRefresh:  # 'X'
            # Not used in Phase 1 (see module docstring) - log only.
            pass
        elif mtype == fix.MsgType_MarketDataRequestReject:  # 'Y'
            # Surface this - a silent reject looks identical to "no data yet"
            # otherwise, which wastes hours of debugging.
            self.book.update(bid=None, ask=None)

    # --- outbound requests ---

    def _request_security_definition(self) -> None:
        request = fix44.SecurityDefinitionRequest()
        request.setField(fix.SecurityReqID("secdef-req-1"))
        request.setField(fix.SecurityRequestType(
            fix.SecurityRequestType_REQUEST_SECURITY_IDENTITY_AND_SPECIFICATIONS
        ))
        request.setField(fix.Symbol(self.security_id))
        request.setField(fix.SecurityExchange(self.exchange))
        fix.Session.sendToTarget(request, self._session_id)

    def _subscribe_market_data(self) -> None:
        if self._subscribed:
            return
        request = fix44.MarketDataRequest()
        request.setField(fix.MDReqID("mdreq-1"))
        request.setField(fix.SubscriptionRequestType(
            fix.SubscriptionRequestType_SNAPSHOT_PLUS_UPDATES
        ))
        request.setField(fix.MarketDepth(1))  # top of book only
        request.setField(fix.MDUpdateType(fix.MDUpdateType_FULL_REFRESH))

        entry_types = fix44.MarketDataRequest.NoMDEntryTypes()
        entry_types.setField(fix.MDEntryType(fix.MDEntryType_BID))
        request.addGroup(entry_types)
        entry_types.setField(fix.MDEntryType(fix.MDEntryType_OFFER))
        request.addGroup(entry_types)

        symbols = fix44.MarketDataRequest.NoRelatedSym()
        symbols.setField(fix.Symbol(self.security_id))
        symbols.setField(fix.SecurityExchange(self.exchange))
        request.addGroup(symbols)

        fix.Session.sendToTarget(request, self._session_id)
        self._subscribed = True

    # --- inbound handling ---

    def _handle_snapshot(self, message: fix.Message) -> None:
        bid = None
        ask = None
        try:
            n_entries = fix.NoMDEntries()
            message.getField(n_entries)
            group = fix44.MarketDataSnapshotFullRefresh.NoMDEntries()
            for i in range(1, n_entries.getValue() + 1):
                message.getGroup(i, group)
                entry_type = fix.MDEntryType()
                group.getField(entry_type)
                price = fix.MDEntryPx()
                group.getField(price)
                if entry_type.getValue() == fix.MDEntryType_BID:
                    bid = price.getValue()
                elif entry_type.getValue() == fix.MDEntryType_OFFER:
                    ask = price.getValue()
        except fix.FieldNotFound:
            pass
        self.book.update(bid=bid, ask=ask)
