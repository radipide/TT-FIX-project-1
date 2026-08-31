"""
mock_acceptor.py

A lightweight stand-in for TT FIX, for testing fix_session.py end to end
without needing real SIM/UAT credentials. This is NOT a spec-accurate FIX
acceptor - it only implements enough behavior to exercise our client code:

  - Accepts Logon (35=A), replies with a Logon ack immediately.
  - Replies to TestRequest (35=1) with a Heartbeat.
  - On MarketDataRequest (35=V): sends an immediate
    MarketDataSnapshotFullRefresh (35=W), then a random-walk
    MarketDataIncrementalRefresh (35=X) roughly once a second.
  - On NewOrderSingle (35=D): replies with a New (OrdStatus=0) Execution
    Report almost immediately, then a Filled (OrdStatus=2) Execution
    Report after a short randomized delay - this is what
    scripts/measure_latency.py times against.

Run with:
    python src/mock_acceptor.py [--port 5001]
"""

import argparse
import random
import socket
import threading
import time

import simplefix


class MockAcceptor:
    def __init__(self, host="127.0.0.1", port=5001):
        self.host = host
        self.port = port
        self._seq_num = 1
        self._lock = threading.Lock()

    def serve_forever(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(1)
        print(f"Mock TT acceptor listening on {self.host}:{self.port}")

        while True:
            conn, addr = server.accept()
            print(f"Client connected: {addr}")
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn):
        parser = simplefix.FixParser()
        conn.settimeout(1.0)
        running = True

        def send(msg):
            with self._lock:
                seq = self._seq_num
                self._seq_num += 1
            msg.append_pair(34, seq, header=True)
            msg.append_pair(49, "TT", header=True)  # SenderCompID (mock's perspective)
            msg.append_utc_timestamp(52, header=True)
            conn.sendall(msg.encode())

        def market_data_loop(symbol, bid, ask):
            while running:
                time.sleep(1)
                bid = round(bid + random.uniform(-0.25, 0.25), 2)
                ask = round(bid + random.uniform(0.25, 0.75), 2)
                msg = simplefix.FixMessage()
                msg.append_pair(8, "FIX.4.4")
                msg.append_pair(35, "X")  # MarketDataIncrementalRefresh
                msg.append_pair(268, 2)  # NoMDEntries
                msg.append_pair(279, 1)  # MDUpdateAction = Change
                msg.append_pair(269, 0)  # MDEntryType = Bid
                msg.append_pair(270, bid)
                msg.append_pair(55, symbol)
                msg.append_pair(279, 1)
                msg.append_pair(269, 1)  # MDEntryType = Ask
                msg.append_pair(270, ask)
                msg.append_pair(55, symbol)
                try:
                    send(msg)
                except OSError:
                    return

        try:
            while running:
                try:
                    data = conn.recv(4096)
                    if not data:
                        break
                    parser.append_buffer(data)
                    while True:
                        msg = parser.get_message()
                        if msg is None:
                            break
                        self._handle_message(msg, send, market_data_loop)
                except socket.timeout:
                    continue
        except OSError:
            pass
        finally:
            conn.close()
            running = False
            print("Client disconnected")

    def _handle_message(self, msg, send, market_data_loop):
        msg_type = msg.get(35)

        if msg_type == b"A":  # Logon
            reply = simplefix.FixMessage()
            reply.append_pair(8, "FIX.4.4")
            reply.append_pair(35, "A")
            reply.append_pair(98, 0)
            reply.append_pair(108, msg.get(108) or 30)
            send(reply)
            print("-> Logon ack sent")

        elif msg_type == b"1":  # TestRequest
            reply = simplefix.FixMessage()
            reply.append_pair(8, "FIX.4.4")
            reply.append_pair(35, "0")
            reply.append_pair(112, msg.get(112))
            send(reply)

        elif msg_type == b"V":  # MarketDataRequest
            symbol = msg.get(55) or b"ES"
            symbol = symbol.decode() if isinstance(symbol, bytes) else symbol
            bid, ask = 5000.00, 5000.25

            snapshot = simplefix.FixMessage()
            snapshot.append_pair(8, "FIX.4.4")
            snapshot.append_pair(35, "W")  # MarketDataSnapshotFullRefresh
            snapshot.append_pair(55, symbol)
            snapshot.append_pair(268, 2)  # NoMDEntries
            snapshot.append_pair(269, 0)
            snapshot.append_pair(270, bid)
            snapshot.append_pair(269, 1)
            snapshot.append_pair(270, ask)
            send(snapshot)
            print(f"-> Market data snapshot sent for {symbol}")

            threading.Thread(
                target=market_data_loop, args=(symbol, bid, ask), daemon=True
            ).start()

        elif msg_type == b"D":  # NewOrderSingle
            cl_ord_id = msg.get(11)
            symbol = msg.get(55)
            side = msg.get(54)
            qty = msg.get(38)
            price = msg.get(44)

            # Immediate "New" ack - this is what the latency harness times.
            ack = simplefix.FixMessage()
            ack.append_pair(8, "FIX.4.4")
            ack.append_pair(35, "8")  # ExecutionReport
            ack.append_pair(37, f"ORD-{cl_ord_id.decode()}")  # OrderID
            ack.append_pair(11, cl_ord_id)
            ack.append_pair(17, f"EXEC-{cl_ord_id.decode()}-1")  # ExecID
            ack.append_pair(150, "0")  # ExecType = New
            ack.append_pair(39, "0")  # OrdStatus = New
            ack.append_pair(55, symbol)
            ack.append_pair(54, side)
            ack.append_pair(38, qty)
            ack.append_pair(14, 0)  # CumQty
            ack.append_pair(151, qty)  # LeavesQty
            ack.append_pair(6, 0)  # AvgPx
            send(ack)

            # Simulated fill after a short randomized delay.
            def delayed_fill():
                time.sleep(random.uniform(0.05, 0.3))
                fill = simplefix.FixMessage()
                fill.append_pair(8, "FIX.4.4")
                fill.append_pair(35, "8")
                fill.append_pair(37, f"ORD-{cl_ord_id.decode()}")
                fill.append_pair(11, cl_ord_id)
                fill.append_pair(17, f"EXEC-{cl_ord_id.decode()}-2")
                fill.append_pair(150, "F")  # ExecType = Trade (fill)
                fill.append_pair(39, "2")  # OrdStatus = Filled
                fill.append_pair(55, symbol)
                fill.append_pair(54, side)
                fill.append_pair(38, qty)
                fill.append_pair(32, qty)  # LastQty
                fill.append_pair(31, price or 5000.00)  # LastPx
                fill.append_pair(14, qty)  # CumQty
                fill.append_pair(151, 0)  # LeavesQty
                fill.append_pair(6, price or 5000.00)  # AvgPx
                try:
                    send(fill)
                except OSError:
                    pass

            threading.Thread(target=delayed_fill, daemon=True).start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mock TT FIX acceptor for local testing")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()

    MockAcceptor(args.host, args.port).serve_forever()
