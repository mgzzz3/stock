"""
sector_monitor.py — 量化主线监控系统

核心逻辑：从多个维度给每个行业板块打分，
综合识别当前市场的主线板块。

用法：
    uv run python sector_monitor.py                          # 默认最新日期
    uv run python sector_monitor.py 20260626                 # 指定日期
    uv run python sector_monitor.py --history                # 输出历史排行+轮动矩阵
    uv run python sector_monitor.py --signal                 # 仅输出确认信号JSON
"""
import sys
import json
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from store.db import connect
from store import daily as daily_store
from strategy import loader

# ── 配置参数 ──────────────────────────────────────────────
MIN_STOCKS_PER_SECTOR = 5
SCORE_WINDOWS = [5, 10, 20]
TOP_N_SECTORS = 8
TOP_N_STOCKS = 5
NEW_HIGH_LOOKBACK = 63
EXCLUDE_INDUSTRIES = ["None", ""]
CONFIRM_CONSECUTIVE_DAYS = 3      # 连续N天高分才算确认
CONFIRM_SCORE_THRESHOLD = 0.70    # 高分阈值
CONFIRM_GAP_THRESHOLD = 0.10      # 与第二名的分差阈值

WEIGHTS = {
    "return_5d":        0.20,
    "return_10d":       0.10,
    "return_20d":       0.05,
    "turnover":         0.20,
    "breadth":          0.15,
    "momentum":         0.10,
    "new_high_ratio":   0.10,
    "concentration":    0.05,
    "relative_strength": 0.05,
}


# ═══════════════════════════════════════════════════════════
#  核心数据加载
# ═══════════════════════════════════════════════════════════

def _get_latest_date():
    if len(sys.argv) >= 2 and sys.argv[1] not in ("--history", "--signal"):
        d = sys.argv[1]
        if d.isdigit() and len(d) == 8:
            return d
    return daily_store.last_global_trade_date()


def load_sector_data(end_date):
    end = datetime.strptime(end_date, "%Y%m%d")
    start_20d = _shift_date(end, -40)
    start_new_high = _shift_date(end, -NEW_HIGH_LOOKBACK - 20)

    df = loader.load_all(
        start=start_20d.strftime("%Y%m%d"),
        end=end_date,
        columns=("open", "close", "high", "low", "vol", "amount", "pct_chg"),
    )
    info = loader.stock_names()
    df = df.merge(info, on="ts_code", how="inner")
    df = df[~df["industry"].isin(EXCLUDE_INDUSTRIES)]

    df_high = loader.load_all(
        start=start_new_high.strftime("%Y%m%d"),
        end=end_date,
        columns=("close", "high"),
    )
    df_high = df_high.merge(info[["ts_code", "industry"]], on="ts_code", how="inner")
    df_high = df_high[~df_high["industry"].isin(EXCLUDE_INDUSTRIES)]

    return df, df_high


def _shift_date(d, days):
    return d + timedelta(days=days)


def find_trade_dates(df, end_date_str, windows):
    all_dates = sorted(df["trade_date"].unique())
    if end_date_str not in all_dates:
        for d in reversed(all_dates):
            if d <= end_date_str:
                end_date_str = d
                break
        else:
            end_date_str = all_dates[-1]
    end_idx = all_dates.index(end_date_str)
    results = {}
    for w in windows:
        idx = end_idx - w + 1
        results[w] = all_dates[max(0, idx)]
    results["end"] = end_date_str
    return results


# ═══════════════════════════════════════════════════════════
#  因子计算
# ═══════════════════════════════════════════════════════════

def calc_sector_returns(df, date_range):
    end = date_range["end"]
    results = {}
    for w in [5, 10, 20]:
        start = date_range.get(w)
        if start is None or start >= end:
            continue
        sub = df[(df["trade_date"] >= start) & (df["trade_date"] <= end)]
        first = sub.groupby("ts_code").first()["close"]
        last = sub.groupby("ts_code").last()["close"]
        returns = (last / first - 1).to_frame(f"ret_{w}d")
        returns["industry"] = sub.groupby("ts_code")["industry"].first()
        results[f"return_{w}d"] = returns.groupby("industry")[f"ret_{w}d"].mean()
    return pd.DataFrame(results)


def calc_turnover(df, date_range):
    end = date_range["end"]
    sub = df[df["trade_date"] == end].copy()
    if sub.empty:
        last_date = sorted(df["trade_date"].unique())[-1]
        sub = df[df["trade_date"] == last_date].copy()
    return sub.groupby("industry")["amount"].sum()


def calc_breadth(df, date_range):
    end_day = df[df["trade_date"] == date_range["end"]].copy()
    if end_day.empty:
        return pd.Series(dtype=float)

    def _breadth(grp):
        total = len(grp)
        up = (grp["pct_chg"] > 0).sum()
        return up / total if total > 0 else 0

    return end_day.groupby("industry").apply(_breadth)


def calc_new_high_ratio(df_high, end_date_str):
    dates = sorted(df_high["trade_date"].unique())
    if end_date_str not in dates:
        for d in reversed(dates):
            if d <= end_date_str:
                end_date_str = d
                break
    end_idx = dates.index(end_date_str)
    lookback_start = dates[max(0, end_idx - NEW_HIGH_LOOKBACK + 1)]

    end_data = df_high[df_high["trade_date"] == end_date_str].set_index("ts_code").copy()
    window = df_high[
        (df_high["trade_date"] >= lookback_start) &
        (df_high["trade_date"] <= end_date_str)
    ]
    max_high = window.groupby("ts_code")["high"].max()
    common = end_data.index.intersection(max_high.index)
    end_data = end_data.loc[common]
    max_high = max_high.loc[common]
    end_data["is_new_high"] = end_data["high"].values >= max_high.values

    def _high_ratio(grp):
        total = len(grp)
        return grp["is_new_high"].sum() / total if total > 0 else 0

    return end_data.groupby("industry").apply(_high_ratio)


def calc_concentration(df, date_range):
    end = date_range["end"]
    sub = df[df["trade_date"] == end].copy()
    if sub.empty:
        return pd.Series(dtype=float)

    def _conc(grp):
        rets = grp["pct_chg"]
        if len(rets) < 3 or rets.std() == 0:
            return 1.0
        return rets.std() / abs(rets.mean()) if rets.mean() != 0 else 99

    raw = sub.groupby("industry").apply(_conc).clip(upper=20)
    return 1 / (raw + 0.001)


def calc_relative_strength(df, date_range):
    end = date_range["end"]
    sub = df[df["trade_date"] == end].copy()
    if sub.empty:
        return pd.Series(dtype=float)
    market_avg = sub["pct_chg"].mean()

    def _rs(grp):
        return grp["pct_chg"].mean() - market_avg

    return sub.groupby("industry").apply(_rs)


# ═══════════════════════════════════════════════════════════
#  评分系统
# ═══════════════════════════════════════════════════════════

def rank_normalize(series, reverse=False):
    if series.empty:
        return pd.Series(dtype=float)
    r = series.rank(method="average")
    if reverse:
        r = len(series) + 1 - r
    return (r - 1) / (len(series) - 1) if len(series) > 1 else pd.Series(0.5, index=series.index)


def compute_scores(factors, weights):
    scores = pd.Series(0.0, index=factors.index)
    for factor_name, weight in weights.items():
        if weight == 0 or factor_name not in factors.columns:
            continue
        col = factors[factor_name]
        if col.isna().all():
            continue
        scores += rank_normalize(col.fillna(0)) * weight
    return scores


def get_top_stocks_in_sector(df, date_range, sector, top_n=5):
    end = date_range["end"]
    sub = df[(df["trade_date"] == end) & (df["industry"] == sector)].copy()
    dates = sorted(df[df["ts_code"].isin(sub["ts_code"])]["trade_date"].unique())
    if len(dates) < 6:
        return []
    recent_dates = [d for d in dates if d <= end][-6:]
    if len(recent_dates) < 2:
        return []
    start_5d = recent_dates[0]
    sub_hist = df[
        (df["ts_code"].isin(sub["ts_code"])) &
        (df["trade_date"].isin([start_5d, end]))
    ]
    first = sub_hist[sub_hist["trade_date"] == start_5d].set_index("ts_code")["close"]
    last = sub_hist[sub_hist["trade_date"] == end].set_index("ts_code")["close"]
    both = first.index.intersection(last.index)
    if len(both) == 0:
        return []
    ret_5d = (last[both] / first[both] - 1).sort_values(ascending=False)
    top_codes = ret_5d.head(top_n)
    info_dict = loader.stock_names().set_index("ts_code")["name"].to_dict()
    return [
        {"ts_code": c, "name": info_dict.get(c, c), "ret_5d": round(r * 100, 2)}
        for c, r in top_codes.items()
    ]


# ═══════════════════════════════════════════════════════════
#  历史排行存储与加载
# ═══════════════════════════════════════════════════════════

def save_ranking_history(date_str, rankings_df):
    with connect() as conn:
        conn.execute("""
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
        """)
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


def load_ranking_history(lookback_days=30):
    with connect() as conn:
        return pd.read_sql_query("""
            SELECT * FROM sector_ranking_history
            WHERE trade_date >= (
                SELECT MIN(trade_date) FROM (
                    SELECT DISTINCT trade_date FROM sector_ranking_history
                    ORDER BY trade_date DESC LIMIT ?
                )
            )
            ORDER BY trade_date, rank
        """, conn, params=(lookback_days,))


# ═══════════════════════════════════════════════════════════
#  主线确认信号
# ═══════════════════════════════════════════════════════════

def generate_confirmation_signal(rankings, trade_date):
    """生成主线确认信号并保存为JSON"""
    top = rankings.head(TOP_N_SECTORS)
    if len(top) == 0:
        return None

    main_line = top.index[0]
    main_score = float(top.iloc[0]["综合评分"])
    second_score = float(top.iloc[1]["综合评分"]) if len(top) > 1 else 0
    gap = main_score - second_score

    # 读取历史确认数据
    history = load_ranking_history(20)
    if not history.empty:
        recent = history[history["trade_date"] <= trade_date].sort_values("trade_date")
        top1_over_time = recent.loc[recent.groupby("trade_date")["score"].idxmax()]
        consecutive = _count_consecutive_top1(top1_over_time, main_line, trade_date)
    else:
        consecutive = 1

    # 信号等级判定
    strength = 0
    if main_score >= CONFIRM_SCORE_THRESHOLD and gap >= CONFIRM_GAP_THRESHOLD:
        strength = 2
    elif main_score >= CONFIRM_SCORE_THRESHOLD:
        strength = 1
    else:
        strength = 0

    if strength >= 2 and consecutive >= CONFIRM_CONSECUTIVE_DAYS:
        level = "strong"        # 🟢 主线确认
    elif strength >= 2 and consecutive >= 1:
        level = "emerging"      # 🟡 主线萌芽
    elif strength >= 1:
        level = "candidate"     # 🔵 潜在主线
    else:
        level = "none"          # ⚪ 无明显主线

    signal = {
        "date": trade_date,
        "main_line": main_line,
        "main_score": round(main_score, 4),
        "second_line": top.index[1] if len(top) > 1 else None,
        "gap": round(gap, 4),
        "consecutive_days": consecutive,
        "confirmation_level": level,
        "strength": strength,
        "summary": _signal_summary(level, main_line, main_score, consecutive, gap),
    }

    # 保存JSON
    import os
    with open("data/signal.json", "w") as f:
        json.dump(signal, f, ensure_ascii=False, indent=2)
    web_data_dir = "web/data"
    os.makedirs(web_data_dir, exist_ok=True)
    with open(os.path.join(web_data_dir, "signal.json"), "w") as f:
        json.dump(signal, f, ensure_ascii=False, indent=2)

    return signal


def _count_consecutive_top1(top1_over_time, current_main, current_date):
    """统计当前主线连续登顶天数"""
    recent = top1_over_time[top1_over_time["trade_date"] <= current_date]
    if recent.empty:
        return 1
    recent = recent.sort_values("trade_date")
    count = 0
    for _, row in recent.iloc[::-1].iterrows():
        industry = row.get("industry")
        if industry == current_main:
            count += 1
        else:
            break
    return max(count, 1)


def _signal_summary(level, main_line, score, consecutive, gap):
    if level == "strong":
        return (f"✅ 主线确认！{main_line}连续{consecutive}天评分≥{CONFIRM_SCORE_THRESHOLD}，"
                f"领先第二名{gap:.2f}，当前评分{score:.3f}，建议重点关注")
    elif level == "emerging":
        return (f"🟡 主线萌芽：{main_line}今日评分{score:.3f}，领先{gap:.2f}，"
                f"但尚未连续{CONFIRM_CONSECUTIVE_DAYS}天确认（当前{consecutive}天），关注持续性")
    elif level == "candidate":
        return (f"🔵 潜在主线：{main_line}评分{score:.3f}，但领先优势不足(gap={gap:.2f})，"
                f"需观察量价配合")
    else:
        return "⚪ 市场无明显主线，轮动较快，建议保持观望"


def print_signal(signal):
    """打印确认信号"""
    if not signal:
        return
    print(f"\n{'═' * 56}")
    print(f"  🚦 主线确认信号 — {signal['date']}")
    print(f"{'═' * 56}")
    print(f"  等级：{signal['confirmation_level']} (强度{signal['strength']}/2)")
    print(f"  主线：{signal['main_line']}（评分{signal['main_score']:.3f}）")
    print(f"  连续登顶：{signal['consecutive_days']}天")
    print(f"  领先第二名：{signal['gap']:.3f}")
    print(f"  总结：{signal['summary']}")
    print(f"  💾 → data/signal.json")
    print()


# ═══════════════════════════════════════════════════════════
#  板块轮动矩阵（HTML）
# ═══════════════════════════════════════════════════════════

def load_all_historical_scores():
    """加载所有历史评分记录"""
    with connect() as conn:
        df = pd.read_sql_query(
            "SELECT DISTINCT trade_date FROM sector_ranking_history ORDER BY trade_date",
            conn
        )
    return df["trade_date"].tolist()


def generate_rotation_matrix(lookback_days=30, top_n=12):
    """生成板块轮动矩阵并保存为HTML可视化"""
    history = load_ranking_history(lookback_days)
    if history.empty:
        print("  ⚠ 尚无历史排行数据，跳过轮动矩阵")
        return

    # 取评分排名的TOP n板块
    latest = history[history["trade_date"] == history["trade_date"].max()]
    top_industries = latest.nsmallest(top_n, "rank")["industry"].tolist()

    # 构建透视表
    hist = history[history["industry"].isin(top_industries)].copy()
    pivot = hist.pivot_table(
        index="trade_date", columns="industry", values="score", aggfunc="first"
    )
    pivot = pivot.sort_index()
    # 按最新评分排序
    latest_scores = pivot.iloc[-1]
    top_cols = latest_scores.sort_values(ascending=False).index.tolist()
    pivot = pivot[top_cols]

    # 填充缺失值
    pivot = pivot.fillna(0)

    html = _build_rotation_html(pivot, lookback_days, top_n)
    out_path = "data/rotation_matrix.html"
    with open(out_path, "w") as f:
        f.write(html)
    # 同时输出到 web/data/ 供H5前端使用
    import os
    web_data_dir = "web/data"
    os.makedirs(web_data_dir, exist_ok=True)
    web_path = os.path.join(web_data_dir, "rotation_matrix.html")
    with open(web_path, "w") as f:
        f.write(html)
    print(f"  💾 轮动矩阵图 → {out_path}")


def _build_rotation_html(pivot, days, top_n):
    """构建轮动矩阵HTML（热力表格）"""
    dates = pivot.index.tolist()
    industries = pivot.columns.tolist()

    # 给每个值分配颜色
    rows_html = []
    for date in dates:
        cells = [f"<td class='date-cell'>{date[-5:]}</td>"]
        for ind in industries:
            val = pivot.loc[date, ind]
            # 根据分数分配颜色（从红到绿）
            color = _score_color(val)
            cells.append(
                f"<td class='data-cell' style='background:{color}' "
                f"title='{date}|{ind}|评分{val:.3f}'>{val:.2f}</td>"
            )
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    # 表头
    header_cells = "<th class='date-header'>日期</th>"
    for ind in industries:
        header_cells += f"<th class='ind-header'>{ind[:4]}</th>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>板块轮动矩阵</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; background:#0d1117; color:#c9d1d9; padding:20px; }}
h1 {{ font-size:18px; margin-bottom:16px; color:#58a6ff; }}
table {{ border-collapse:collapse; font-size:12px; }}
th, td {{ padding:6px 10px; text-align:center; border:1px solid #30363d; white-space:nowrap; }}
.date-header, .date-cell {{ position:sticky; left:0; background:#161b22; color:#8b949e; text-align:center; font-weight:normal; min-width:52px; }}
.date-header {{ z-index:2; }}
.date-cell {{ z-index:1; }}
.ind-header {{ background:#161b22; color:#58a6ff; font-weight:600; writing-mode:vertical-lr; text-orientation:mixed; height:80px; font-size:11px; }}
.data-cell {{ font-weight:500; color:#c9d1d9; }}
.data-cell:hover {{ filter:brightness(1.4); cursor:pointer; }}
.footer {{ margin-top:12px; color:#8b949e; font-size:12px; }}
.badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; margin-right:4px; }}
.badge-green {{ background:#238636; color:#fff; }}
.badge-yellow {{ background:#9e6a03; color:#fff; }}
.badge-red {{ background:#da3633; color:#fff; }}
.badge-gray {{ background:#30363d; color:#8b949e; }}
</style>
</head>
<body>
<h1>🔥 板块轮动矩阵 · TOP{top_n} · 近{days}个交易日</h1>
<div style="overflow-x:auto; overflow-y:auto; max-height:calc(100vh - 120px);">
<table>
<thead><tr>{header_cells}</tr></thead>
<tbody>{"".join(rows_html)}</tbody>
</table>
</div>
<div class="footer">
<span class="badge badge-green">≥0.70 主线</span>
<span class="badge badge-yellow">0.50~0.69 候选</span>
<span class="badge badge-red">&lt;0.50 弱势</span>
<span class="badge badge-gray">灰色 = 0</span>
&nbsp;&nbsp;更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}
</div>
</body>
</html>"""
    return html


def _score_color(val):
    """评分→颜色映射"""
    if val >= 0.80:
        return "#1a7f37"  # 深绿
    if val >= 0.70:
        return "#238636"  # 绿
    if val >= 0.60:
        return "#2ea043"  # 浅绿
    if val >= 0.55:
        return "#9e6a03"  # 黄
    if val >= 0.50:
        return "#d29922"  # 橙黄
    if val >= 0.40:
        return "#bd561d"  # 橙
    if val >= 0.30:
        return "#da3633"  # 红
    if val >= 0.10:
        return "#ab2626"  # 深红
    return "#30363d"      # 灰


# ═══════════════════════════════════════════════════════════
#  历史轮动文本输出
# ═══════════════════════════════════════════════════════════

def show_sector_rotation(days=20):
    try:
        history = load_ranking_history(days)
    except Exception:
        print("（尚无历史数据）")
        return
    if history.empty:
        return

    pivot = history.pivot_table(index="trade_date", columns="industry", values="rank")
    top_over_time = pivot.idxmin(axis=1).value_counts().head(8)

    print(f"\n📊 近期板块轮动轨迹（最近{days}个交易日，TOP1板块出现频次）：")
    print(f"{'板块':<16}{'登顶次数':<10}")
    print("-" * 26)
    for industry, count in top_over_time.items():
        bar = "█" * count
        print(f"{industry:<16}{count:<10}{bar}")
    print()


# ═══════════════════════════════════════════════════════════
#  完整计算流程
# ═══════════════════════════════════════════════════════════

def compute_rankings(end_date_str):
    """计算完整评分并返回 rankings DataFrame + factors"""
    df, df_high = load_sector_data(end_date_str)
    trade_dates = find_trade_dates(df, end_date_str, SCORE_WINDOWS)
    end_day = trade_dates["end"]

    factors_list = []
    ret_df = calc_sector_returns(df, trade_dates)
    factors_list.append(ret_df)
    factors_list.append(calc_turnover(df, trade_dates).to_frame("turnover"))
    factors_list.append(calc_breadth(df, trade_dates).to_frame("breadth"))
    factors_list.append(calc_new_high_ratio(df_high, end_day).to_frame("new_high_ratio"))
    factors_list.append(calc_concentration(df, trade_dates).to_frame("concentration"))
    factors_list.append(calc_relative_strength(df, trade_dates).to_frame("relative_strength"))

    factors = factors_list[0]
    for f in factors_list[1:]:
        factors = factors.join(f, how="outer")

    sample_sizes = df[df["trade_date"] == end_day].groupby("industry").size()
    valid = sample_sizes[sample_sizes >= MIN_STOCKS_PER_SECTOR].index
    factors = factors[factors.index.isin(valid)].fillna(0)

    scores = compute_scores(factors, WEIGHTS)
    ranked = scores.sort_values(ascending=False)

    rankings = ranked.to_frame("综合评分")
    rankings["排名"] = range(1, len(rankings) + 1)
    rankings["5日涨幅"] = factors["return_5d"] * 100
    if "return_10d" in factors.columns:
        rankings["10日涨幅"] = factors["return_10d"] * 100
    if "return_20d" in factors.columns:
        rankings["20日涨幅"] = factors["return_20d"] * 100
    rankings["成交额_亿"] = factors["turnover"] / 1e8
    rankings["上涨占比"] = factors["breadth"] * 100
    rankings["新高占比"] = factors["new_high_ratio"] * 100
    rankings["集中度得分"] = calc_concentration(df, trade_dates).reindex(rankings.index).fillna(0)
    rankings["相对强度"] = factors["relative_strength"]

    return rankings, df, trade_dates, end_day


# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════

def run(end_date=None):
    if end_date is None:
        end_date = _get_latest_date()
    if end_date is None:
        print("❌ 无法确定交易日，请先运行 uv run python -m ingest.incremental")
        return

    end_str = str(end_date)
    show_history_flag = "--history" in sys.argv

    print(f"\n{'═' * 56}")
    print(f"  量化主线监控 — {end_str}")
    print(f"{'═' * 56}\n")

    # 计算
    print("📥 加载数据...")
    rankings, df, trade_dates, end_day = compute_rankings(end_str)
    print(f"   ✓ {df['ts_code'].nunique()} 只股票，{len(rankings)} 个行业板块")
    print(f"   ✓ 分析区间: {trade_dates.get(20)} ~ {end_day}")

    # 持久化排行
    save_ranking_history(end_day, rankings)

    # 输出报告
    _print_report(rankings, df, trade_dates, end_day)

    # 主线确认信号
    signal = generate_confirmation_signal(rankings, end_day)
    print_signal(signal)

    # 板块轮动矩阵 HTML
    print(f"{'═' * 56}")
    print("  🗺️  生成板块轮动矩阵...")
    generate_rotation_matrix(lookback_days=30, top_n=12)
    print()

    # 历史轮动文本
    if show_history_flag:
        show_sector_rotation(20)

    # 导出 JSON
    _export_json(rankings, df, trade_dates, end_day, signal)


def _print_report(rankings, df, trade_dates, end_day):
    top = rankings.head(TOP_N_SECTORS)

    print(f"\n{'═' * 80}")
    print(f"  🔥 主线板块 TOP{TOP_N_SECTORS}")
    print(f"{'═' * 80}\n")

    header = f"{'排名':<5}{'板块':<14}{'综合评分':<10}{'5日涨':<9}{'成交额(亿)':<12}{'上涨占比':<10}{'新高占比':<10}{'相对强度':<10}"
    print(header)
    print("-" * 80)

    for idx, (industry, row) in enumerate(top.iterrows(), 1):
        ret_5 = f"{row['5日涨幅']:.2f}%" if pd.notna(row['5日涨幅']) else "N/A"
        amt = f"{row['成交额_亿']:.1f}" if pd.notna(row['成交额_亿']) else "N/A"
        breadth = f"{row['上涨占比']:.0f}%" if pd.notna(row['上涨占比']) else "N/A"
        nh = f"{row['新高占比']:.1f}%" if pd.notna(row['新高占比']) else "N/A"
        rs = f"{row['相对强度']:+.2f}pp" if pd.notna(row['相对强度']) else "N/A"
        score = f"{row['综合评分']:.3f}"
        if row['综合评分'] >= 0.7:
            score_disp = f"🔥{score}"
        elif row['综合评分'] >= 0.5:
            score_disp = f"⭐{score}"
        else:
            score_disp = f" {score}"
        print(f"{idx:<5}{industry:<14}{score_disp:<10}{ret_5:<9}{amt:<12}{breadth:<10}{nh:<10}{rs:<10}")

    # 龙头股
    print(f"\n{'═' * 80}")
    print("  👑 主线板块龙头股")
    print(f"{'═' * 80}\n")
    for idx, (industry, _) in enumerate(top.iterrows(), 1):
        top_stocks = get_top_stocks_in_sector(df, trade_dates, industry, TOP_N_STOCKS)
        stocks_str = "  ".join(
            [f"{s['name']}({s['ret_5d']:+.1f}%)" for s in top_stocks]
        ) if top_stocks else "（数据不足）"
        print(f"  {idx}. {industry}")
        print(f"     📈 {stocks_str}")
        print()

    # 画像
    print(f"{'═' * 80}")
    print("  📋 市场画像摘要")
    print(f"{'═' * 80}\n")

    top3 = top.head(3)
    bot3 = rankings.tail(3)
    print("  🟢 领涨三强：")
    for industry, row in top3.iterrows():
        ret_5 = f"{row['5日涨幅']:.2f}%" if pd.notna(row['5日涨幅']) else "N/A"
        print(f"     · {industry}（评分{row['综合评分']:.3f}，5日 {ret_5}）")
    print(f"\n  🔴 领跌三弱：")
    for industry, row in bot3.iterrows():
        ret_5 = f"{row['5日涨幅']:.2f}%" if pd.notna(row['5日涨幅']) else "N/A"
        print(f"     · {industry}（评分{row['综合评分']:.3f}，5日 {ret_5}）")

    top_score = top.iloc[0]["综合评分"]
    gap = top_score - top.iloc[1]["综合评分"] if len(top) > 1 else 0
    print(f"\n  🔍 主线清晰度判断：")
    if top_score >= 0.7 and gap >= 0.15:
        print(f"     ✅ 主线非常清晰！第一板块评分{top_score:.3f}，领先第二{gap:.3f}")
        print(f"     核心关注：{top.index[0]}")
    elif top_score >= 0.5:
        print(f"     ⚠ 有潜在主线，但还不够突出（评分{top_score:.3f}）")
    else:
        print(f"     🔄 市场轮动较快，无明显主线")

    main_line = top.index[0]
    main_stocks = get_top_stocks_in_sector(df, trade_dates, main_line, 3)
    print(f"\n  🎯 操作建议：")
    if main_stocks:
        stocks_str = "、".join([f"{s['name']}({s['ts_code']})" for s in main_stocks])
        print(f"     主线板块：{main_line}")
        print(f"     龙头参考：{stocks_str}")
    print()


def _export_json(rankings, df, trade_dates, end_day, signal=None):
    top = rankings.head(TOP_N_SECTORS)
    data = []
    for industry, row in top.iterrows():
        stocks = get_top_stocks_in_sector(df, trade_dates, industry, TOP_N_STOCKS)
        data.append({
            "rank": int(row["排名"]),
            "industry": industry,
            "score": round(float(row["综合评分"]), 4),
            "return_5d": round(float(row["5日涨幅"]), 2) if pd.notna(row["5日涨幅"]) else None,
            "turnover_billion": round(float(row["成交额_亿"]), 1) if pd.notna(row["成交额_亿"]) else None,
            "breadth_pct": round(float(row["上涨占比"]), 1) if pd.notna(row["上涨占比"]) else None,
            "new_high_pct": round(float(row["新高占比"]), 1) if pd.notna(row["新高占比"]) else None,
            "relative_strength": round(float(row["相对强度"]), 2) if pd.notna(row["相对强度"]) else None,
            "top_stocks": stocks,
        })

    profile = {
        "date": end_day,
        "main_line": data[0]["industry"] if data else None,
        "main_score": data[0]["score"] if data else None,
        "clarity": (
            "clear" if data and data[0]["score"] >= 0.7
            else "fuzzy" if data and data[0]["score"] >= 0.5
            else "rotating"
        ),
        "signal": signal,
        "sectors": data,
    }

    with open("data/main_line.json", "w") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    # 同时输出到 web/data/ 供H5前端使用
    import os
    web_data_dir = "web/data"
    os.makedirs(web_data_dir, exist_ok=True)
    web_path = os.path.join(web_data_dir, "main_line.json")
    with open(web_path, "w") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    print(f"  💾 JSON已导出 → data/main_line.json")
    print(f"  💾 前端版本 → {web_path}")


# ═══════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    run()
