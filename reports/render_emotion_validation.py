"""Render the machine-readable emotion validation result as a concise report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def fmt(value: object) -> str:
    return "—" if value is None else f"{float(value):+.2f}%"


def render(payload: dict, limit_research: dict | None = None) -> str:
    strategies = payload["strategies"]
    audit = strategies[0]["validation"]["data_audit"] if strategies else {}
    lines = [
        "# 情绪策略长期验证报告",
        "",
        f"数据覆盖 {audit.get('period_start', '—')}—{audit.get('period_end', '—')}，"
        f"共 {audit.get('trading_days', 0):,} 个交易日、{audit.get('row_count', 0):,} 条行情、"
        f"{audit.get('stock_count', 0):,} 个证券代码。交易日日历缺口："
        f"{len(audit.get('calendar_missing_sessions', []))}。",
        "",
        "四套规则均使用收盘时已知数据，次日开盘执行；训练交易和同日基准必须在测试窗口开始前完成。"
        "每 252 日训练、随后 21 日样本外测试，买卖各计 0.10% 成本。信号日最多买 10 只，"
        "没有成交的资金留在现金，卖出受限时继续计价并顺延退出。",
        "",
        "## 结论",
        "",
        "没有情绪规则达到预设的可靠性门槛。E1 已有足够样本且长期失败，因此停用；"
        "E2—E4 的有效样本仍不足，只保留为研究观察。两年样本上的局部正收益未能扩展到十年历史。",
        "",
        "## 滚动样本外结果",
        "",
        "| 策略 | 状态 | 配对组合 | 完成交易 | 组合净收益均值 | 配对超额均值 | 总收益 | 最大回撤 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy in strategies:
        metric = strategy["walk_forward"]["metrics"]
        lines.append(
            f"| {strategy['name']} | {strategy['status_label']} | "
            f"{metric['paired_cohort_count']} | {metric['signal_count']} | "
            f"{fmt(metric['cohort_net_mean_pct'])} | {fmt(metric['excess_return_pct'])} | "
            f"{fmt(metric['total_return_pct'])} | {fmt(metric['max_drawdown_pct'])} |"
        )
    lines.extend([
        "",
        "E4 的 0% 收益表示滚动门控期间一直持有现金，并不表示原始信号没有风险。"
        "E3 尚有未退出持仓，未完成交易不计入完成交易均值，但仍进入每日净值与回撤。",
        "",
        "## 可靠性门槛",
        "",
        "至少需要 20 个策略与基准均完成的滚动样本外组合；配对超额的区块自助法区间下界大于 0；"
        "普通成本和每边 0.25% 的压力成本下总收益均为正。区间以连续 3 个组合为区块，"
        "采用固定随机种子重采样 4,000 次，并对四项策略进行 Bonferroni 校正。",
        "",
        "本轮还在 2015—2021 研究期和 2022—2023 验证期筛出 14 个恐慌反转配置，"
        "随后统一检查 2024—2026 冻结区间；14 个配置全部未通过校正后的超额检验，"
        "多数转为负收益。沪深 300 情绪仓位开关的参数组也没有一个同时通过研究期与验证期，"
        "因此未添加新的可执行卡片。失败结果保留，未据此继续微调冻结区间。",
    ])
    if limit_research:
        period_keys = (
            "development_2015_2020",
            "validation_2021_2023",
            "holdout_2024_2026",
        )
        lines.extend([
            "",
            "## 封板情绪扩展审计",
            "",
            "再按沪深主板普通 10% 涨跌停制度，使用 `pre_close` 与收盘涨跌幅构造跌停消退、"
            "涨停扩散、封板翻转和强势降温四条固定假设。开发期为 2015—2020，验证期为 "
            "2021—2023，2024—2026 仅作冻结检查。候选股票仍使用相同的次日开盘、持有五日、"
            "现金槽、成本与同日基准口径。",
            "",
            "| 假设 | 开发期净收益/超额 | 验证期净收益/超额 | 冻结期净收益/超额 | 结论 |",
            "|---|---:|---:|---:|---|",
        ])
        for item in limit_research["results"]:
            cells = []
            for key in period_keys:
                metric = item["periods"][key]
                cells.append(
                    f"{fmt(metric['cohort_net_mean_pct'])} / {fmt(metric['excess_return_pct'])}"
                )
            lines.append(
                f"| {item['name']} | {cells[0]} | {cells[1]} | {cells[2]} | 未通过 |"
            )
        lines.extend([
            "",
            "四条假设都没有同时通过开发期与验证期，因此均未进入策略模块。涨停扩散在后两段的"
            "绝对收益为正，但开发期显著为负，且冻结期相对同日基准仍为负；不能据后段表现反向"
            "挑选它。官方 `daily_basic.limit_status` 可访问但当前账号限速为每小时一次，完整十年"
            "逐日下载缺乏可操作性；同花顺涨停池、连板及龙虎榜接口当前账号无权限。",
        ])
    lines.extend([
        "",
        "## 数据审计",
        "",
        f"历史压缩归档 {audit.get('archive_sessions', 0):,} 个交易日，SQLite 近期数据 "
        f"{audit.get('sqlite_sessions', 0):,} 个交易日；读取时逐文件核对 SHA-256。"
        "交易日历来自新浪历史交易日历，行情来自 Tushare。",
        "",
        "另用新浪行情经 AKShare 对浦发银行、贵州茅台、平安银行、宁德时代抽样核对。"
        "浦发银行、平安银行和宁德时代重叠日收盘价 100% 一致；贵州茅台 99.82% 一致，"
        "2,274 个重叠日中 4 日差异超过 0.01 元。沪深交易所官网退市名单共整理出 333 个去重事件。",
        "",
        "## 已知限制",
        "",
        "历史风险警示状态、退市终值、真实开盘排队成交和冲击成本仍不完整。情绪指标是价格、"
        "成交量和市场广度的代理，没有使用新闻文本、龙虎榜或历史封单。历史伪样本外不能替代"
        "未来新增数据验证。",
        "",
        "数据字段口径：[Tushare A股日线](https://tushare.pro/document/1?doc_id=27)；"
        "退市资料：[上交所](https://www.sse.com.cn/assortment/stock/list/delisting/)、"
        "[深交所](https://www.szse.cn/market/stock/suspend/index.html)。",
        "",
        "## 复现",
        "",
        "```bash",
        "cd /Users/zgm/stock",
        ".venv/bin/python -m ingest.history_archive --start 20150101 --end 20260909",
        ".venv/bin/python -m ingest.security_history",
        ".venv/bin/python -m strategy.emotion --date 20260909 --output reports/emotion_validation_2015_20260909.json",
        ".venv/bin/python reports/emotion_limit_research.py --date 20260909 --output reports/emotion_limit_research_20260910.json",
        ".venv/bin/python reports/render_emotion_validation.py reports/emotion_validation_2015_20260909.json reports/emotion_validation_2015_20260909.md --limit-research reports/emotion_limit_research_20260910.json",
        ".venv/bin/python export_web_data.py --strategies-only",
        ".venv/bin/python -m unittest discover -s tests",
        "```",
        "",
        f"策略代码 SHA-256：`{payload['code_sha256']}`",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit-research", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text())
    limit_research = (
        json.loads(args.limit_research.read_text()) if args.limit_research else None
    )
    args.output.write_text(render(payload, limit_research))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
