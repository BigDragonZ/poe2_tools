# POE2 游玩工具项目指南

> 本文档面向 AI 编程助手。阅读前默认不了解本项目，以下内容基于仓库现有文件与用户确认的设计决策整理，请据此开展工作，不要自行假设。

---

## 1. 项目概述

本项目是为《流放之路 2》（Path of Exile 2，简称 POE2）开发的半自动化辅助工具，目标是把玩家从重复、高频的机械操作中解放出来。

核心设计原则：**人脑负责导航与高阶决策，脚本负责高频机械执行**。明确拒绝全自动化 Bot（自动寻路、自动探索地图、全自动刷宝）。

### 1.1 当前阶段

桌面端已于 2026-10-01 从 AutoHotkey 全量迁回 Python 分层架构（`poe2_tools/`：config / core / modules / bridge / ui，tkinter 界面）；同日旋风页精简为鼠标三键策略（原 Q/E 数字检测已移除），功能含战斗宏 + 背包整理 + 货币坐标 + 石碑/地图速点，待游戏内人工验证。旧 AHK 版保留在 `ahk/` 目录作回退对照，**人工验证通过后才物理删除**。地图词缀 OCR 识别、石碑属性识别为二期规划，暂不开发。

### 1.2 主界面模块

| 模块 | 状态 | 说明 |
|------|------|------|
| Python 桌面端 | 待人工验证 | 战斗宏 + 旋风(鼠标三键策略) + 背包整理 + 货币坐标 + 石碑/地图速点（poe2_tools/，tkinter 界面） |
| 刷图自动化 | 待人工验证 | 三线程（dxcam 截图/视觉仲裁/SendInput 执行）+ 确定性 FSM；侧键切换移动/拾取/连招，Q=6 检测用 F5 + 右键两角标记区域（poe2_tools/modules/mapping/，控制并入「旋风」页） |
| 测试页（输入记录分析） | 待人工验证 | F2 切换记录鼠标按键与 Q/E 按下，按轮存 logs/recordings/；分析过滤自动重复/抖动、排除停顿，提取技能释放频率（poe2_tools/modules/recorder/，「测试」页） |
| 开发页（测量坐标与框选范围） | 待人工验证 | 收集开发阶段信息：6 个测量坐标（按钮 + F5，同坐标模块流程）+ 6 个框选范围（开启后左键拖框），结果存 ini [Measure] 段（poe2_tools/modules/measure.py，「开发」页） |
| 交易模块（市场比例抓取） | 待人工验证 | 内嵌 默认通货/指定/自动/比例测试 子标签：默认=三默认通货两两抓取（F9）、指定=指定通货×三默认（F10）、自动=套利批量抓取（F11：通货快照 0.5~20 神圣候选 × 三默认，比例写 web/data/economy.db（source=auto + category 区分页面，同类别整批替换、只保留最近一次抓取记录），分别输出到 Web 交易菜单「默认」「指定」「自动」页，每轮口径最佳套利方案与套利复核由对应页面计算展示；比例测试=A/B 双向抓取调试（F8）（poe2_tools/modules/market/，「交易」页） |
| AHK 按键助手 | 已弃用，待删除 | ahk/ 目录，验证通过前保留作回退 |
| 地图词缀识别 | 二期规划 | OCR/OpenCV 词缀解析 + 高危词缀警告 |
| 石碑属性识别 | 二期规划 | 属性识别 + 合成路线推演 |

### 1.3 已确认的设计决策

- POE2 坐标体系与 POE1 一致，沿用两点标定 + CellSize 网格推导；坐标一律使用客户区坐标（与 AHK CoordMode Client 一致），点击时换算屏幕坐标
- **桌面端从 AHK 迁回 Python**（2026-10-01 变更，取代 09-30 的 AHK 决策；用户确认：先等价迁移，OCR 词缀识别二期；tkinter 界面保留作自动化工具，Web 前端定位是信息记录统计；`ahk/` 目录在人工验证通过后删除）
- **所有批量操作必须提供执行间隔配置**（2026-09-30 确认；间隔带随机抖动，保留人工操作痕迹）
- **功能热键属于功能、不绑标签页**（2026-10-02 确认）：战斗/整理/石碑/地图/F3/F4 在 POE2 前台即生效，战斗宏作用于当前激活配置（切换配置/旋风标签页 = 切换激活配置）；页面级动作键归属各自页面（F5 标定→旋风/坐标/开发，F2 记录→测试），功能热键与当前页动作键同键时动作键优先；F12 急停始终全局
- **所有功能必须提供启动热键**（2026-10-03 确认）：每个功能都要能在游戏内按热键手动启动/切换，不能只靠界面按钮（如市场抓取 F8）
- 代码复用方式：复制后独立适配，不抽公共包

---

## 2. 技术栈与运行环境

- **运行环境**：Windows 11 原生环境（禁止依赖 WSL）
- **语言**：Python 3.11+，使用 [uv](https://docs.astral.sh/uv/) 管理环境与依赖（桌面端与 Web 应用）
- **GUI**：tkinter（桌面端，`uv run python main.py`）
- **输入模拟**：`pydirectinput`（DirectInput 扫描码）+ `keyboard`（全局热键），封装在 `poe2_tools/core/`；刷图自动化模块（`modules/mapping/`）例外：用 SendInput（pywin32 常量 + ctypes 调用）+ `mouse` 侧键监听，为其独立技术栈契约
- **视觉检测**：刷图自动化模块用 `dxcam`（Desktop Duplication）整帧采集 + OpenCV 二值化点阵比对管道，dxcam 必须懒导入隔离在 capture.py；标定与启动测试的小区域截图用 `mss`
- **测试**：pytest（纯逻辑单元测试）+ 游戏内人工验证

### 架构约束

- 禁止内存读取、注入、Hook 等侵入式技术
- 所有点击/按键需加入随机延迟，保留人工操作痕迹
- 任何可能卡住的按键操作都要在 `finally` 或急停函数中释放按键

---

## 3. 代码组织

```
D:/game/poe2_tools/
├── main.py                 # Python 桌面端入口（薄壳，调用 poe2_tools.ui.app.run_app）
├── ahk/                    # 旧版 AHK 按键助手（已弃用，人工验证通过后删除）
│   ├── poe2_key_helper.ahk # 旧版主程序（回退对照用）
│   └── poe2_key_helper.ini # 旧版配置（启动时自动迁移到 poe2_tools.ini）
├── poe2_tools/             # Python 桌面端（AHK → Python 重构后）
│   ├── config/             # 配置模型与 ini 读写（settings.py）、AHK 配置迁移（migrate.py）
│   ├── core/               # 基础层：热键管理、窗口绑定、键鼠模拟、调度、时间规约
│   ├── modules/            # 业务模块：背包整理、石碑速点、地图速点、战斗宏、批量操作核心、开发测量（measure.py：范围规范化 + 左键框选会话）
│   │   └── mapping/        # 刷图自动化：dxcam 截图 + 视觉仲裁 FSM + SendInput 执行 + F5/右键两角标记 Q6 区域（calibrate.py）+ 文件日志（mlog.py → logs/mapping.log）
│   │   └── recorder/       # 测试页输入记录：F2 采集鼠标/Q/E 按下（recorder.py → logs/recordings/）+ 释放频率分析（analysis.py 纯逻辑）
│   │   └── market/         # 通货市场比例抓取：UI 原子驱动（driver.py）+ OCR 文本解析（parser.py 纯逻辑）+ RapidOCR 封装（ocr.py）+ 双向抓取控制器（scanner.py，坐标复用 [Measure] point1~5/range3/range5）+ 默认/指定/自动批量抓取与交易菜单同步（exchange.py → web/data/economy.db，source=auto + category=default/custom/auto 整批替换只留最近一次抓取，含双向一致性复核：价差超 10 倍的异常对不发布；抓取前置「沒有存貨」检查：range5 区域识别到无存货提示则该方向按无挂单处理）+ 自动套利编排（arbitrage.py：通货快照候选筛选 + auto_pairs + category=auto）
│   ├── bridge/             # 进程内事件总线（bus）与可选 WebSocket 桥接
│   └── ui/                 # tkinter 界面（运行状态区 + 顶部模块导航 + 模块内高内聚配置，2026-10-03 重构）
│       ├── app.py          # 主窗口与控制器：状态区 + 模块导航 + StackedView 四模块 + 热键注册 + 标定/急停
│       ├── stacked.py      # StackedView：Frame 堆叠切换（等价 QStackedWidget）
│       ├── log_panel.py    # 全局日志面板：可折叠/展开 + 级别着色 + 级别过滤
│       ├── combat_module.py   # 战斗模块（内嵌 配置1/旋风 子标签 + 战斗宏热键）
│       ├── general_module.py  # 通用模块（整理/石碑速点/地图速点合并单页：背包网格通用 + 各自参数热键；热键支持按键捕获 + 手动输入）
│       ├── dev_module.py      # 研发模块（内嵌 开发/测试/坐标 子标签 + 调试模式/日志级别）
│       ├── trade_module.py    # 交易模块（内嵌 默认通货/指定/自动/比例测试 子标签；批量抓取结果按类别同步 Web 交易·默认/指定/自动页，不在本页展示；自动页=候选筛选预览+套利批量抓取）
│       ├── profile_tab.py  # 配置子页（8 行按键策略）
│       ├── cyclone_tab.py  # 旋疯子页（鼠标三键 + 刷图自动化控制分区）
│       ├── coords_tab.py   # 坐标子页（10 种货币标定）
│       ├── recorder_tab.py # 测试子页（输入记录状态 + 分析报告 + 清空）
│       ├── dev_tab.py      # 开发子页（6 测量坐标 F5 + 6 框选范围左键拖框，存 ini [Measure]）
│       └── widgets.py      # 共享小部件（KeyRowsFrame）与显示名映射
├── tests/                  # pytest 单元测试（纯逻辑）
├── web/                    # POE2 经济记录 Web 应用（FastAPI + React CDN + SQLite，独立于桌面工具）
│   ├── app.py              # FastAPI 入口：`uv run python -m web.app`（端口 8321）
│   ├── scraper.py          # 抓取+解析 poe2db.tw 14 个经济模块（解析与网络分离，便于测试）
│   ├── db.py               # SQLite schema 与读写（写操作全局锁串行化）
│   ├── icons.py            # 图标下载缓存到本地
│   ├── service.py          # 刷新任务编排与进度（手动单模块/全量）
│   ├── trading.py          # 交易页纯逻辑：汇率图、最优兑换路径、套利环检测、每轮口径最优套利方案（1 单位起点，通货/万金币转换率，best_arbitrage_round/arbitrage_opportunities）+ 方案独立复核 + 套利候选筛选
│   ├── scheduler.py        # APScheduler 定时抓取（开服前 2 周每天抓，之后每周抓，可配置）
│   ├── static/             # index.html（React 18 CDN 单页）+ icons/（图标缓存，不入库）
│   └── data/               # economy.db（不入库）
├── scripts/                # 应用管理脚本（app.sh：启动/关闭/重启/查看 Web 应用与桌面端，日志 → logs/web.log、logs/desktop.log）
├── 应用管理.sh             # 应用管理命令速查（复制粘贴用，不直接执行）
├── poe2_tools.ini          # 本机标定与热键配置（UTF-8，不入库）
├── templates/              # 刷图 Q6 模板（q6.png / q6_live.png，界面标定/启动测试生成，不入库）
├── logs/                   # 刷图执行日志（mapping.log，不入库）
├── docs/                   # 项目文档与功能文档
├── changelog/              # 变更日志明细（见第 5 节规范）
├── CHANGELOG.md            # 汇总后的变更日志
├── response.md             # 最近一次问答记录（见第 5 节规范）
├── promot/                 # 需求与设计草稿
├── pyproject.toml          # uv 项目配置
└── uv.lock                 # 依赖锁定
```

### 命名与注释

- 注释与用户可见文案使用中文
- Python：常量全大写下划线，函数 `snake_case`，类 `PascalCase`
- 分层约定：`core/` 只做硬件级能力（窗口/输入/热键/调度），`modules/` 组合 core 实现业务，`config/` 管配置，`bridge/` 管事件分发，`ui/` 只做展示与控制；上层可依赖下层，禁止反向依赖
- 桌面端新功能加入 `poe2_tools/modules/`；`main.py` 保持薄壳

---

## 4. 构建、运行与测试

1. 首次运行前执行 `uv sync` 安装依赖
2. `uv run python main.py` 启动 Python 桌面端主界面（tkinter，自动化工具）
3. `uv run python -m web.app` 启动经济记录 Web 应用（http://127.0.0.1:8321 ）
4. `uv run pytest` 运行单元测试
5. （过渡期待删）AHK 语法校验：Git Bash 中需双斜杠防止路径转换：`"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe" //ErrorStdOut //validate ahk/poe2_key_helper.ahk`

### 验证策略

- 纯逻辑（网格计算、配置读写、热键解析）必须有 pytest 单元测试
- 游戏内行为依赖人工验证，验证项记录在 `docs/功能说明.md` 的待完成清单中，人工验证后更新状态

---

## 5. 工作流规范（AI 助手必须遵守）

### 5.1 changelog 规范

- 每个功能开发完成后，在 `changelog/` 下新增明细文件，命名格式：`changelog/YYYY-MM-DD-功能名.md`
- `changelog/` 下明细文件超过 10 个时，合并汇总进 `CHANGELOG.md`，然后删除明细文件
- 功能开发验证通过后，提交并推送到 GitHub（origin: `git@github.com:BigDragonZ/poe2_tools.git`，主分支 `main`）

### 5.2 response.md 规范

- 每次向用户提问并得到回答后，将回答内容写入根目录 `response.md`
- 覆盖旧内容，只保留最近一次回答

### 5.3 文档规范

- 项目文档（`docs/项目框架.md`）：记录项目框架等整体性内容，结构变化时同步更新
- 功能文档（`docs/功能说明.md`）：解释各模块功能及使用方式，含待完成清单

---

## 6. 安全与合规

- 仅使用输入模拟，不读取游戏内存、不注入 DLL、不 Hook 游戏进程
- 不实现自动寻路、自动地图探索、全自动刷宝等全 Bot 功能
- 全局停止键必须能在脚本卡死时强制释放被按下的键
- 即便如此仍存在被行为检测识别的风险，使用者自行承担
