"""Strategy b2 — single-factor mean-reversion candidate.

Built on the b1 attribution finding (see strategy.b1_attribution) that
the inverse of c4 was the strongest standalone positive-lift signal over
the 2024-09 → 2026-05 window:

    trend_short < bull_bear
    (知行短期趋势线 < 知行多空线 — short-term trend below long-term)

Historical attribution showed positive +20d lift over baseline. b2 tests whether
that edge survives under realistic short-horizon execution rules —
see strategy.b2_backtest.

Stocks are ranked by `gap_pct = (bull_bear - trend_short) / bull_bear`,
descending — i.e., most below trend first. Caveat: bigger gap can mean
either "more oversold, bigger bounce" or "more broken, less likely to
recover" — the backtest decides which interpretation is operative.

Usage:
    uv run python -m strategy.b2                  # latest trade_date
    uv run python -m strategy.b2 20260514         # specific date
"""
import sys

from indicators import zhixing
from strategy import loader


def screen(on_date=None):
    on_date = on_date or loader.latest_trade_date()
    if on_date is None:
        raise RuntimeError("daily table is empty; run ingest.backfill first")

    z = zhixing.load(start=on_date, end=on_date)
    z = z.dropna(subset=["trend_short", "bull_bear"])
    z = z[z["bull_bear"] > 0].copy()  # guard div-by-zero
    z["gap_pct"] = (z["bull_bear"] - z["trend_short"]) / z["bull_bear"]

    hits = z[z["trend_short"] < z["bull_bear"]].copy()
    names = loader.stock_names()
    hits = (hits.merge(names, on="ts_code", how="left")
                .sort_values("gap_pct", ascending=False))
    return hits, len(z), on_date


def _report(hits, universe_n, on_date, top_n=30):
    print(f"Strategy b2 — c4_inv screen on {on_date}")
    print(f"Universe (stocks with zhixing data): {universe_n:,}")
    print(f"Matching (trend_short < bull_bear): {len(hits):,}")
    if hits.empty:
        return
    print(f"\nTop {top_n} by gap_pct (most below long-term trend first):")
    cols = ["ts_code", "name", "industry", "trend_short", "bull_bear", "gap_pct"]
    out = hits[cols].head(top_n).round(
        {"trend_short": 2, "bull_bear": 2, "gap_pct": 4}
    )
    print(out.to_string(index=False))


if __name__ == "__main__":
    on_date = sys.argv[1] if len(sys.argv) > 1 else None
    hits, universe_n, used_date = screen(on_date)
    _report(hits, universe_n, used_date)
