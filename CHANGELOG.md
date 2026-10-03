# 变更日志（汇总版）

> 本文件为 `changelog/` 明细文件的压缩汇总，按日期倒序组织。明细文件超过 10 个时合并至此并删除明细。
> 关键里程碑：**2026-09-30 桌面端 Python → AHK 重构**；**2026-10-01 AHK → Python 全量回迁**（`poe2_tools/` 分层架构，tkinter 界面）。

---

## 2026-10-03

### 交易菜单拆分与手动录入移除

- Web 新增一级菜单「交易」（经济 / 交易 / 策略 / 做装 / 开荒），原「交易助手」从经济·工具移入，重命名「默认」；新增「指定」「自动」三级页面，侧边栏二级菜单「市场比例」统一嵌套
- `trade_rates` 新增 `category` 列（default/custom/auto）：桌面端默认通货抓取 → 交易·默认页、指定抓取 → 交易·指定页、自动（预留）→ 交易·自动页；旧库迁移按 `item:` 单位回填 custom；同类别同方向只留最近一次，类别隔离互不影响
- 交易页移除全部手动录入（组件 + `POST /api/trade/rates` 接口），只读展示游玩工具同步数据；保留 VE 值设置、金币转化、最佳兑换、套利环、同步历史（可删除）；最佳兑换单位集合扩展为「三基础通货 + 该类别物品单位」
- 桌面端 `exchange.py`/`trade_module.py` 按类别发布并更新文案；pytest 218 项通过；API 与 Playwright 冒烟通过

### 交易模块：默认/指定通货批量抓取与同步

- 新增 `modules/market/exchange.py`：`DEFAULT_CURRENCIES`（崇高/混沌/神圣）、`default_pairs()`/`custom_pairs(name)`、`rates_from_scan()`（市场比率 x:y → side=buy 买边汇率）、`publish_rates()`（写 web/data/economy.db）、`ExchangeScanRunner`（顺序抓取多对，单对失败记 errors 继续，汇总一次性发布）
- `trade_rates` 新增 `source` 列（manual/auto）；`replace_auto_trade_rates()` 同方向旧自动记录先删后插，只留最近一次
- 交易模块页重构为四子页：默认通货（F9）/ 指定（F10）/ 自动（预留）/ 比例测试（F8）；`[MarketScan]` 新增 HotkeyDefault/HotkeyCustom/CustomCurrency；批量抓取在工作线程执行，结果不在桌面端展示
- 验证：pytest 216 项通过；同步链路端到端验证（入库 → API 最佳兑换含金金币折算）；游戏内抓取待人工验证

### 通货市场比例抓取模块（新增 modules/market/）

- `driver.py` 原子操作驱动（剪贴板/带修饰键点击 try/finally 释放/Ctrl+A/Ctrl+V 粘贴/mss 截屏，±30% 抖动）；`parser.py` OCR 解析纯逻辑（比例正则、库存特征模糊匹配含 OCR 混淆变体、千分位）；`ocr.py` RapidOCR 懒加载封装（可注入替身）；`scanner.py` 双向抓取控制器（Phase 2 Ctrl+左键反转方向），坐标复用开发页 point1~5/range3
- 迭代修正（游戏内实测反馈）：截屏去 Alt；解析放宽（有比例即有效，库存缺失为 None）；单方向失败隔离；库存跨行合并；坐标化行列重建（纵向聚类 + 行内配对，兼容库存左/右布局）；range3 偏移修正（RangeOffsetX/Y 默认 -10/+20）；结果只取前 3 条；搜索/选中延时加保守（300/1200/800/500ms）；空结果重试一次；调试截图存 logs/market/；完成后弹提示框
- 启动热键 F8（用户决策：所有功能必须提供游戏内启动热键）；测试 13 例（test_market_scanner.py）；全量 pytest 197 项通过

### 界面模块化重构

- 桌面端主界面重构：顶部全局状态栏 + 模块导航（战斗/通用/研发/交易，后移至运行状态区下方）+ StackedView 四模块 + 底部可折叠日志面板（级别着色/过滤）；战斗内嵌 配置1/旋风，通用内嵌 整理/石碑速点/地图速点，研发内嵌 开发/测试/坐标
- 配置模型层级化：`combat`/`general.sort`/`general.tablet`/`general.map_click`/`dev` 分组；ini 段更名 [Combat]/[Sort]/[Tablet]，按键级回退兼容旧段旧键；`bus.log` 支持日志级别
- 页面动作键作用域按「模块 + 子页」隔离（F5∈旋风/坐标/开发，F2∈测试），功能热键 POE2 前台即生效；pytest 184 项全绿

### 通用模块合并单页 + 热键捕获与瓦尔流程

- 通用模块三子标签合并单页：顶部汇总行展示热键；背包网格（行/列/格子间距）作为通用配置只保留一份；各功能独立参数分区平铺
- 热键行恢复按键捕获（后台线程 keyboard.read_key()，Esc 取消）+ 手动输入框双方式，保存配置后生效
- 地图速点瓦尔阶段简化：按住 Shift → 右键选中瓦尔一次 → 逐格左键，不再逐格重选；移除 MAP_RESELECT_KEYS 与 reselect_per_cell；500ms 最小间隔兜底保留

### 开发页：测量坐标与框选范围

- 新增「开发」页：6 个测量坐标（按钮 + F5，同坐标模块流程）+ 6 个框选范围（左键拖框，F5 重开，F12 取消）；`modules/measure.py`（normalize_range 规范化 + RangeMarkSession 旁观框选会话，<4×4 视为误触）；ini 新增 `[Measure]` 段；F5 标定路由扩展为三页
- 测试 9 项（test_measure.py）；pytest 178 项通过

### Web 菜单三级嵌套标准确立

- 全应用统一：顶部一级菜单 → 侧边栏二级菜单（`.side-l2` 纯分组）→ 三级菜单（`.side-item.sub` 页面）嵌套于二级下；不允许内容区自设菜单列
- 做装页从禁用改为可用：戒指 → 稀有度做装流程图（52% 稀有度 + 双 T1 点伤 + 抗性戒指，纯前端 FlowNode/FlowArrow 组件，含底材/双点伤+品质/洗后缀模块与两个放弃分支）
- 二次修正：经济模块（14 个）回滚为页内数据视图（内容区模块列），不拆分侧边栏页面；经济侧边栏只留赛季切换区 + 工具菜单
- `web/browser_check.py` 同步断言（35 项通过），截图 temp/browser/04、05

## 2026-10-02

### 刷图自动化修复与调整（Q6 检测 / 侧键 / 启动）

- Q6 匹配度 1px 容差修复：实况亮像素与模板完全相同但逐像素比对仅 0.919（抗锯齿边缘 1px 偏移），`mask_confidence` 改为实况二值图先膨胀 1px 再求交，实测匹配度 0.919 → 1.000
- 侧键切换 XButton1 → XButton2：新增侧键识别工具 `mapping/check_buttons.py`（mouse 钩子 + GetAsyncKeyState 双通道），确认用户习惯按的是 XButton2，配置默认值同步修改
- 刷图启动按钮改等待前台自动启动：点「启动」时 POE2 非前台进入 500ms 轮询（15 秒超时），切回游戏窗口即自动启动；修复此前按钮必失败的缺陷；注明 F2 不启动刷图助手

### 标签页热键独立 + 功能设置区加宽

- 功能热键（战斗/整理/石碑/地图/F3/F4）与标签页无关，POE2 前台即生效，战斗宏作用于当前激活配置页；页面级动作键归属各自页面（F5 标定→旋风/坐标，F2 记录→测试），同键冲突时动作键优先，页不对时日志提示归属页
- 窗口默认 960→1180 宽，功能设置区按自然宽度 ×2 固定

### 测试页：F2 输入记录与释放频率分析

- 新增 `modules/recorder/`：F2 切换记录鼠标全键位 + Q/E 按下（相对秒级时间戳，0.5s 防抖），每轮存 `logs/recordings/round-*.json`；纯逻辑分析过滤自动重复（<80ms）/停顿（>10s 切片段）/碎片（<5s），输出各键位次数/频率/中位间隔
- 「测试」标签页：状态 + 分析报告 + 清空；注意刷图助手停止时 unhook_all 会清钩子，记录期间勿启停

### 地图速点瓦尔漏点修复

- 瓦尔腐化有动画、点击后可能取消货币选中，阶段开始只选一次导致后续点击被吞
- `apply_currency_to_bag` 新增 `reselect_per_cell`（每格前重新右键选中，幂等安全）；`MAP_RESELECT_KEYS={"vaal"}` + `MAP_MIN_INTERVAL_MS={"vaal":500}`，瓦尔阶段逐格重选且间隔不低于 500ms
- 验证：pytest 169 项全部通过；游戏内人工验证待做

## 2026-10-01

### 刷图自动化（极简健康刷图，新增模块）

- 新增 `modules/mapping/`：三线程生产者-消费者（dxcam 截图 → 视觉仲裁 → SendInput 执行），确定性 FSM（IDLE/MOVING/LOOTING/COMBOS）严格优先级仲裁；loot 黑框过滤管道、Q=6 点阵识别（自适应局部二值化 + 对比度守卫）、拾取黑名单（网格量化 + 5s）、输入 jitter、I/Tab/Esc UI 挂起感知、失焦强制 IDLE
- 新依赖 dxcam（0.3.0，`create()` 参数为 `output_color`，代码内 TypeError 回退）与 pywin32
- 同日并入旋风页：Q=6 检测复用旋风 Q 坐标 ±30px 与 `templates/q.png` 二值化掩模，删除独立「刷图」Tab 与 `calibrate_q_template` 等旧标定

### 旋风页精简与 Q6 右键两角标定

- 移除旋风 Q/E 数字检测（`CycloneWatcher`、`core/vision.py` 整模块、`cyclone_coords` 等），旋风页只保留鼠标三键策略
- Q6 标定改 F5 + 右键两角标记：`calibrate.py` 的 `Q6MarkSession` 右键钩子会话 + `normalize_roi` 纯逻辑 + 截图存 `templates/q6.png`；启动时对 ROI 截图做匹配测试（实况图存 `q6_live.png`，匹配度写 `logs/mapping.log`）
- （注：F5 标定 Q6 精确区域曾短暂用「截右下角 + 连通域自动提取紧框」方案，同日被右键两角标记取代）

### 刷图执行日志与 Q6 热重载

- 修复先启动助手后 F5 标定时掩模恒为 None 的缺陷：`reload_q6` 热重载 + 禁用状态每 2 秒自动重试加载
- 新增 `mapping/mlog.py` 文件日志（`logs/mapping.log`，毫秒时间戳）：启动配置摘要、FSM 转移、动作链摘要、黑名单、Q 匹配度节流输出、急停来源

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
