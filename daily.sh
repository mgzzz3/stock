#!/usr/bin/env bash
# Daily refresh: incremental ingest → indicator rebuild → b1 screen → annotate → web export.
# Run after A-share close + Tushare data publication (~16:30 China time).
#
# Usage:
#   ./daily.sh
#
# All six steps are idempotent — safe to re-run.

set -euo pipefail
cd "$(dirname "$0")"

echo "=== 1/6  ingest.incremental ==="
uv run python -m ingest.incremental

echo
echo "=== 2/6  indicators.kdj ==="
uv run python -m indicators.kdj

echo
echo "=== 3/6  indicators.zhixing ==="
uv run python -m indicators.zhixing

echo
echo "=== 4/6  strategy.b1 ==="
uv run python -m strategy.b1

echo
echo "=== 5/6  annotate b1 CSV with 黄金坑 ==="
uv run python -m indicators.golden_pit
uv run python -m strategy.b1_annotate_gp

echo
echo "=== 6/6  export static web data ==="
uv run python export_web_data.py
