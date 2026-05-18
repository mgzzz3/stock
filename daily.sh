#!/usr/bin/env bash
# Daily refresh: incremental ingest → indicator rebuild → b1 screen → annotate.
# Run after A-share close + Tushare data publication (~16:30 China time).
#
# Usage:
#   ./daily.sh
#
# All five steps are idempotent — safe to re-run.

set -euo pipefail
cd "$(dirname "$0")"

echo "=== 1/5  ingest.incremental ==="
uv run python -m ingest.incremental

echo
echo "=== 2/5  indicators.kdj ==="
uv run python -m indicators.kdj

echo
echo "=== 3/5  indicators.zhixing ==="
uv run python -m indicators.zhixing

echo
echo "=== 4/5  strategy.b1 ==="
uv run python -m strategy.b1

echo
echo "=== 5/5  annotate b1 CSV with 黄金坑 ==="
uv run python -m indicators.golden_pit
uv run python -m strategy.b1_annotate_gp
