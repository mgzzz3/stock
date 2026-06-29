"""
backfill_mainline.py — 补充历史日期的主线排行数据

从数据库直接查询，批量计算并写入 sector_ranking_history 表，
供前端日期选择器自由切换查看历史主线数据。

用法：
    uv run python backfill_mainline.py                         # 补充所有缺失的
    uv run python backfill_mainline.py 20260601                # 补充指定日期
"""
import sys
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from store.db import connect
from store import daily as daily_store
from strategy import loader


# ── 配置（与 sector_monitor.py 保持一致） ──
MIN_STOCKS_PER_SECTOR = 5
SCORE_WINDOWS = [5, 10, 20]
NEW_HIGH_LOOKBACK = 63
EXCLUDE_INDUSTRIES = ["None", ""]

WEIGHTS = {
    "return_5d": 0.20,
    "return_10d": 0.10,
    "return_20d": 0.05,
    "turnover": 0.20,
    "breadth": 0.15,
    "momentum": 0.10,
    "new_high_ratio": 0.10,
    "concentration": 0.05,
    "relative_strength": 0.05,
}


CREATE_HISTORY_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS sector_ranking_history (
        trade_date TEXT NOT NULL,
        industry TEXT NOT NULL,
        score REAL,
        rank INTEGER,
        return_5d REAL,
        return_10d REAL,
        return_20d REAL,
        turnover REAL,
        breadth REAL,
        new_high_ratio REAL,
        concentration REAL,
        relative_strength REAL,
        PRIMARY KEY (trade_date, industry)
    )
"""


# ── 直连数据库加载（比 loader.load_all 走 CSV 快得多） ──

def load_from_db(dates_needed):
    """从SQLite直接加载指定日期范围的行情+行业信息"""
    start = min(dates_needed)
    end = max(dates_needed)

    with connect() as conn:
        # 行情数据
        df = pd.read_sql_query(f"""
            SELECT d.ts_code, d.trade_date, d.open, d.close, d.high,
                   d.low, d.vol, d.amount, d.pct_chg
            FROM daily d
            WHERE d.trade_date >= ? AND d.trade_date <= ?
            ORDER BY d.ts_code, d.trade_date
        """, conn, params=(start, end))

        # 行业信息
        info = pd.read_sql_query("""
            SELECT ts_code, industry FROM stock_basic
            WHERE industry NOT IN ('None', '') AND delist_date IS NULL
        """, conn)

    df = df.merge(info, on="ts_code", how="inner")
    return df


# ── 单日计算 ──

def compute_one_date(df, trade_date):
    """对单个交易日计算板块评分（优化版，直接使用已加载的数据）"""
    all_dates = sorted(df["trade_date"].unique())
    if trade_date not in all_dates:
        # 找到最近的可用交易日
        for d in reversed(all_dates):
            if d <= trade_date:
                trade_date = d
                break
        else:
            return None

    end_idx = all_dates.index(trade_date)

    # 确定各窗口的起始日期
    date_range = {"end": trade_date}
    for w in SCORE_WINDOWS:
        idx = end_idx - w + 1
        date_range[w] = all_dates[max(0, idx)]

    # 当日数据快照
    day_df = df[df["trade_date"] == trade_date]

    # 板块样本量过滤
    sample_sizes = day_df.groupby("industry").size()
    valid = sample_sizes[sample_sizes >= MIN_STOCKS_PER_SECTOR].index

    # ── 因子计算 ──

    factors = {}

    # 1. 涨幅
    for w in [5, 10, 20]:
        start = date_range.get(w)
        if start is None or start >= trade_date:
            continue
        sub = df[(df["trade_date"] >= start) & (df["trade_date"] <= trade_date)]
        if sub.empty:
            continue
        first = sub.groupby("ts_code").first()["close"]
        last = sub.groupby("ts_code").last()["close"]
        ret = (last / first - 1)
        ret = ret.to_frame("ret")
        ret["industry"] = sub.groupby("ts_code")["industry"].first()
        factors[f"return_{w}d"] = ret.groupby("industry")["ret"].mean()

    # 2. 成交额
    factors["turnover"] = day_df.groupby("industry")["amount"].sum()

    # 3. 上涨占比
    def _breadth(grp):
        total = len(grp)
        up = (grp["pct_chg"] > 0).sum()
        return up / total if total > 0 else 0
    factors["breadth"] = day_df.groupby("industry").apply(_breadth)

    # 4. 新高占比
    nh_start = all_dates[max(0, end_idx - NEW_HIGH_LOOKBACK + 1)]
    nh_window = df[(df["trade_date"] >= nh_start) & (df["trade_date"] <= trade_date)]
    max_high = nh_window.groupby("ts_code")["high"].max()
    day_high = day_df.set_index("ts_code")["high"]
    common = day_high.index.intersection(max_high.index)
    is_nh = day_high.loc[common].values >= max_high.loc[common].values
    nh_series = pd.Series(0.0, index=day_df["industry"].unique())
    for ind in valid:
        stocks_in_ind = day_df[day_df["industry"] == ind]
        codes = stocks_in_ind["ts_code"].values
        codes_in_common = [c for c in codes if c in common]
        if codes_in_common:
            nh_count = sum(
                1 for c in codes_in_common
                if is_nh[list(common).index(c)]
            )
            nh_series[ind] = nh_count / len(codes_in_common)
    factors["new_high_ratio"] = nh_series

    # 5. 集中度
    def _conc(grp):
        rets = grp["pct_chg"]
        if len(rets) < 3 or rets.std() == 0:
            return 1.0
        return rets.std() / abs(rets.mean()) if rets.mean() != 0 else 99
    raw_conc = day_df.groupby("industry").apply(_conc).clip(upper=20)
    factors["concentration"] = 1 / (raw_conc + 0.001)

    # 6. 相对强度
    market_avg = day_df["pct_chg"].mean()
    def _rs(grp):
        return grp["pct_chg"].mean() - market_avg
    factors["relative_strength"] = day_df.groupby("industry").apply(_rs)

    # ── 合成评分 ──
    factor_df = pd.DataFrame(factors)
    factor_df = factor_df[factor_df.index.isin(valid)].fillna(0)

    def rank_normalize(series):
        if series.empty or series.std() == 0:
            return pd.Series(0.5, index=series.index)
        r = series.rank(method="average")
        return (r - 1) / (len(series) - 1) if len(series) > 1 else pd.Series(0.5, index=series.index)

    scores = pd.Series(0.0, index=factor_df.index)
    for fname, weight in WEIGHTS.items():
        if weight == 0 or fname not in factor_df.columns:
            continue
        col = factor_df[fname]
        if col.isna().all():
            continue
        scores += rank_normalize(col.fillna(0)) * weight

    ranked = scores.sort_values(ascending=False)
    result = ranked.to_frame("综合评分")
    result["排名"] = range(1, len(result) + 1)
    if "return_5d" in factor_df.columns:
        result["5日涨幅"] = factor_df["return_5d"] * 100
    else:
        result["5日涨幅"] = 0.0
    if "return_10d" in factor_df.columns:
        result["10日涨幅"] = factor_df["return_10d"] * 100
    else:
        result["10日涨幅"] = 0.0
    if "return_20d" in factor_df.columns:
        result["20日涨幅"] = factor_df["return_20d"] * 100
    else:
        result["20日涨幅"] = 0.0
    result["成交额_亿"] = factor_df["turnover"] / 1e8
    result["上涨占比"] = factor_df["breadth"] * 100
    result["新高占比"] = factor_df["new_high_ratio"] * 100
    result["集中度得分"] = factors["concentration"].reindex(result.index).fillna(0)
    result["相对强度"] = factors["relative_strength"].reindex(result.index).fillna(0)

    return result


# ── 保存 ──

def save_one_date(date_str, rankings_df):
    with connect() as conn:
        conn.execute(CREATE_HISTORY_TABLE_SQL)
        for idx, row in rankings_df.iterrows():
            conn.execute("""
                INSERT OR REPLACE INTO sector_ranking_history
                (trade_date, industry, score, rank, return_5d, return_10d, return_20d,
                 turnover, breadth, new_high_ratio, concentration, relative_strength)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                date_str, idx,
                row.get("综合评分", 0), row.get("排名", 0),
                row.get("5日涨幅", 0), row.get("10日涨幅", 0),
                row.get("20日涨幅", 0), row.get("成交额_亿", 0),
                row.get("上涨占比", 0), row.get("新高占比", 0),
                row.get("集中度得分", 0), row.get("相对强度", 0),
            ))
        conn.commit()


# ── 主流程 ──

def backfill(target_dates=None):
    """补充主线排行数据"""
    with connect() as conn:
        conn.execute(CREATE_HISTORY_TABLE_SQL)
        # 所有交易日
        all_trade_dates = sorted([
            r[0] for r in conn.execute(
                "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date"
            ).fetchall()
        ])

        if not all_trade_dates:
            print("⚠ 无 daily 行情数据，无法补充主线排行")
            return

        # 已处理的
        done = set(
            r[0] for r in conn.execute(
                "SELECT DISTINCT trade_date FROM sector_ranking_history"
            ).fetchall()
        )

    if target_dates is None:
        # 前端日期选择器范围
        import json
        try:
            with open("web/data/manifest.json") as f:
                manifest = json.load(f)
            web_dates = sorted([d["date"] for d in manifest.get("dates", [])])
            target_dates = web_dates
        except:
            target_dates = all_trade_dates

    # 过滤出未处理的
    pending = sorted(set(target_dates) - done)
    if not pending:
        print(f"✅ 所有日期({len(target_dates)} 个)已处理完毕，无需补充")
        return

    print(f"📅 目标: {len(target_dates)} 个日期", flush=True)
    print(f"   ✅ 已处理: {len(target_dates) - len(pending)}", flush=True)
    print(f"   ⏳ 待补充: {len(pending)}", flush=True)
    print(f"   范围: {pending[0]} ~ {pending[-1]}", flush=True)
    print(flush=True)

    # 分批加载数据（每批加载约60个交易日的数据量）
    batch_start = min(pending)
    batch_end = max(pending)
    # 需要额外前导数据用于计算窗口和回看
    lookback = max(SCORE_WINDOWS) + NEW_HIGH_LOOKBACK + 20  # 约100个交易日

    # 找到 batch_start 往前 lookback 个交易日
    sorted_dates = sorted(all_trade_dates)
    idx = sorted_dates.index(batch_start)
    data_start = sorted_dates[max(0, idx - lookback)]

    print(f"📥 批量加载行情数据: {data_start} ~ {batch_end} ({all_trade_dates.index(batch_end) - all_trade_dates.index(data_start)} 个交易日)")
    df = load_from_db([data_start, batch_end])
    print(f"   ✓ {df['ts_code'].nunique()} 只股票, {len(df)} 行")

    # 可用交易日列表（加载范围内的）
    loaded_dates = sorted(df["trade_date"].unique())
    print(f"   ✓ {len(loaded_dates)} 个交易日")

    # 逐日计算
    success = 0
    skip = 0
    errors = 0
    for i, date_str in enumerate(pending):
        if date_str not in loaded_dates:
            # 找最近的
            for d in reversed(all_trade_dates):
                if d <= date_str and d in loaded_dates:
                    date_str = d
                    break
            else:
                print(f"   ⚠ [{i+1}/{len(pending)}] {date_str}: 无可用的交易日数据")
                skip += 1
                continue

        try:
            rankings = compute_one_date(df, date_str)
            if rankings is None or rankings.empty:
                skip += 1
                continue
            save_one_date(date_str, rankings)
            success += 1
            if (i + 1) % 5 == 0:
                print(f"   ✅ [{i+1}/{len(pending)}] 已处理 {success} 个, 跳过 {skip}, 错误 {errors}")
        except Exception as e:
            print(f"   ❌ [{i+1}/{len(pending)}] {date_str}: {e}")
            errors += 1

    print()
    print(f"{'═' * 42}")
    print(f"  补充完成")
    print(f"  ✅ 成功: {success}")
    print(f"  ⏭ 跳过: {skip}")
    print(f"  ❌ 错误: {errors}")
    print(f"{'═' * 42}")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        date = sys.argv[1]
        if date.isdigit() and len(date) == 8:
            backfill([date])
        else:
            print(f"用法: uv run python backfill_mainline.py [YYYYMMDD]")
    else:
        backfill()
