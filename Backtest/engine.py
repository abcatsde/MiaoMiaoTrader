from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, List


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class BacktestResult:
    total_trades: int
    win_rate: float
    total_pnl: float
    avg_pnl: float


class BacktestEngine:
    """Simple backtest engine using close-to-close signals.

    signal_fn returns: 1 (long), -1 (short), 0 (flat)
    """

    def run(
        self,
        candles: Iterable[Candle],
        signal_fn: Callable[[Candle], int],
    ) -> BacktestResult:
        candles_list = list(candles)
        if len(candles_list) < 2:
            return BacktestResult(0, 0.0, 0.0, 0.0)

        pnls: List[float] = []
        position = 0
        entry_price = 0.0

        for candle in candles_list:
            signal = int(signal_fn(candle))
            if signal not in (-1, 0, 1):
                signal = 0

            if position == 0 and signal != 0:
                position = signal
                entry_price = candle.close
                continue

            if position != 0 and signal == 0:
                pnl = (candle.close - entry_price) * position
                pnls.append(pnl)
                position = 0
                entry_price = 0.0
                continue

            if position != 0 and signal != position:
                pnl = (candle.close - entry_price) * position
                pnls.append(pnl)
                position = signal
                entry_price = candle.close

        if position != 0:
            pnl = (candles_list[-1].close - entry_price) * position
            pnls.append(pnl)

        total_trades = len(pnls)
        total_pnl = sum(pnls)
        win_rate = (
            sum(1 for p in pnls if p > 0) / total_trades if total_trades > 0 else 0.0
        )
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0.0
        return BacktestResult(total_trades, win_rate, total_pnl, avg_pnl)
