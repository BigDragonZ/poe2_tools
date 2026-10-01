# 架构文档

> Python 桌面端（`poe2_tools/`）的分层架构、模块接口、前后端交互协议、配置文件与时间规约。
> 描述与代码现状一致（2026-10-01 AHK → Python 全量重构后）。

## 1. 总览

桌面端采用分层架构，自上而下：

```
┌─────────────────────────────────────────────┐
│ ui/         tkinter 界面（展示与控制）         │
├─────────────────────────────────────────────┤
│ modules/    业务模块（战斗/背包/石碑/地图）    │
├─────────────────────────────────────────────┤
│ core/       硬件级能力（窗口/输入/热键/调度/视觉）│
└─────────────────────────────────────────────┘
   config/  配置模型与 ini 读写（横向，各层只读）
   bridge/  进程内事件总线 + 可选 WebSocket（事件分发）
```

依赖方向规则：

- 上层可依赖下层：`ui` → `modules` → `core`，禁止反向依赖
- `config/` 横向共享：各层均可读取配置模型，但 `config` 不依赖任何上层
- `bridge/` 只做事件分发：`modules` 通过总线发布日志/状态，`ui` 订阅后渲染；`modules` 不直接引用 `ui`
- `main.py` 保持薄壳，仅调用 `poe2_tools.ui.app.run_app`

## 2. 各层职责与模块接口

### 2.1 config/（配置）

**`config/settings.py`** — 配置模型与 ini 读写（UTF-8，configparser）。

- 数据模型：`Point(x, y)` 客户区坐标点；`KeyConfig(mode, interval_ms, random_jitter)` 单键战斗配置；`Settings` 全部配置（热键、背包网格、石碑/地图、旋风、货币坐标、战斗配置页、桥接）
- 常量：`PROFILE_COUNT = 1`、`CYCLONE_PROFILE = 2`、`SKILL_KEYS`（8 键）、`CYC_KEYS`（鼠标三键）、`MODES = ("disabled", "spam", "hold")`、批量/抖动/旋风检测相关常量、`EMERGENCY_HOTKEY = "f12"`
- 关键函数：
  - `load_settings(path=None) -> Settings` — 从 ini 加载，字段非法时回退默认值并夹取范围
  - `save_settings(s, path=None) -> None` — 写回 ini（UTF-8）
  - `currency_coord(s, key, tier=1) -> Point | None` — 货币坐标解析，三级货币向右偏移（二级 +70px，三级 +140px）

**`config/migrate.py`** — AHK 旧配置迁移。

- `decode_ahk_ini(raw: bytes) -> str` — 混合编码（UTF-8 BOM + GBK 节名「配置N」）逐行容错解码
- `migrate_ahk_config(raw: bytes) -> Settings` — 纯逻辑迁移：模式 int（1/2/3）→ 字符串（disabled/spam/hold）；FindText 字库代码（q_text/e_text）丢弃
- `migrate_file(ahk_ini, target_ini) -> Settings | None` — 执行迁移并写盘；不删除源文件

### 2.2 core/（基础层）

**`core/window.py`** — POE2 窗口绑定与客户区坐标换算（ctypes user32，不读内存/不注入/不 Hook）。

- `is_poe_active() -> bool` / `is_poe_minimized() -> bool` / `get_foreground_window_title() -> str`
- `client_origin() -> Point | None` — 客户区左上角屏幕坐标
- `client_to_screen(p) -> Point | None` — 客户区 → 屏幕换算
- `cursor_client_pos() -> Point | None` — 当前鼠标位置（客户区坐标）

所有标定坐标一律客户区坐标（与 AHK CoordMode Client 一致），点击时换算屏幕坐标。

**`core/input.py`** — 键鼠模拟封装（pydirectinput / DirectInput 扫描码）。

- `press(key)` / `key_down(key)` / `key_up(key)` — 按键名沿用 AHK 风格（LButton/RButton/MButton/Space/q/w/...），由本层映射到驱动名
- `move_to(x, y)` / `click_at(x, y, button="LButton")` — 屏幕绝对坐标（客户区坐标请先在 `core.window` 换算）
- `held_keys() -> list[str]` — 按住键台账（线程安全）
- `release_all(extra_keys=None)` — 释放台账 + `EMERGENCY_RELEASE_KEYS`（Ctrl/Shift/Alt + 鼠标三键），急停兜底
- 模块级设置：`pydirectinput.PAUSE = 0.01`（默认 0.1s 会拖慢批量操作）、`FAILSAFE = False`（急停场景防误触发）

**`core/hotkey.py`** — 全局热键管理（keyboard 库）。

- `HotkeyManager.register(name, hotkey, callback) -> bool` — 同名重复注册先清理旧的
- `register_when_poe_active(name, hotkey, callback, is_active) -> bool` — 等价 AHK `HotIfWinActive`：回调内先检查 POE2 前台，否则忽略（不拦截系统输入）
- `unregister(name)` / `unregister_all()`
- F12 急停为全局生效，不走 `register_when_poe_active`

**`core/scheduler.py`** — 连点调度器（纯逻辑）。

- `JITTER_RATIO = 0.15`（战斗连点 ±15% 抖动）
- `SpamScheduler.start(intervals_ms, now)` — 各键首次到期 `now + rand(0, interval)`，错开首帧
- `collect_due(now) -> list[str]` — 到期按键列表
- `reschedule(key, interval_ms, random_jitter, now)` — 触发后按「当前时刻 + 抖动间隔」重排，下限 50ms，间隔精确不漂移
- `stop()` — 清空调度状态

**`core/timing.py`** — 时间规约纯逻辑。

- `jitter_ms(base_ms, ratio, rng=None) -> int` — ±ratio 随机抖动，等价 AHK `Jitter()`
- `clamp(value, lo, hi) -> int`

**`core/vision.py`** — 视觉检测（mss 截图 + OpenCV 模板匹配，FindText 的 Python 替代）。

- `capture_region(x, y, w, h) -> np.ndarray` — mss 抓屏幕小区域（BGR）
- `match_template(region, template, threshold=0.9) -> bool` — `cv2.matchTemplate`（TM_CCOEFF_NORMED），阈值 0.9 ≈ FindText 容错 10%；常量模板（纯黑/纯白）直接返回 False
- `has_bright_pixel(region, tolerance=20) -> bool` — 白色像素兜底（数字为纯白，容差 ±20）
- `load_template(path)` / `grab_template_image(center, radius=30)` — 模板加载与截取（供 UI「截图」按钮）
- `EdgeTrigger` — 边沿触发器，信号「无 → 有」只触发一次
- `CycloneWatcher(coords, templates, on_trigger, logger=None, detect_ms=2000)` — Q/E 数字检测后台线程：每 2 秒检测一次，有模板走模板匹配（标定点 ±30px 搜索），否则白色像素兜底（标定点中心 17×19 区域）；全黑帧（截图失败）保持上次状态不误判；`start()` 幂等、`stop()` 停线程

### 2.3 modules/（业务层）

**`modules/base.py`** — 热键切换式任务基类。

- `ToggleRunner`：热键入口 `toggle()`（运行中再触发 → 置停止标记；空闲 → preflight 后启动工作线程）；`request_stop()` 外部急停；子类实现 `preflight() -> Point | None` 与 `_work(origin)`；`_check_common()` 公共检查（POE2 前台 + 已标定格距 + 取鼠标位置为背包第 1 格中心）

**`modules/batch_ops.py`** — 批量操作核心（背包网格遍历点击，背包/石碑/地图共用）。

- `grid_points(origin, cell, rows, cols)` — 行优先逐格中心坐标（纯逻辑）
- `BatchDriver` — 真实驱动：客户区坐标 → 屏幕坐标 → pydirectinput（`key_down/key_up/click_client/sleep_ms`）
- `run_dump(origin, cell, rows, cols, interval_ms, should_stop, is_active, driver) -> bool` — 一键存仓核心：Ctrl 按住行优先遍历点击，`finally` 释放 Ctrl；返回是否被中断
- `apply_currency_to_bag(coord, clicks_per_cell, origin, cell, rows, cols, interval_ms, should_stop, is_active, driver) -> bool` — 货币批量应用核心：Shift 按住 → 货币坐标右键选中 → 背包每格左键 N 次，`finally` 释放 Shift
- 中断条件统一：外部停止标记 或 POE2 失焦；间隔 ±30% 抖动（`BATCH_JITTER`）

**`modules/bag.py`** — `BagOrganizer(ToggleRunner)`：F3/F4 两点标定格距（校验第 2 格在右侧同一行 ±10px，写盘）+ 一键存仓；`run_once(origin)` 供石碑/地图完成后调用一次整理。

**`modules/waystone.py`** — `WaystoneRunner(ToggleRunner)`：石碑速点。Shift+右键选货币 → 背包逐格左键 ×1 → 完成后自动触发一次背包整理（中断时不触发）。

**`modules/map_runner.py`** — `MapRunner(ToggleRunner)`：地图速点。按 `MAP_PHASES` 固定流程：点金×每格 1 次 → 崇高×每格 4 次 → 瓦尔×每格 1 次 → 完成后自动整理；`missing_currencies()` 返回未标定的流程货币（中文名）。

**`modules/combat.py`** — `CombatMacro`：战斗巡航宏。

- `LOOP_TICK = 0.01`（10ms 调度节拍）；`TEMPLATES_DIR` = 根目录 `templates/`
- `toggle()` / `start()` / `stop()`；`active` 运行状态
- 启动时按住键（hold）按下并登记，连点键（spam）进 `SpamScheduler`；调度循环每拍到期间隔精确触发，失焦自动停止并在 `finally` 释放全部按住键
- 旋风页（`active_profile == 5`）：鼠标三键走同一调度，Q/E 由 `CycloneWatcher` 后台线程数字检测、边沿触发 `core_input.press`

### 2.4 bridge/（事件分发）

**`bridge/bus.py`** — 进程内事件总线（线程安全发布/订阅）。

- `EventBus.subscribe(fn)` / `unsubscribe(fn)` / `publish(message)`（单订阅者异常不影响其他）
- 便捷发布：`log(message)` / `status(payload)` / `event(name, detail="")`
- 模块级全局实例 `bus`：单进程应用，模块与 UI 共享

**`bridge/server.py`** — 可选 WebSocket 适配器（FastAPI + uvicorn，默认关闭）。

- `BridgeServer(bus, port, on_command=None)`；`start()` 后台线程启动 uvicorn（幂等）、`stop()`
- 仅监听 `127.0.0.1`，端点 `/ws`；下行把总线消息原样广播给全部连接，上行 command 路由到注册的命令处理器

### 2.5 ui/（界面层，tkinter）

- **`ui/app.py`** — `Poe2ToolsApp(root)` 主窗口与控制器：状态区 + 标签页 + 功能设置区 + 日志区；启动时按需迁移 AHK 旧配置；注册全局热键（战斗/整理/石碑/地图仅 POE2 前台生效，F3/F4 背包标定、F5 记录标定点、F12 全局急停）；`run_app()` 主入口
- **`ui/profile_tab.py`** — `ProfileTab(notebook, index)` 战斗配置页（8 行按键）
- **`ui/cyclone_tab.py`** — `CycloneTab(master, on_calibrate, on_screenshot)` 旋风页：鼠标三键策略 + Q/E 标定/截图按钮
- **`ui/coords_tab.py`** — `CoordsTab(master, on_calibrate)` 坐标页：10 种货币标定（双列：左三级货币、右普通货币）
- **`ui/settings_panel.py`** — `SettingsPanel(master, on_save)` 右侧功能设置区：热键 + 背包/石碑/地图参数 + 保存
- **`ui/widgets.py`** — 共享小部件 `KeyRowsFrame`（策略下拉 + 间隔输入 + 抖动复选框）与显示名映射、`parse_int`/`clamp`

## 3. 前后端交互协议

两套通道：进程内事件总线（tkinter UI 使用，主通道）与可选 WebSocket 桥（外部前端预留）。消息均为 JSON 可序列化 dict。

### 3.1 进程内事件总线 `bridge.bus`

下行消息（模块 → UI）三种：

```json
{"type": "log", "message": "str —— 一行日志文本"}
```

```json
{
  "type": "status",
  "payload": {
    "foreground": true,
    "combat": "running | stopped",
    "bag": "...",
    "waystone": "...",
    "map": "..."
  }
}
```

```json
{"type": "event", "name": "calibrated | aborted | error", "detail": "str"}
```

JSON Schema（合并）：

```json
{
  "oneOf": [
    {
      "type": "object",
      "required": ["type", "message"],
      "properties": {"type": {"const": "log"}, "message": {"type": "string"}}
    },
    {
      "type": "object",
      "required": ["type", "payload"],
      "properties": {
        "type": {"const": "status"},
        "payload": {
          "type": "object",
          "required": ["foreground", "combat", "bag", "waystone", "map"],
          "properties": {
            "foreground": {"type": "boolean"},
            "combat": {"enum": ["running", "stopped"]},
            "bag": {"type": "string"},
            "waystone": {"type": "string"},
            "map": {"type": "string"}
          }
        }
      }
    },
    {
      "type": "object",
      "required": ["type", "name", "detail"],
      "properties": {
        "type": {"const": "event"},
        "name": {"enum": ["calibrated", "aborted", "error"]},
        "detail": {"type": "string"}
      }
    }
  ]
}
```

当前 tkinter UI 实际消费 `log` 消息（汇入日志区）；状态区由 UI 每 500ms 轮询模块状态刷新。`status`/`event` 为总线约定消息，供 WebSocket 外部前端使用。

### 3.2 可选 WebSocket 桥 `bridge.server`

默认关闭（`[Bridge] Enabled=0`），仅监听 `127.0.0.1`，默认端口 8322（范围 1024-65535），端点 `/ws`。

- **下行**：总线上的 log/status/event 消息原样 JSON 广播给全部连接（`ensure_ascii=False`）
- **上行命令**：

```json
{"type": "command", "action": "str —— 命令名", "params": {}}
```

JSON Schema：

```json
{
  "type": "object",
  "required": ["type", "action", "params"],
  "properties": {
    "type": {"const": "command"},
    "action": {"type": "string"},
    "params": {"type": "object"}
  }
}
```

示例：

```json
{"type": "command", "action": "stop_all", "params": {}}
```

命令由构造 `BridgeServer` 时注册的 `on_command` 处理器路由到业务层；非 JSON 或非 command 消息静默忽略，处理器异常只记日志不断连。

## 4. 配置文件说明

配置文件为根目录 `poe2_tools.ini`（UTF-8，configparser，键名大小写敏感）。文件缺失或字段非法时使用默认值；非法数值夹取到允许范围。坐标一律客户区坐标。

### [General]

| 键 | 含义 | 默认值 | 取值范围 |
|----|------|--------|----------|
| CombatHotkey | 战斗宏启停热键 | f2 | 非空字符串（keyboard 热键语法） |
| DumpHotkey | 背包整理启停热键 | f1 | 同上 |
| ActiveProfile | 当前生效配置页 | 1 | 1-2（1 = 配置，2 = 旋风） |

### [Waystone]（石碑速点）

| 键 | 含义 | 默认值 | 取值范围 |
|----|------|--------|----------|
| Hotkey | 石碑速点热键 | f6 | 非空字符串 |
| Currency | 石碑货币 | alch | 10 种货币内部键之一（见 [Currency]） |
| Tier | 货币级别 | 1 | 1-3（仅三级货币生效） |
| Interval | 每格点击间隔 ms | 50 | 5-5000（±30% 抖动） |

### [Map]（地图速点）

| 键 | 含义 | 默认值 | 取值范围 |
|----|------|--------|----------|
| Hotkey | 地图速点热键 | f7 | 非空字符串 |
| Interval | 每格点击间隔 ms | 50 | 5-5000（±30% 抖动） |

### [Bag]（背包）

| 键 | 含义 | 默认值 | 取值范围 |
|----|------|--------|----------|
| CellSize | 格子间距 px（F3/F4 标定写入） | 0（未标定） | ≥ 0 |
| Rows | 背包行数 | 5 | 1-30 |
| Cols | 背包列数 | 11 | 1-30 |
| DumpInterval | 整理每格间隔 ms | 30 | 5-5000（±30% 抖动） |

### [Cyclone]（旋风页）

鼠标三键（LButton/MButton/RButton）各一组：

| 键 | 含义 | 默认值 | 取值范围 |
|----|------|--------|----------|
| {key}_mode | 策略 | LButton = spam，其余 disabled | disabled / spam / hold |
| {key}_interval | 执行间隔 ms | LButton = 100，其余 300 | ≥ 50（±15% 抖动，可关） |
| {key}_random | 随机抖动开关 | 1 | 0 / 1 |

另有 Q/E 数字检测标定点（可选）：`q_x`/`q_y`、`e_x`/`e_y`（客户区坐标）。

### [Currency]（货币坐标）

10 种货币各一组 `{key}_x`/`{key}_y`（可选，未标定不写）：

- 三级货币（标定一级，二级 +70px、三级 +140px 向右推导）：`trans` 蜕变、`aug` 增幅、`regal` 富豪、`ex` 崇高、`chaos` 混沌
- 普通货币：`alch` 点金石、`vaal` 瓦尔、`whet` 磨刀石、`scrap` 护甲片、`etch` 奥术师

### [Profile1]（战斗配置页）

8 个按键（LButton/RButton/Space/q/w/e/r/t）各一组 `{key}_mode` / `{key}_interval` / `{key}_random`，含义与默认同 [Cyclone] 的鼠标键组。

### [Bridge]（WebSocket 桥）

| 键 | 含义 | 默认值 | 取值范围 |
|----|------|--------|----------|
| Enabled | 是否启用 WebSocket 桥 | 0 | 0 / 1（true/yes 亦为真） |
| Port | 监听端口（仅 127.0.0.1） | 8322 | 1024-65535 |

### 模式取值说明

`disabled` = 禁用、`spam` = 连点、`hold` = 按住不放。非法值回退默认。

### 与 AHK 旧 ini 的迁移关系

启动时若 `poe2_tools.ini` 不存在且存在 `ahk/poe2_key_helper.ini`，自动迁移（`config/migrate.py`）：AHK 旧 ini 为混合编码（UTF-8 BOM + GBK 节名「配置N」），逐行容错解码；模式字段 int（1/2/3）→ 字符串（disabled/spam/hold）；FindText 字库代码（`q_text`/`e_text`）为 AHK 私有格式无法移植，迁移时丢弃，由新版旋风页「截图」按钮重新生成模板图（`templates/q.png`、`e.png`）。迁移不删除源文件。

## 5. 时间规约表

| 项 | 数值 | 位置 |
|----|------|------|
| 战斗宏调度节拍 | 10ms（`LOOP_TICK = 0.01`） | modules/combat.py |
| 战斗连点抖动 | ±15%，下限 50ms | core/scheduler.py（JITTER_RATIO）、config（MIN_INTERVAL_MS） |
| 战斗连点默认间隔 | 300ms（LButton 默认连点 100ms） | config/settings.py |
| 批量操作抖动 | ±30%，范围 5-5000ms | config/settings.py（BATCH_JITTER 等） |
| 批量操作默认间隔 | 整理 30ms / 石碑 50ms / 地图 50ms | config/settings.py |
| 旋风 Q/E 检测间隔 | 2000ms（边沿触发） | config/settings.py（CYC_DETECT_MS） |
| 旋风模板搜索半径 | 标定点 ±30px | config/settings.py（CYC_TEMPLATE_RADIUS） |
| 模板匹配阈值 | 0.9（≈ FindText 容错 10%） | config/settings.py（CYC_MATCH_THRESHOLD） |
| 白色像素容差 | ±20（各通道 ≥ 235） | core/vision.py（WHITE_TOLERANCE） |
| 像素法检测区域 | 标定点中心 17×19 | config/settings.py（CYC_NUM_HW/HH） |
| 货币级别间距 | 二级 +70px、三级 +140px | config/settings.py（TIER_SPACING） |
| UI 状态轮询 | 500ms | ui/app.py（STATUS_POLL_MS） |

## 6. 安全与鲁棒性

- **F12 全局急停**：固定不可修改，全局生效（不走 POE2 前台检查）；中断全部任务（置停止标记）并 `release_all()` 释放台账 + Ctrl/Shift/Alt/鼠标三键
- **失焦自动停止**：战斗宏调度循环每拍检查 POE2 前台，失焦即停并在 `finally` 释放全部按住键；批量操作每格点击前检查失焦并中断
- **修饰键 finally 释放**：批量操作中 Ctrl/Shift 在 `finally` 中释放，任何中断路径都不残留；`key_up` 静默忽略异常
- **热键不拦截系统输入**：`register_when_poe_active` 仅在回调内检查前台，非 POE2 前台时按键行为不受影响
- **全黑帧防误判**：旋风检测区域全黑（截图失败/独占全屏 flip-model）时视为读取失败，保持上次状态，不触发也不清零；游戏需窗口化/无边框全屏
- **常量模板防误判**：纯黑/纯白模板的归一化相关系数无意义，直接判不匹配
- **合规边界**：仅输入模拟 + Win32 窗口 API，不读游戏内存、不注入、不 Hook
