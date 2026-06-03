# AGENTS.md - 股神

## 工作目录

- 项目根目录：`~/stock/`
- 数据目录：`~/stock/data/`
- Web 目录：`~/stock/web/`

## 常用命令

```bash
# 每日数据更新
bash ~/stock/daily.sh

# 仅增量拉取数据
uv run python -m ingest.incremental

# 初始化/刷新数据库
uv run python -m store.schema

# 导出 Web 数据
uv run python ~/stock/export_web_data.py

# 搜索股票
uv run python ~/stock/search_stock_csv.py <股票代码/名称>

# 本地预览
uv run python ~/stock/h5_server.py
```

## 数据源

- **Tushare Token**: 3d4b538562adcf05d601c99ae6e1f91a27d92267b558b2c4d7a8503e
- **数据库**: SQLite at `~/stock/data/stock.db`

## 模块说明

| 模块 | 功能 |
|------|------|
| ingest/ | 从 Tushare 拉取行情数据 |
| store/ | SQLite 数据库存储 |
| indicators/ | 技术指标计算 |
| strategy/ | 量化策略回测 |
| web/ | 前端展示（静态 JSON） |
