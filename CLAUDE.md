# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 本仓库的完整项目指南在 [AGENTS.md](AGENTS.md)（模块状态、设计决策、目录结构、工作流规范），该文件是本文件的权威来源，遇到冲突以它为准。以下内容只补充 AGENTS.md 未覆盖或需要跨文件阅读才能理解的要点。

## 常用命令

```bash
uv sync                                # 安装依赖（首次运行前）
uv run python main.py                  # 启动桌面端（tkinter）
uv run python -m web.app               # 启动 Web 应用（http://127.0.0.1:8321）
uv run pytest                          # 全部单元测试
uv run pytest tests/test_map_vaal.py   # 单个测试文件
uv run pytest tests/test_map_vaal.py -k "stash"  # 按名称过滤
bash scripts/app.sh help               # 启动/关闭/重启 Web 与桌面端（日志 → logs/）
```

- 测试只覆盖纯逻辑（pytest，`tests/`）；所有涉及游戏内行为的改动依赖人工验证，验证项记录在 `docs/功能说明.md` 待完成清单。
- Windows 原生环境，禁止依赖 WSL。

## 大局架构（跨文件要点）

### 两套并行的输入/视觉技术栈，不要混用

- **`poe2_tools/core/`（默认栈）**：`pydirectinput`（DirectInput 扫描码）+ `keyboard`（全局热键）+ `mss`（小区域截图）。绝大多数模块走这条路。
- **`poe2_tools/modules/cyclone/`（独立栈）**：SendInput（pywin32 常量 + ctypes）+ `mouse` 侧键监听 + `dxcam`（Desktop Duplication）整帧采集 + OpenCV 二值化。这是旋风引擎的独立技术栈契约，`dxcam` 必须懒导入并隔离在 `cyclone/capture.py`。

### 分层依赖方向是硬性约束

`ui/`（展示控制）→ `modules/`（业务）→ `core/`（硬件能力）→ `config/`（配置）。上层可依赖下层，禁止反向依赖。`main.py` 保持薄壳。新功能放 `poe2_tools/modules/`。

### 热键分派规则（ui/app.py，行为不直观）

功能热键（战斗/整理/石碑/地图/F3/F4）在 POE2 前台即生效、不绑标签页；战斗热键在旋风页分派给旋风引擎，否则作用于当前激活配置；页面级动作键（F5 标定→旋风/坐标/开发，F2 记录→测试）与功能热键同键时**动作键优先**；F12 急停始终全局且必须能强制释放卡住的按键。改热键相关代码前先读 `core/hotkey.py` 与 `app.py` 的注册逻辑。

### 坐标与配置

- 坐标一律用客户区坐标（同 AHK CoordMode Client），点击时换算屏幕坐标；两点标定 + CellSize 网格推导。
- 本机配置在 `poe2_tools.ini`（UTF-8，不入库）；测量坐标/框选范围存 `[Measure]` 段，被市场抓取（`modules/market/scanner.py`）等多个模块复用。
- 代码复用方式：**复制后独立适配，不抽公共包**（用户确认的决策）。

### Web 应用（`web/`）是独立信息记录统计端

FastAPI + React CDN 单页 + SQLite（`web/data/economy.db`）。桌面端的市场抓取模块（`modules/market/exchange.py`）按类别（default/custom/auto）整批替换写入该库，同类别只保留最近一次抓取；套利计算在 `web/trading.py` 纯逻辑中完成。

## 修改后必须做的事（AGENTS.md §5 摘要）

1. 功能完成后写 `changelog/YYYY-MM-DD-功能名.md`；明细超过 10 个时汇总进 `CHANGELOG.md` 并删除明细。
2. 向用户提问得到回答后，覆盖写入根目录 `response.md`（只留最近一次）。
3. 结构变化同步 `docs/项目框架.md`；功能/使用方式变化同步 `docs/功能说明.md`。
4. 注释与用户可见文案用中文。
