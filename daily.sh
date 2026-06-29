#!/usr/bin/env bash
# Daily refresh: incremental ingest → indicators → screens → next-day prediction → mainline → web export.
# Run after A-share close + Tushare data publication (~16:30 China time).
#
# Usage:
#   ./daily.sh
#
# All nine steps are idempotent — safe to re-run.

set -euo pipefail
cd "$(dirname "$0")"

echo "=== 1/9  ingest.incremental ==="
uv run python -m ingest.incremental

echo
echo "=== 2/9  indicators.kdj ==="
uv run python -m indicators.kdj

echo
echo "=== 3/9  indicators.zhixing ==="
uv run python -m indicators.zhixing

echo
echo "=== 4/9  strategy.b1 ==="
uv run python -m strategy.b1

echo
echo "=== 5/9  annotate b1 CSV with 黄金坑 ==="
uv run python -m indicators.golden_pit
uv run python -m strategy.b1_annotate_gp

echo
echo "=== 6/9  strategy.next_day ==="
uv run python -m strategy.next_day predict

echo
echo "=== 7/9  backfill mainline history for date picker ==="
uv run python backfill_mainline.py

echo
echo "=== 8/9  量化主线监控 ==="
uv run python sector_monitor.py

echo
echo "=== 9/9  export static web data ==="
uv run python export_web_data.py
