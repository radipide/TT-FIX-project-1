"""
spread_engine.py

Computes weighted spread values (e.g. HO*42-CL, BZ-CL) from live leg
prices, maintains rolling mean/stddev over a sliding TIME window (not a
fixed tick count - ticks arrive irregularly), tracks high/low of day, and
emits entry/exit signals based on a z-score threshold.

Design notes:
  - Rolling stats use an O(1)-amortized sliding window: a deque of
    (timestamp, value) pairs plus running sum/sum-of-squares, so cost per
    tick doesn't grow with window size or session length. This matters
    because this runs on every tick, same latency discipline as the FIX
    session code (see .claude/skills/git-hygiene/SKILL.md section 8).
  - No historical backfill (per current setup - live FIX only): stats
    start empty each run and need `window_seconds` of live ticks before
    they're meaningful. `RollingWindowStats.count` / `.is_warm` tell you
    whether to trust the numbers yet.
  - High/low of day resets on UTC date change, matching FIX's own
    UTC-only timestamp convention (tag 52/60).
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional


class RollingWindowStats:
    """O(1)-amortized rolling mean/stddev over a sliding time window,
    plus running high/low of the current UTC day."""

    def __init__(self, window_seconds: float):
        self.window_seconds = window_seconds
        self._values = deque()  # (timestamp, value)
        self._sum = 0.0
        self._sumsq = 0.0
        self._day_high: Optional[float] = None
        self._day_low: Optional[float] = None
        self._day_start_date = None

    def add(self, value: float, timestamp: Optional[float] = None) -> None:
        ts = timestamp if timestamp is not None else time.time()

        current_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        if self._day_start_date != current_date:
            self._day_start_date = current_date
            self._day_high = value
            self._day_low = value
        else:
            self._day_high = value if self._day_high is None else max(self._day_high, value)
            self._day_low = value if self._day_low is None else min(self._day_low, value)

        self._values.append((ts, value))
        self._sum += value
        self._sumsq += value * value
        self._evict_old(ts)

    def _evict_old(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._values and self._values[0][0] < cutoff:
            _, v = self._values.popleft()
            self._sum -= v
            self._sumsq -= v * v

    @property
    def count(self) -> int:
        return len(self._values)

    @property
    def is_warm(self) -> bool:
        """True once the window has at least 2 points spanning close to
        the full window duration - a rough readiness check. Adjust the
        minimum count if your tick rate is very low."""
        if len(self._values) < 2:
            return False
        span = self._values[-1][0] - self._values[0][0]
        return span >= self.window_seconds * 0.8

    @property
    def mean(self) -> Optional[float]:
        n = len(self._values)
        return self._sum / n if n else None

    @property
    def stddev(self) -> Optional[float]:
        n = len(self._values)
        if n < 2:
            return None
        variance = (self._sumsq - (self._sum ** 2) / n) / (n - 1)
        return math.sqrt(max(variance, 0.0))

    @property
    def day_high(self) -> Optional[float]:
        return self._day_high

    @property
    def day_low(self) -> Optional[float]:
        return self._day_low

    def zscore(self, value: float) -> Optional[float]:
        mean, stddev = self.mean, self.stddev
        if mean is None or not stddev:
            return None
        return (value - mean) / stddev


@dataclass
class SpreadDefinition:
    """A weighted linear combination of leg prices, e.g.
    {"HO": 42, "CL": -1} for HO*42-CL, or {"BZ": 1, "CL": -1} for BZ-CL."""
    name: str
    legs: dict  # symbol -> weight


@dataclass
class SpreadState:
    definition: SpreadDefinition
    stats: RollingWindowStats
    last_value: Optional[float] = None
    signal_state: str = "NONE"  # NONE, ARMED_SHORT, SHORT, ARMED_LONG, LONG
    entry_time: Optional[float] = None
    _pending_value: Optional[float] = None
    _last_bar_second: Optional[int] = None


class SpreadEngine:
    """Tracks multiple legs' latest prices, computes configured spread
    values whenever any leg updates, samples them into 1-second bars (last
    tick per second, not raw tick-by-tick), and evaluates entry/exit
    signals on that 1-second series.

    Entry logic is confirmation-based, not extreme-triggered: crossing
    beyond entry_zscore ARMS a side, but the actual entry only fires once
    the z-score re-enters back inside that threshold (trading the start of
    the reversion, not the peak). Exit fires on reversion to exit_zscore,
    OR on max_holding_seconds elapsed, whichever comes first.
    """

    def __init__(
        self,
        spread_definitions: list,
        window_seconds: float = 300,
        entry_zscore: float = 2.0,
        exit_zscore: float = 0.5,
        max_holding_seconds: float = 90 * 60,
        price_field: str = "mid",  # "mid", "bid", or "ask"
    ):
        self.window_seconds = window_seconds
        self.entry_zscore = entry_zscore
        self.exit_zscore = exit_zscore
        self.max_holding_seconds = max_holding_seconds
        self.price_field = price_field

        self._leg_prices = {}  # symbol -> {"bid":..., "ask":...}
        self.spreads = {
            d.name: SpreadState(definition=d, stats=RollingWindowStats(window_seconds))
            for d in spread_definitions
        }

        # Callback: on_signal(spread_name, signal, value, zscore)
        self.on_signal: Optional[Callable] = None
        # Callback: on_update(spread_name, state) - fires on every recompute,
        # useful for a dashboard to redraw without polling internals directly.
        self.on_update: Optional[Callable] = None

    def _leg_price(self, symbol: str) -> Optional[float]:
        q = self._leg_prices.get(symbol)
        if not q:
            return None
        bid, ask = q.get("bid"), q.get("ask")
        if self.price_field == "bid":
            return bid
        if self.price_field == "ask":
            return ask
        if bid is not None and ask is not None:
            return (bid + ask) / 2
        return bid if bid is not None else ask

    def on_quote(self, symbol: str, bid: Optional[float], ask: Optional[float],
                 timestamp: Optional[float] = None) -> None:
        """Wire this directly as a FixSession.on_quote callback. `timestamp`
        is normally left None (uses real time) - only override it in tests
        that need to simulate elapsed time without actually sleeping."""
        prev = self._leg_prices.get(symbol, {})
        self._leg_prices[symbol] = {
            "bid": bid if bid is not None else prev.get("bid"),
            "ask": ask if ask is not None else prev.get("ask"),
        }
        self._recompute_affected(symbol, timestamp)

    def _recompute_affected(self, changed_symbol: str, timestamp: Optional[float] = None) -> None:
        now = timestamp if timestamp is not None else time.time()
        for state in self.spreads.values():
            if changed_symbol not in state.definition.legs:
                continue

            prices = {sym: self._leg_price(sym) for sym in state.definition.legs}
            if any(p is None for p in prices.values()):
                continue  # not all legs have a price yet

            value = sum(weight * prices[sym] for sym, weight in state.definition.legs.items())
            state.last_value = value

            # Sample into 1-second bars: only push into rolling stats when
            # we cross a new second boundary, using the last value seen in
            # the second that just closed (standard last-tick-of-bar
            # sampling). This is what "1-second data instead of tick
            # level" means in practice - it smooths out sub-second noise
            # that pure tick-by-tick would react to.
            current_second = int(now)
            if state._last_bar_second is None:
                state._last_bar_second = current_second
                state._pending_value = value
            elif current_second != state._last_bar_second:
                # Second boundary crossed - close the previous bar using
                # its last observed value, then start a new pending bar.
                state.stats.add(state._pending_value, timestamp=state._last_bar_second)
                state._last_bar_second = current_second
                state._pending_value = value
                if self.on_update:
                    self.on_update(state.definition.name, state)
                self._evaluate_signal(state, now)
            else:
                state._pending_value = value

    def _evaluate_signal(self, state: SpreadState, now: float) -> None:
        name = state.definition.name

        # Time-based exit takes priority over z-score exit logic - a
        # position that's been open past max_holding_seconds closes
        # regardless of where the z-score currently sits.
        if state.signal_state in ("SHORT", "LONG") and state.entry_time is not None:
            if now - state.entry_time >= self.max_holding_seconds:
                exit_signal = "SHORT_TIME_EXIT" if state.signal_state == "SHORT" else "LONG_TIME_EXIT"
                state.signal_state = "NONE"
                state.entry_time = None
                if self.on_signal:
                    self.on_signal(name, exit_signal, state.last_value,
                                    state.stats.zscore(state.last_value))
                return

        if not state.stats.is_warm:
            return
        z = state.stats.zscore(state.last_value)
        if z is None:
            return

        if state.signal_state == "NONE":
            # Arm (don't enter yet) when z first breaches the extreme.
            if z >= self.entry_zscore:
                state.signal_state = "ARMED_SHORT"
            elif z <= -self.entry_zscore:
                state.signal_state = "ARMED_LONG"

        elif state.signal_state == "ARMED_SHORT":
            # Entry confirmation: z has come back inside the threshold,
            # i.e. the reversion has started - enter now, not at the peak.
            if z < self.entry_zscore:
                state.signal_state = "SHORT"
                state.entry_time = now
                if self.on_signal:
                    self.on_signal(name, "SHORT_ENTRY", state.last_value, z)

        elif state.signal_state == "ARMED_LONG":
            if z > -self.entry_zscore:
                state.signal_state = "LONG"
                state.entry_time = now
                if self.on_signal:
                    self.on_signal(name, "LONG_ENTRY", state.last_value, z)

        elif state.signal_state == "SHORT" and z <= self.exit_zscore:
            state.signal_state = "NONE"
            state.entry_time = None
            if self.on_signal:
                self.on_signal(name, "SHORT_EXIT", state.last_value, z)

        elif state.signal_state == "LONG" and z >= -self.exit_zscore:
            state.signal_state = "NONE"
            state.entry_time = None
            if self.on_signal:
                self.on_signal(name, "LONG_EXIT", state.last_value, z)
