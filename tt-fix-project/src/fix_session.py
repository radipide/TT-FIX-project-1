"""
fix_session.py

A minimal FIX session manager built on top of `simplefix`.

`simplefix` only builds/parses individual FIX messages - it does not manage
the session layer (logon, heartbeats, sequence numbers, reconnects). This
module fills that gap with just enough logic for:
  - Logon / Logout
  - Heartbeat / TestRequest handling (so TT doesn't disconnect us)
  - Outgoing sequence number tracking
  - Subscribing to market data (bid/ask) for a CME instrument
  - Sending NewOrderSingle (market and limit orders)

This is intentionally simple - no message store/replay, no resend logic.
That's fine for a first working version; production TT connectivity would
need more (persistent sequence numbers across restarts, resend requests,
etc.) but this gets the dashboard + basic order flow working end to end.
"""

import socket
import threading
import time
import logging

import simplefix

logger = logging.getLogger("fix_session")


class FixSession:
    def __init__(
        self,
        host,
        port,
        sender_comp_id,
        target_comp_id,
        username=None,
        password=None,
        fix_version="FIX.4.4",
        heartbeat_interval=30,
    ):
        self.host = host
        self.port = port
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.username = username
        self.password = password
        self.fix_version = fix_version
        self.heartbeat_interval = heartbeat_interval

        self._sock = None
        self._parser = simplefix.FixParser()
        self._seq_num = 1
        self._running = False
        self._logged_on = False
        self._last_sent_time = 0.0

        # Callbacks the dashboard (or any consumer) can set.
        # on_quote(symbol, bid, ask)
        self.on_quote = None
        # on_execution(exec_report_dict)
        self.on_execution = None
        # on_logon() / on_logout()
        self.on_logon = None
        self.on_logout = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect_and_logon(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=10)
        self._sock.settimeout(1.0)  # so the read loop can check self._running
        self._running = True

        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

        self._send_logon()

    def disconnect(self):
        if self._logged_on:
            self._send_logout()
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Low-level send/receive
    # ------------------------------------------------------------------

    def _new_message(self, msg_type):
        msg = simplefix.FixMessage()
        msg.append_pair(8, self.fix_version)
        msg.append_pair(35, msg_type)
        msg.append_pair(49, self.sender_comp_id)
        msg.append_pair(56, self.target_comp_id)
        msg.append_pair(34, self._seq_num)
        msg.append_utc_timestamp(52)
        return msg

    def _send(self, msg):
        raw = msg.encode()
        self._sock.sendall(raw)
        self._seq_num += 1
        self._last_sent_time = time.time()
        logger.debug("SENT: %s", raw.replace(b"\x01", b"|"))

    def _send_logon(self):
        msg = self._new_message(b"A")
        msg.append_pair(98, 0)  # EncryptMethod = None
        msg.append_pair(108, self.heartbeat_interval)
        if self.username:
            msg.append_pair(553, self.username)
        if self.password:
            msg.append_pair(554, self.password)
        self._send(msg)

    def _send_logout(self):
        msg = self._new_message(b"5")
        self._send(msg)

    def _send_heartbeat(self, test_req_id=None):
        msg = self._new_message(b"0")
        if test_req_id:
            msg.append_pair(112, test_req_id)
        self._send(msg)

    def _send_test_request(self):
        msg = self._new_message(b"1")
        msg.append_pair(112, "TEST")
        self._send(msg)

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def subscribe_market_data(self, symbol, md_req_id="MDR1"):
        """Subscribe to top-of-book bid/ask for a single CME symbol."""
        msg = self._new_message(b"V")  # MarketDataRequest
        msg.append_pair(262, md_req_id)  # MDReqID
        msg.append_pair(263, 1)  # SubscriptionRequestType = Snapshot+Updates
        msg.append_pair(264, 1)  # MarketDepth = top of book
        msg.append_pair(265, 0)  # MDUpdateType = Full refresh
        msg.append_pair(146, 1)  # NoRelatedSym
        msg.append_pair(55, symbol)  # Symbol

        msg.append_pair(267, 2)  # NoMDEntryTypes
        msg.append_pair(269, 0)  # MDEntryType = Bid
        msg.append_pair(269, 1)  # MDEntryType = Offer
        self._send(msg)

    # ------------------------------------------------------------------
    # Order entry
    # ------------------------------------------------------------------

    def send_new_order(self, symbol, side, quantity, order_type="market", price=None, cl_ord_id=None):
        """
        side: 'buy' or 'sell'
        order_type: 'market' or 'limit'
        price: required if order_type == 'limit'
        """
        if cl_ord_id is None:
            cl_ord_id = f"ORD{int(time.time() * 1000)}"

        msg = self._new_message(b"D")  # NewOrderSingle
        msg.append_pair(11, cl_ord_id)  # ClOrdID
        msg.append_pair(55, symbol)  # Symbol
        msg.append_pair(54, 1 if side.lower() == "buy" else 2)  # Side
        msg.append_utc_timestamp(60)  # TransactTime
        msg.append_pair(38, quantity)  # OrderQty

        if order_type.lower() == "limit":
            if price is None:
                raise ValueError("price is required for limit orders")
            msg.append_pair(40, 2)  # OrdType = Limit
            msg.append_pair(44, price)  # Price
        else:
            msg.append_pair(40, 1)  # OrdType = Market

        msg.append_pair(59, 0)  # TimeInForce = Day
        self._send(msg)
        return cl_ord_id

    # ------------------------------------------------------------------
    # Read loop / dispatch
    # ------------------------------------------------------------------

    def _heartbeat_loop(self):
        while self._running:
            time.sleep(1)
            if self._logged_on and time.time() - self._last_sent_time >= self.heartbeat_interval:
                self._send_heartbeat()

    def _read_loop(self):
        while self._running:
            try:
                data = self._sock.recv(4096)
                if not data:
                    logger.warning("Connection closed by remote end")
                    self._running = False
                    break
                self._parser.append_buffer(data)
                while True:
                    msg = self._parser.get_message()
                    if msg is None:
                        break
                    self._dispatch(msg)
            except socket.timeout:
                continue
            except OSError:
                break

    def _dispatch(self, msg):
        msg_type = msg.get(35)
        logger.debug("RECV type=%s", msg_type)

        if msg_type == b"A":  # Logon ack
            self._logged_on = True
            if self.on_logon:
                self.on_logon()

        elif msg_type == b"5":  # Logout
            self._logged_on = False
            if self.on_logout:
                self.on_logout()

        elif msg_type == b"1":  # TestRequest -> must respond with Heartbeat
            test_req_id = msg.get(112)
            self._send_heartbeat(test_req_id)

        elif msg_type == b"0":  # Heartbeat
            pass

        elif msg_type in (b"W", b"X"):  # MarketDataSnapshotFullRefresh / Incremental
            self._handle_market_data(msg)

        elif msg_type == b"8":  # ExecutionReport
            if self.on_execution:
                self.on_execution(self._execution_report_to_dict(msg))

        elif msg_type == b"j":  # BusinessMessageReject
            logger.warning("BusinessMessageReject: %s", msg.get(58))

        elif msg_type == b"3":  # Reject
            logger.warning("Session-level Reject: %s", msg.get(58))

    def _handle_market_data(self, msg):
        symbol = msg.get(55)
        bid = None
        ask = None

        num_entries = msg.get(268)  # NoMDEntries
        if num_entries is None:
            return
        num_entries = int(num_entries)

        # NOTE: repeating groups in simplefix are read positionally via
        # get(tag, nth=...). This assumes entries arrive in a consistent
        # Bid/Offer order per update, which holds for typical CME MD feeds
        # but a hardened implementation should walk pairs in original order.
        for i in range(1, num_entries + 1):
            entry_type = msg.get(269, nth=i)
            price = msg.get(270, nth=i)
            if entry_type == b"0":
                bid = float(price)
            elif entry_type == b"1":
                ask = float(price)

        if self.on_quote and (bid is not None or ask is not None):
            self.on_quote(symbol.decode() if symbol else "", bid, ask)

    @staticmethod
    def _execution_report_to_dict(msg):
        return {
            "cl_ord_id": msg.get(11),
            "symbol": msg.get(55),
            "side": msg.get(54),
            "ord_status": msg.get(39),
            "last_qty": msg.get(32),
            "last_px": msg.get(31),
            "text": msg.get(58),
        }
