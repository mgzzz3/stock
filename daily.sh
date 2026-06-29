#!/usr/bin/env bash
# Daily refresh: incremental ingest → indicators → screens → next-day prediction → web export.
# Run after A-share close + Tushare data publication (~16:30 China time).
#
# Usage:
#   ./daily.sh
#
# All seven steps are idempotent — safe to re-run.

set -euo pipefail
cd "$(dirname "$0")"

echo "=== 1/7  ingest.incremental ==="
uv run python -m ingest.incremental

echo
echo "=== 2/7  indicators.kdj ==="
uv run python -m indicators.kdj

echo
echo "=== 3/7  indicators.zhixing ==="
uv run python -m indicators.zhixing

echo
echo "=== 4/7  strategy.b1 ==="
uv run python -m strategy.b1

echo
echo "=== 5/7  annotate b1 CSV with 黄金坑 ==="
uv run python -m indicators.golden_pit
uv run python -m strategy.b1_annotate_gp

echo
echo "=== 6/7  strategy.next_day ==="
uv run python -m strategy.next_day predict

echo
echo "=== 7/7  export static web data ==="
uv run python export_web_data.py

echo
echo "=== 8/8  量化主线监控 ==="
uv run python sector_monitor.py
