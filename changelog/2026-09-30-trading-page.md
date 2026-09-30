# 2026-09-30 交易助手（Web 交易页）

## 需求

经济 Web 应用新增「交易」页：用户在游戏内观测兑换比例后手动录入，工具据此计算最佳兑换方案，并根据差价发现套利机会；所有录入持久化收集，为后续智能优化积累数据。

## 变更

- `web/trading.py`（新增）：交易助手纯逻辑
  - 汇率图：基础通货 exalted/chaos/divine + 物品（`item:名称`）统一为有向边
  - `best_conversion`：简单路径 DFS 求两通货间兑换率最高路径（不重复节点，避免套利环无限放大）
  - `find_profitable_cycles`：枚举乘积 > 1 的简单环，按收益率降序，旋转去重
- `web/db.py`：新增 `trade_rates` 表（方向、双方数量、录入时间，全量保留历史）及读写函数；物品名联想与按名称查图标
- `web/app.py`：新增 `GET /api/trade/state`（最新比例/历史/最优方案/套利环）、`POST /api/trade/rates`（校验单位与正数）、`DELETE /api/trade/rates/{id}`
- `web/static/index.html`：左侧边栏新增「工具 → 交易助手」入口（经济页内切换，不占顶部导航），含四部分：
  1. 三通货互换比例：6 个兑换方向全部平铺逐行录入（无下拉框）+ 最新比例表
  2. 物品 ⇄ 三通货比例：3 通货 × 买卖 2 方向共 6 行平铺录入，物品名带联想
  3. 最佳兑换方案（绕行优于直兑时标注）+ 套利机会展示
  4. 录入历史（可删除误录）
- `tests/test_trading.py`（新增）：13 项单测覆盖最优路径（直兑/绕行/经物品/无路径/防环放大）与套利环（双边/三边/平衡排除/旋转去重/排序）
- 文档：`docs/功能说明.md` 增加交易助手说明与验证记录；`AGENTS.md` 结构补充 `web/trading.py`

## 验证

- `uv run pytest`：57 项全部通过（含新增 13 项）
- 端到端：8322 端口启动应用，API 录入/删除/校验非法输入正常；桌面浏览器自动化打开「交易」页，表单录入 1 神圣=300 混沌后最新比例表、最佳方案、历史即时刷新，验证后清理测试数据

---

## 2026-09-30 追加：金币交易市场模型（买/卖侧 + Currency Exchange 值）

### 需求

POE2 中神圣/混沌/崇高可通过市场消耗金币交易。模块一分为买、卖两部分，用户观测实时交易信息手动填写；基于交易比例与金币费计算金币 ⇄ 通货转化比例。规则：出售不需要金币；金币 = 购买的通货数量 × 该通货的 Currency Exchange 值（VE）。

### 变更

- `web/trading.py`：`effective_rate`（买边有效汇率 = r / (1 + r×VE(to)/VE(from))，金币费折算成支付方通货）；`gold_conversion`（1 通货 = VE 金币、1 金币 = 1/VE 通货、1 金币经最优路径折合混沌）；`best_conversion` / `find_profitable_cycles` 接受 gold_values，计入金币费后伪套利不再误报
- `web/db.py`：`trade_rates` 加 `side` 列（buy/sell，init_db 对旧库 ALTER TABLE 迁移）；`latest_trade_rates` 按 (from, to, side) 取最新；`get_gold_costs_by_slugs`（从信息库 item_info 取 VE，表不存在时优雅回退）
- `web/app.py`：`TradeRateIn` 加 side 校验；`PUT /api/trade/gold_values`（手动覆盖 VE，清空回退信息库值）；state 增加 gold_values（含来源 manual/library）与 gold_conversion
- `web/static/index.html`：模块一拆「买入（付金币，行内实时显示费用）」「卖出（免金币）」两部分平铺；顶部 Currency Exchange 值表单（标注信息库来源）；金币 ⇄ 通货转化比例表；最新比例/历史加买/卖类型列；最优路径买边标 [买]
- `tests/test_trading.py`：+9 项（有效汇率、买边折费最优路径、金币转化、缺 VE 回退、计入金币费的伪套利排除）

### 验证

- `uv run pytest`：74 项全部通过
- 端到端：API 校验 side 存储、金币费有效汇率（300 混沌买 1 神圣 + 2500 金币 → 有效 1/350）、伪套利被排除；浏览器验证金币费行内联动（1 崇高买 20 混沌 → 提示 1000 金币）、手动费率覆盖与清空后回退信息库值（崇高 120 / 混沌 160 / 神圣 800）
