# 2026-10-01 桌面端 AHK → Python 全量重构

## 背景

用户确认三项设计决策（2026-10-01，取代 09-30 的 AHK 决策）：

1. **先等价迁移**：桌面端从 AutoHotkey v2 全量迁回 Python，功能与 AHK 版等价（战斗宏 + 旋风数字检测 + 背包整理 + 货币坐标 + 石碑/地图速点），OCR 词缀识别二期再做
2. **tkinter 界面保留**：Python 桌面端用 tkinter 作自动化工具界面；Web 前端定位是信息记录统计，不受影响
3. **ahk/ 目录在人工验证通过后物理删除**，验证前保留作回退对照

## 架构分层

`poe2_tools/` 按职责分五层，上层可依赖下层、禁止反向依赖（详见 `docs/architecture.md`）：

- `ui/`（tkinter）→ `modules/`（业务）→ `core/`（硬件级能力）
- `config/` 横向共享配置模型；`bridge/` 管事件分发（进程内总线 + 可选 WebSocket）

## 各层文件清单与职责

- **config/**
  - `settings.py`：配置模型（Settings/KeyConfig/Point）与 ini 读写（UTF-8，configparser）；全部常量（按键清单、模式、抖动、旋风检测、货币分级）；`currency_coord()` 三级货币向右推导（+70/+140px）
  - `migrate.py`：AHK 旧配置迁移（见下「配置迁移」）
- **core/**
  - `window.py`：POE2 窗口查找/前台检测/客户区↔屏幕坐标换算（ctypes user32）
  - `input.py`：pydirectinput 键鼠封装（AHK 风格按键名映射、按住键台账、`release_all` 急停兜底；PAUSE=0.01、FAILSAFE 关闭）
  - `hotkey.py`：keyboard 全局热键管理；`register_when_poe_active` 等价 AHK HotIfWinActive（回调内检查前台，不拦截系统输入）
  - `scheduler.py`：连点调度器 `SpamScheduler`（到期时间驱动、首帧随机错开、±15% 抖动、下限 50ms）
  - `timing.py`：`jitter_ms` / `clamp` 纯逻辑
  - `vision.py`：mss 截图 + OpenCV 模板匹配；`EdgeTrigger` 边沿触发；`CycloneWatcher` 后台检测线程
- **modules/**
  - `base.py`：`ToggleRunner` 热键切换式任务基类（再按停止 / preflight 检查 / 工作线程）
  - `batch_ops.py`：批量操作核心（`grid_points` 网格、`run_dump` Ctrl 存仓、`apply_currency_to_bag` Shift 货币应用；修饰键 finally 释放；驱动层可注入便于单测）
  - `bag.py`：`BagOrganizer`（F3/F4 两点标定 + 一键存仓 + `run_once` 供石碑/地图复用）
  - `waystone.py`：`WaystoneRunner`（Shift+右键选货币 → 逐格左键 → 完成后自动整理）
  - `map_runner.py`：`MapRunner`（点金×1 → 崇高×4 → 瓦尔×1 → 完成后自动整理）
  - `combat.py`：`CombatMacro`（10ms 节拍 + SpamScheduler；按住键启动按下/停止释放；失焦自动停止；旋风页挂 CycloneWatcher）
- **bridge/**
  - `bus.py`：进程内事件总线（线程安全 pub/sub，全局实例 `bus`，消息为 JSON 可序列化 dict）
  - `server.py`：可选 WebSocket 桥（FastAPI + uvicorn，默认关闭，`[Bridge] Enabled/Port`，仅 127.0.0.1，`/ws` 端点；下行广播总线消息，上行 command 路由）
- **ui/**
  - `app.py`：主窗口与控制器（状态区 + 标签页 + 功能设置区 + 日志区；启动时按需迁移 AHK 配置；热键注册：战斗 F2/整理 F1/石碑 F6/地图 F7 仅 POE2 前台生效，F3/F4 背包标定、F5 记录标定点、F12 全局急停）
  - `profile_tab.py` / `cyclone_tab.py` / `coords_tab.py` / `settings_panel.py` / `widgets.py`：配置1-4、旋风、坐标、功能设置区、共享按键行小部件

## 时间规约等价性

与 AHK 版逐项对齐：战斗宏 10ms 调度节拍 + 到期时间驱动（间隔精确不漂移）；连点抖动 ±15% 下限 50ms；批量操作抖动 ±30% 范围 5-5000ms（整理默认 30ms、石碑/地图默认 50ms）；旋风 Q/E 检测 2 秒/次边沿触发；三级货币 +70/+140px 推导；抖动公式等价 AHK `Jitter()`（`core/timing.py`）。

## 视觉检测：FindText → OpenCV

- AHK FindText 字库代码为私有格式无法移植，改为：旋风页「截图」按钮在标定点直接截取模板图保存 `templates/q.png`、`e.png`（不再需要字库代码输入框）
- 检测优先 OpenCV 模板匹配（`cv2.matchTemplate`，TM_CCOEFF_NORMED 阈值 0.9 ≈ FindText 容错 10%，标定点 ±30px 搜索），无模板时白色像素兜底（17×19 区域、容差 ±20）
- 保留 AHK 版的防护：全黑帧（截图失败）保持上次状态不误判；新增常量模板（纯黑/纯白）直接判不匹配，避免归一化相关系数误导
- 检测线程独立后台运行，日志经 bus 输出到界面日志区（替代 AHK 的 `cyclone_debug.log` 文件）

## 配置迁移

- 新配置为根目录 `poe2_tools.ini`（UTF-8）；启动时若无此文件且存在 `ahk/poe2_key_helper.ini` 则自动迁移
- AHK 旧 ini 是混合编码（UTF-8 BOM + GBK 节名「配置N」），`decode_ahk_ini` 逐行容错解码（先整体 UTF-8，失败去 BOM 后逐行 UTF-8 → GBK 回退）
- 模式字段 int（1/2/3）→ 字符串（disabled/spam/hold）；FindText 字库代码（q_text/e_text）丢弃，由「截图」按钮重新生成模板
- 迁移不删除源文件（ahk/ 目录由用户确认后统一清理）

## 新增依赖

`opencv-python`（模板匹配）、`mss`（区域截图）、`pillow`（图像处理）；pydirectinput、keyboard、fastapi 等原有依赖不变。

## 删除的旧文件

- `poe2_tools/bag.py`、`poe2_tools/combat.py`、`poe2_tools/common.py`（Python 旧版单文件实现，功能并入分层架构）
- 旧 ui 三个 tab：`poe2_tools/ui/bag_tab.py`、`combat_tab.py`、`placeholder_tab.py`（由 profile_tab/cyclone_tab/coords_tab/settings_panel/widgets 取代）

## 验证

- `uv run pytest`：101 项全部通过（配置读写、AHK 迁移含混合编码、网格计算、抖动规约、调度到期、批量操作中断、边沿触发、模板匹配防护等纯逻辑）
- 文档同步：新建 `docs/architecture.md`（分层/接口/协议/配置/时间规约）；重写 `README.md`；更新 `docs/功能说明.md`、`docs/项目框架.md`、`AGENTS.md`

## 遗留事项

- 游戏内人工验证（验证项见 `docs/功能说明.md` 待完成清单）：战斗宏连点/按住/抖动/失焦停止；F3/F4 标定 + 一键存仓落点 + 急停释放；石碑/地图速点流程 + 自动整理；旋风 Q/E 模板截图 + 数字检测触发
- 上述验证通过后物理删除 `ahk/` 目录
- 二期规划：地图词缀 OCR 识别、石碑属性识别（OpenCV/OCR 技术栈已就绪）
- 按规范「验证通过后推送 GitHub」，游戏内人工验证未做，本次不提交
