"""
measure_latency.py

Sends N market orders and measures send-to-first-ack latency (time from
sending NewOrderSingle to receiving the first ExecutionReport, OrdStatus=New).
This measures our own code's overhead plus network round trip - against the
mock acceptor, that's ~localhost overhead only; against real TT SIM/UAT, it
becomes a genuine (if informal) latency measurement.

Run against the mock acceptor (default):
    python scripts/measure_latency.py --count 200

Run against real TT (once .env has real SIM/UAT values):
    python scripts/measure_latency.py --count 200 --real

Writes per-order latency samples to data/latency_run.csv and prints
p50/p95/p99/max.
"""

import argparse
import csv
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from fix_session import FixSession  # noqa: E402
from config import load_settings  # noqa: E402


def percentile(sorted_values, pct):
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def main():
    parser = argparse.ArgumentParser(description="Measure FIX order send-to-ack latency")
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--symbol", default="ES")
    parser.add_argument(
        "--real",
        action="store_true",
        help="Connect using .env settings (real TT) instead of the local mock acceptor",
    )
    parser.add_argument("--mock-host", default="127.0.0.1")
    parser.add_argument("--mock-port", type=int, default=5001)
    args = parser.parse_args()

    if args.real:
        settings = load_settings()
        host, port = settings.host, settings.port
        sender_comp_id, target_comp_id = settings.sender_comp_id, settings.target_comp_id
        account, password = settings.account, settings.tt_password
        heartbeat_interval = settings.heartbeat_interval
        print(f"Connecting to REAL TT endpoint {host}:{port} ...")
    else:
        host, port = args.mock_host, args.mock_port
        sender_comp_id, target_comp_id = "LATENCYTEST", "TT"
        account, password = "TESTACCT", None
        heartbeat_interval = 30
        print(f"Connecting to MOCK acceptor {host}:{port} ...")
        print("(start it first in another terminal: python src/mock_acceptor.py)")

    pending = {}  # cl_ord_id -> send_time
    samples = []  # list of (cl_ord_id, latency_seconds)
    done_event = threading.Event()

    def on_execution(report):
        cl_ord_id = report.get("cl_ord_id")
        if cl_ord_id is None:
            return
        cl_ord_id = cl_ord_id.decode() if isinstance(cl_ord_id, bytes) else cl_ord_id
        send_time = pending.pop(cl_ord_id, None)
        if send_time is not None:
            latency = time.time() - send_time
            samples.append((cl_ord_id, latency))
            if len(samples) >= args.count:
                done_event.set()

    fs = FixSession(
        host=host,
        port=port,
        sender_comp_id=sender_comp_id,
        target_comp_id=target_comp_id,
        account=account,
        password=password,
        heartbeat_interval=heartbeat_interval,
    )
    fs.on_execution = on_execution
    fs.connect_and_logon()
    time.sleep(0.5)

    print(f"Sending {args.count} market orders for {args.symbol} ...")
    for _ in range(args.count):
        cl_ord_id = fs.send_new_order(args.symbol, "buy", 1, order_type="market")
        pending[cl_ord_id] = time.time()
        time.sleep(0.02)  # small pacing gap - avoid overwhelming the mock/session

    done_event.wait(timeout=30)
    fs.disconnect()

    if not samples:
        print("No execution reports received - check connection/credentials.")
        return

    latencies_ms = sorted(lat * 1000 for _, lat in samples)

    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data"), exist_ok=True)
    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "latency_run.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["cl_ord_id", "latency_ms"])
        for cl_ord_id, lat in samples:
            writer.writerow([cl_ord_id, round(lat * 1000, 3)])

    print(f"\nReceived {len(samples)}/{args.count} acks.")
    print(f"p50: {percentile(latencies_ms, 50):.2f} ms")
    print(f"p95: {percentile(latencies_ms, 95):.2f} ms")
    print(f"p99: {percentile(latencies_ms, 99):.2f} ms")
    print(f"max: {max(latencies_ms):.2f} ms")
    print(f"Raw samples written to {csv_path}")


if __name__ == "__main__":
    main()
