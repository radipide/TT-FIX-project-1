"""
Fires N market orders against the running order-routing session, records
send-to-ack latency for each, and reports p50/p95/p99/max.

Uses time.perf_counter_ns() throughout - never time.time(), which is not
monotonic and is too coarse for this purpose.

Usage (with the dashboard app already running):
    python scripts/measure_latency.py --count 200 --side BUY --qty 1
"""
from __future__ import annotations

import argparse
import csv
import statistics
import time
from pathlib import Path

import requests

DASHBOARD_URL = "http://localhost:8000"


def percentile(data: list[float], pct: float) -> float:
    data_sorted = sorted(data)
    idx = int(len(data_sorted) * pct)
    idx = min(idx, len(data_sorted) - 1)
    return data_sorted[idx]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--side", choices=["BUY", "SELL"], default="BUY")
    parser.add_argument("--qty", type=float, default=1)
    parser.add_argument("--delay-s", type=float, default=0.2,
                         help="pause between order submissions")
    args = parser.parse_args()

    cl_ord_ids = []
    for _ in range(args.count):
        resp = requests.post(
            f"{DASHBOARD_URL}/api/orders",
            json={"side": args.side, "order_type": "MARKET", "qty": args.qty},
            timeout=5,
        )
        resp.raise_for_status()
        cl_ord_ids.append(resp.json()["cl_ord_id"])
        time.sleep(args.delay_s)

    # Give the last few orders time to come back before reading state.
    time.sleep(1.0)

    resp = requests.get(f"{DASHBOARD_URL}/api/orders", timeout=5)
    orders_by_id = {o["cl_ord_id"]: o for o in resp.json()}

    latencies = []
    rows = []
    for cl_ord_id in cl_ord_ids:
        order = orders_by_id.get(cl_ord_id)
        if order and order["latency_ms"] is not None:
            latencies.append(order["latency_ms"])
            rows.append(order)

    if not latencies:
        print("No acked orders - is the mock acceptor / UAT session running?")
        return

    out_path = Path(__file__).parent.parent / "data" / "latency_run.csv"
    out_path.parent.mkdir(exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"Orders sent: {args.count}, acked: {len(latencies)}")
    print(f"p50: {percentile(latencies, 0.50):.2f} ms")
    print(f"p95: {percentile(latencies, 0.95):.2f} ms")
    print(f"p99: {percentile(latencies, 0.99):.2f} ms")
    print(f"max: {max(latencies):.2f} ms")
    print(f"mean: {statistics.mean(latencies):.2f} ms")
    print(f"Raw data written to {out_path}")


if __name__ == "__main__":
    main()
