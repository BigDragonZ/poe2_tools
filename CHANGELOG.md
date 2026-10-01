# 变更日志（汇总版）

> 本文件为 `changelog/` 明细文件的压缩汇总，按日期倒序组织。明细文件超过 10 个时合并至此并删除明细。
> 关键里程碑：**2026-09-30 桌面端 Python → AHK 重构**；**2026-10-01 AHK → Python 全量回迁**（`poe2_tools/` 分层架构，tkinter 界面）。

---

## 2026-10-01

### 桌面端 AHK → Python 全量重构

- 新建 `poe2_tools/` 五层架构：`ui/`（tkinter）→ `modules/`（业务）→ `core/`（窗口/输入/热键/调度/视觉），`config/` 共享配置，`bridge/` 事件总线 + 可选 WebSocket 桥（默认关闭，仅 127.0.0.1）
- 功能与 AHK 版等价：战斗宏（10ms 节拍 + SpamScheduler 到期时间驱动，±15% 抖动下限 50ms）、背包整理、石碑/地图速点、货币坐标（三级 +70/+140px 推导）、旋风 Q/E 数字检测（边沿触发，2 秒/次）
- 视觉检测 FindText → OpenCV：`templates/q.png`、`e.png` 由界面「截图」生成，`cv2.matchTemplate`（阈值 0.9，±30px 搜索），无模板时白色像素兜底；全黑帧/常量模板防护不误判
- AHK 旧配置自动迁移：`decode_ahk_ini` 容错解码混合编码（UTF-8 BOM + GBK 节名），模式 int→字符串，FindText 字库代码丢弃改由截图重新生成
- 新增依赖 opencv-python / mss / pillow；删除旧单文件实现（`poe2_tools/bag.py`、`combat.py`、`common.py`）与旧 ui 三个 tab
- 验证：pytest 101 项全部通过；游戏内人工验证待做（通过后才删除 `ahk/` 目录）

### 界面调整：精简配置页 + 窗口加宽

- 配置页 4 → 1（`PROFILE_COUNT=1`，旋风页序号派生为 `PROFILE_COUNT+1`）；标签页变为 配置/旋风/坐标 三个，AHK 迁移只迁「配置1」
- 窗口默认 780x680 → 960x680，保证右侧功能设置区完整展示
- 验证：pytest 104 项全部通过

### 战斗连点抖动改为毫秒级设置

- `KeyConfig.random_jitter: bool` → `jitter_ms: int`（默认 15ms）：实际间隔 = 执行间隔 + 0~jitter_ms（只加不减），下限 50ms
- ini 键 `{key}_random` → `{key}_jitter`，读取兼容旧布尔键（1 折算为间隔 15%）；AHK 迁移同样折算；UI 抖动列改为毫秒输入框
- 批量操作 ±30% 比例抖动不变；pytest 109 项全部通过

## 2026-09-30

### AHK 按键助手（桌面端 Python → AHK 重构，里程碑）

- 新增 `ahk/poe2_key_helper.ahk`（AHK v2，约 440 行）：战斗宏（配置 1-4，后精简为 8 键行，禁用/连点/按住，失焦自动停止）、F3/F4 两点标定背包存仓、F12 全局急停释放所有按键、`HotIfWinActive` 热键作用域、ini 持久化（UTF-8）
- 战斗宏重写：修 SetTimer 竞态报错与间隔漂移，改 10ms 单调度器 + 到期时间驱动 + SendInput，间隔误差 ≤10ms
- 坐标页：三级货币只标一级（+70/+140px），普通货币单独标定，F5 游戏内记录；石碑速点（F6）/地图速点（F7，点金×1→崇高×4→瓦尔×1），完成后自动触发背包整理；抽出通用 `ApplyCurrencyToBag`/`RunDump` 批量操作
- 背包整理提速：间隔下限 5ms、默认 30ms；瞬间移动 + `SendInput("{Blind}{Click}")`；新增「整理间隔」配置，确认设计决策「所有批量操作必须提供执行间隔配置」
- 旋风页：鼠标三键策略 + Q/E 数字检测触发（白色像素检测，边沿触发，后改 FindText 图像匹配 + 字库代码持久化，修 v2.0 兼容问题，调试日志 `cyclone_debug.log`，全黑帧保护）
- 验证：`/validate` 语法校验通过 + 启动冒烟正常；游戏内行为待人工验证，未提交

### 信息库页面（Web）

- 新增 `item_info` 表与 wiki 抓取：`parse_wiki_item_info` 提取 Currency Exchange 金币值、按 CJK 拆分中/英文名；`POST /api/library/refresh`（missing/all，限速 ≥1 秒/次，单物品失败不中断）
- `LibraryPage` 组件：服务端模糊检索（防抖 300ms）、模块过滤、金币列排序、抓取进度轮询
- 验证：pytest 66 项全部通过；112 个物品真实抓取成功（神聖石 800、混沌石 160 等入库）

### 交易助手（Web 交易页）

- `web/trading.py`：汇率图（三通货 + 物品统一为有向边）、`best_conversion` 简单路径 DFS 求最优兑换（防环放大）、`find_profitable_cycles` 套利环检测（旋转去重）
- `trade_rates` 表持久化全部录入历史；API 增 state/rates/删除；前端平铺录入（三通货 6 方向 + 物品买卖 6 行）+ 最佳方案 + 套利机会 + 历史
- 追加金币市场模型：买/卖侧分开录入，有效汇率折算金币费（VE 值，可手动覆盖，缺省回退信息库），计入金币费后伪套利不误报
- 验证：pytest 74 项全部通过；端到端 API 校验与浏览器联动验证通过

## 2026-09-15

### 经济页面布局调整

- 左侧边栏只保留赛季列表，14 个经济模块移至主内容区独立列（`.module-col`）显示，表格在右
- `web/browser_check.py` 同步选择器并新增布局断言，25 项浏览器自动化验证全部通过

## 2026-09-14

### POE2 经济记录 Web 应用（新增）

- 全新独立 Web 应用 `web/`：FastAPI（`uv run python -m web.app`，端口 8321）+ React 18 CDN 单页 + SQLite；抓取 poe2db.tw 14 个经济模块（解析与网络分离，限速 ≥1 秒）
- `db.py` schema（seasons/modules/items/snapshots/fetch_runs/settings，写操作全局锁）；图标本地化缓存；APScheduler 定时抓取（开服 14 天内每天、之后每周，可配置）
- 价格基准神圣石：记录混沌⇄神圣汇率，同存 price_divine 与换算后 price_chaos；前端复刻原站深色四列样式，支持排序/中英文搜索/开服天数筛选
- 09-15 修复：babel-standalone automatic JSX 运行时导致空白页（改 classic runtime）；新增 `web/browser_check.py` Playwright 自动化验证（24 项通过）
- 验证：pytest 44 项全部通过；真实抓取 107 个物品、118 个图标入库，页面渲染与原站一致

## 2026-09-13

### 项目骨架与主界面

- 初始化 git 仓库（origin `BigDragonZ/poe2_tools`，main 分支）；uv 项目骨架（pydirectinput/keyboard/mouse + pytest）
- tkinter 主界面：四标签页（背包整理/战斗/地图占位/装备占位）；`AGENTS.md`、docs 文档、changelog/response.md 工作流规范

### 背包整理模块迁移（poe1 → poe2）

- 迁移 `common.py`（UTF-8 配置、POE2 窗口检测）与 `bag.py`（F3/F4 两点标定、一键存仓，抽出纯函数 `grid_points()`）
- 主窗口接入热键（整理 F1 / 标定 F3/F4 / 急停 F12）、500ms 状态刷新、共享日志区；pytest 18 项单测

### 战斗模块迁移（poe1 → poe2）

- 迁移 `combat.py`：七键策略（禁用/连点/按住不放）、POE2 失焦自动停止；F2 启停、F12/关窗释放所有按键
- 验证：pytest 25 项全部通过；背包整理（F3/F4 标定、F1 落点、F12 急停、失焦停止）游戏内人工验证通过
