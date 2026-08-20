#!/usr/bin/env bash
# Daily refresh: incremental ingest → indicators → screens → prediction → sector rankings → web export.
# Run after A-share close + Tushare data publication (~16:30 China time).
#
# Usage:
#   ./daily.sh
#
# All eleven steps are idempotent — safe to re-run.

set -euo pipefail
cd "$(dirname "$0")"

echo "=== 1/11  ingest.incremental ==="
uv run python -m ingest.incremental

echo
echo "=== 2/11  ingest.fundamentals ==="
if ! uv run python -m ingest.fundamentals; then
  echo "warning: 财务快照更新失败，继续使用已有点时数据"
fi

echo
echo "=== 3/11  indicators.kdj ==="
uv run python -m indicators.kdj

echo
echo "=== 4/11  indicators.zhixing ==="
uv run python -m indicators.zhixing

echo
echo "=== 5/11  strategy.b1 ==="
uv run python -m strategy.b1

echo
echo "=== 6/11  annotate b1 CSV with 黄金坑 ==="
uv run python -m indicators.golden_pit
uv run python -m strategy.b1_annotate_gp

echo
echo "=== 7/11  strategy.next_day ==="
uv run python -m strategy.next_day predict

echo
echo "=== 8/11  backfill mainline history for date picker ==="
uv run python backfill_mainline.py

echo
echo "=== 9/11  量化主线监控 ==="
uv run python sector_monitor.py

echo
echo "=== 10/11  概念板块涨幅榜 ==="
if ! uv run python concept_monitor.py; then
  echo "warning: 概念板块数据获取失败，继续使用已有历史数据"
fi

echo
echo "=== 11/11  export static web data ==="
uv run python export_web_data.py
