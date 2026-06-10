#!/usr/bin/env bash
# Bootstrap: build stock.db from scratch via Tushare, then run the full pipeline.
#
# Usage:
#   bash scripts/setup.sh
#
# Prerequisites:
#   - uv installed (https://docs.astral.sh/uv/)
#   - Tushare token configured in store/__init__.py or TUSHARE_TOKEN env var
#   - Network access to tushare.pro

set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== 1/5  stock_basic (全量股票列表) ==="
uv run python -m ingest.stock_basic

echo
echo "=== 2/5  trade_cal (交易日历) ==="
uv run python -m ingest.trade_cal

echo
echo "=== 3/5  backfill (全量日线, 默认近5年) ==="
uv run python -m ingest.backfill

echo
echo "=== 4/5  indicators 全量计算 ==="
uv run python -m indicators.kdj
uv run python -m indicators.zhixing

echo
echo "=== 5/5  strategy + export ==="
uv run python -m strategy.b1
uv run python -m indicators.golden_pit
uv run python -m strategy.b1_annotate_gp
uv run python -m strategy.next_day predict
uv run python export_web_data.py

echo
echo "✅ Done! 数据已就绪"
echo "   数据库: $(du -sh data/stock.db | cut -f1)"
echo "   后续每日更新: bash daily.sh"
