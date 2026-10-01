# POE2 游玩工具项目指南

> 本文档面向 AI 编程助手。阅读前默认不了解本项目，以下内容基于仓库现有文件与用户确认的设计决策整理，请据此开展工作，不要自行假设。

---

## 1. 项目概述

本项目是为《流放之路 2》（Path of Exile 2，简称 POE2）开发的半自动化辅助工具，目标是把玩家从重复、高频的机械操作中解放出来。

核心设计原则：**人脑负责导航与高阶决策，脚本负责高频机械执行**。明确拒绝全自动化 Bot（自动寻路、自动探索地图、全自动刷宝）。

### 1.1 当前阶段

桌面端已于 2026-10-01 从 AutoHotkey 全量迁回 Python 分层架构（`poe2_tools/`：config / core / modules / bridge / ui，tkinter 界面），功能与 AHK 版等价（战斗宏 + 旋风数字检测 + 背包整理 + 货币坐标 + 石碑/地图速点），待游戏内人工验证。旧 AHK 版保留在 `ahk/` 目录作回退对照，**人工验证通过后才物理删除**。地图词缀 OCR 识别、石碑属性识别为二期规划，暂不开发。

### 1.2 主界面模块

| 模块 | 状态 | 说明 |
|------|------|------|
| Python 桌面端 | 待人工验证 | 战斗宏 + 旋风(OpenCV 模板匹配数字检测) + 背包整理 + 货币坐标 + 石碑/地图速点（poe2_tools/，tkinter 界面） |
| AHK 按键助手 | 已弃用，待删除 | ahk/ 目录，验证通过前保留作回退 |
| 地图词缀识别 | 二期规划 | OCR/OpenCV 词缀解析 + 高危词缀警告 |
| 石碑属性识别 | 二期规划 | 属性识别 + 合成路线推演 |

### 1.3 已确认的设计决策

- POE2 坐标体系与 POE1 一致，沿用两点标定 + CellSize 网格推导；坐标一律使用客户区坐标（与 AHK CoordMode Client 一致），点击时换算屏幕坐标
- **桌面端从 AHK 迁回 Python**（2026-10-01 变更，取代 09-30 的 AHK 决策；用户确认：先等价迁移，OCR 词缀识别二期；tkinter 界面保留作自动化工具，Web 前端定位是信息记录统计；`ahk/` 目录在人工验证通过后删除）
- **所有批量操作必须提供执行间隔配置**（2026-09-30 确认；间隔带随机抖动，保留人工操作痕迹）
- 代码复用方式：复制后独立适配，不抽公共包

---

## 2. 技术栈与运行环境

- **运行环境**：Windows 11 原生环境（禁止依赖 WSL）
- **语言**：Python 3.11+，使用 [uv](https://docs.astral.sh/uv/) 管理环境与依赖（桌面端与 Web 应用）
- **GUI**：tkinter（桌面端，`uv run python main.py`）
- **输入模拟**：`pydirectinput`（DirectInput 扫描码）+ `keyboard`（全局热键），封装在 `poe2_tools/core/`
- **视觉检测**：`mss` 截图 + `opencv-python` 模板匹配（旋风 Q/E 数字检测，替代 AHK FindText）
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
│   ├── core/               # 基础层：热键管理、窗口绑定、键鼠模拟、视觉检测、调度、时间规约
│   ├── modules/            # 业务模块：背包整理、石碑速点、地图速点、战斗宏、批量操作核心
│   ├── bridge/             # 进程内事件总线（bus）与可选 WebSocket 桥接
│   └── ui/                 # tkinter 界面
│       ├── app.py          # 主窗口与控制器：状态区 + 热键注册 + 标定/截图/急停 + 日志区
│       ├── profile_tab.py  # 配置1-4 页（8 行按键策略）
│       ├── cyclone_tab.py  # 旋风页（鼠标三键 + Q/E 数字检测标定/截图）
│       ├── coords_tab.py   # 坐标页（10 种货币标定）
│       ├── settings_panel.py  # 右侧功能设置区（热键/参数/保存）
│       └── widgets.py      # 共享小部件（KeyRowsFrame）与显示名映射
├── tests/                  # pytest 单元测试（纯逻辑）
├── web/                    # POE2 经济记录 Web 应用（FastAPI + React CDN + SQLite，独立于桌面工具）
│   ├── app.py              # FastAPI 入口：`uv run python -m web.app`（端口 8321）
│   ├── scraper.py          # 抓取+解析 poe2db.tw 14 个经济模块（解析与网络分离，便于测试）
│   ├── db.py               # SQLite schema 与读写（写操作全局锁串行化）
│   ├── icons.py            # 图标下载缓存到本地
│   ├── service.py          # 刷新任务编排与进度（手动单模块/全量）
│   ├── trading.py          # 交易助手纯逻辑：汇率图、最优兑换路径、套利环检测
│   ├── scheduler.py        # APScheduler 定时抓取（开服前 2 周每天抓，之后每周抓，可配置）
│   ├── static/             # index.html（React 18 CDN 单页）+ icons/（图标缓存，不入库）
│   └── data/               # economy.db（不入库）
├── poe2_tools.ini          # 本机标定与热键配置（UTF-8，不入库）
├── templates/              # 旋风 Q/E 数字模板图（界面「截图」生成，不入库）
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
- 分层约定：`core/` 只做硬件级能力（窗口/输入/热键/调度/视觉），`modules/` 组合 core 实现业务，`config/` 管配置，`bridge/` 管事件分发，`ui/` 只做展示与控制；上层可依赖下层，禁止反向依赖
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
