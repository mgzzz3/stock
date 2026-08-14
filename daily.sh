#!/usr/bin/env bash
# Daily refresh: incremental ingest → indicators → screens → prediction → sector rankings → web export.
# Run after A-share close + Tushare data publication (~16:30 China time).
#
# Usage:
#   ./daily.sh
#
# All ten steps are idempotent — safe to re-run.

set -euo pipefail
cd "$(dirname "$0")"

echo "=== 1/10  ingest.incremental ==="
uv run python -m ingest.incremental

echo
echo "=== 2/10  indicators.kdj ==="
uv run python -m indicators.kdj

echo
echo "=== 3/10  indicators.zhixing ==="
uv run python -m indicators.zhixing

echo
echo "=== 4/10  strategy.b1 ==="
uv run python -m strategy.b1

echo
echo "=== 5/10  annotate b1 CSV with 黄金坑 ==="
uv run python -m indicators.golden_pit
uv run python -m strategy.b1_annotate_gp

echo
echo "=== 6/10  strategy.next_day ==="
uv run python -m strategy.next_day predict

echo
echo "=== 7/10  backfill mainline history for date picker ==="
uv run python backfill_mainline.py

echo
echo "=== 8/10  量化主线监控 ==="
uv run python sector_monitor.py

echo
echo "=== 9/10  概念板块涨幅榜 ==="
if ! uv run python concept_monitor.py; then
  echo "warning: 概念板块数据获取失败，继续使用已有历史数据"
fi

echo
echo "=== 10/10  export static web data ==="
uv run python export_web_data.py
