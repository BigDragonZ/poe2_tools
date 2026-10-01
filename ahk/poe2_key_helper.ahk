; ============================================================
; POE2 按键助手（参考 D3KeyHelper v1.4 重构）
; 功能：战斗按键宏 + 旋风配置(数字检测触发) + 背包存仓 + 货币坐标 + 石碑/地图速点
; 运行环境：AutoHotkey v2.0+
; ============================================================
#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent

SetWorkingDir A_ScriptDir
SetTitleMatchMode 2
SendMode "Event"
CoordMode "Mouse", "Client"
CoordMode "Pixel", "Client"

#Include FindText.ahk

; ---------- 常量 ----------
POE2_TITLE    := "Path of Exile 2"
INI_FILE      := A_ScriptDir "\poe2_key_helper.ini"
PROFILE_COUNT := 4
CYCLONE_PROFILE := 5      ; 旋风配置页序号（标签页 5）
SKILL_KEYS    := ["LButton", "RButton", "Space", "q", "w", "e", "r", "t"]
SKILL_NAMES   := Map("LButton", "左键", "RButton", "右键", "Space", "空格"
                   , "q", "Q", "w", "W", "e", "E", "r", "R", "t", "T")
STRATEGIES    := ["禁用", "连点", "按住不放"]
MODE_OFF      := 1
MODE_SPAM     := 2
MODE_HOLD     := 3
JITTER_RATIO  := 0.15
MIN_INTERVAL  := 50
DEF_INTERVAL  := 300
LOOP_TICK     := 10       ; 战斗调度器节拍(ms)：到期时间驱动，间隔精确不漂移
; 旋风配置：鼠标左/中/右键 + Q/E 数字检测触发（Q/E 优先于鼠标按键）
CYC_KEYS      := ["LButton", "MButton", "RButton"]
CYC_NAMES     := Map("LButton", "左键", "MButton", "中键", "RButton", "右键")
CYC_DETECT_MS := 2000     ; Q/E 数字检测间隔（测试阶段 2 秒一次）
CYC_DEBUG_LOG := A_ScriptDir "\cyclone_debug.log"   ; 检测调试日志
CYC_NUM_HW    := 8        ; 像素法检测区域半径（以标定点为中心，17×19）
CYC_NUM_HH    := 9
CYC_FT_RADIUS := 30       ; FindText 法搜索半径（标定点 ±30px）
CYC_COLOR     := 0xFFFFFF ; 数字颜色（纯白，像素法备用）
CYC_VARIATION := 20       ; 色差容差
CYC_FT_ERR    := 0.1      ; FindText 容错率 10%
; 批量操作统一约定：间隔可配置（5-5000ms）+ ±30% 随机抖动
BATCH_JITTER       := 0.3
MIN_BATCH_INTERVAL := 5
DEF_DUMP_INTERVAL  := 30
DEF_WAY_INTERVAL   := 50
DEF_MAP_INTERVAL   := 50
; 货币坐标：蜕变/增幅/富豪/崇高/混沌分三级，二级 = 一级 +70px（向右），三级 = +140px
CURR_KEYS    := ["trans", "aug", "regal", "ex", "chaos", "alch", "vaal", "whet", "scrap", "etch"]
CURR_NAMES   := Map("trans", "蜕变", "aug", "增幅", "regal", "富豪", "ex", "崇高", "chaos", "混沌"
                  , "alch", "点金石", "vaal", "瓦尔", "whet", "磨刀石", "scrap", "护甲片", "etch", "奥术师")
TIERED_KEYS  := ["trans", "aug", "regal", "ex", "chaos"]
TIER_SPACING := 70
; 地图速点流程：[[货币, 每格点击次数], ...]，按顺序执行后触发一次背包整理
MAP_PHASES   := [["alch", 1], ["ex", 4], ["vaal", 1]]

; ---------- 全局状态 ----------
g_Profiles := []          ; 每个配置页: Map(按键 -> {mode, interval, random})
g_UI := []                ; 每个配置页的控件引用
g_Cyc := Map()            ; 旋风鼠标键配置: 按键 -> {mode, interval, random}
g_CycCoord := Map()       ; 旋风 Q/E 数字标定点: "q"/"e" -> {x, y}
g_CycText := Map("q", "", "e", "")   ; 旋风 Q/E FindText 字库代码
g_CycUI := Map()          ; 旋风页控件引用
g_CycState := Map("q", false, "e", false)  ; Q/E 上次是否检测到数字（边沿触发用）
g_CycLastCheck := 0       ; Q/E 检测节流时间戳
g_Currency := Map()       ; 货币 -> {x, y}（坐标页）
g_CurrUI := Map()         ; 货币 -> 坐标显示控件
g_Cfg := Map()            ; 通用配置（热键/背包/石碑/地图）
g_CurrentProfile := 1
g_CombatRunning := false
g_SpamNext := Map()       ; 连点按键 -> 下次到期时间(A_TickCount)
g_HeldKeys := []          ; 当前按住不放的键
g_BagRunning := false
g_BagStop := false
g_WayRunning := false
g_WayStop := false
g_MapRunning := false
g_MapStop := false
g_PendingCalib := ""      ; 等待 F5 记录的标定点（货币 key 或 cyc_q/cyc_e）
g_P1x := 0                ; 背包标定点 1（未标定为 0）
g_P1y := 0
g_HK_Combat := ""         ; 当前已注册的战斗热键
g_HK_Dump := ""           ; 当前已注册的整理热键
g_HK_Way := ""            ; 当前已注册的石碑热键
g_HK_Map := ""            ; 当前已注册的地图热键

; ============================================================
; 工具函数
; ============================================================
ToInt(v, def) {
    try {
        return Integer(v)
    } catch {
        return def
    }
}

Clamp(v, lo, hi) => Max(lo, Min(hi, v))

; 间隔 ±ratio 随机抖动，保留人工操作痕迹
Jitter(base, ratio) => Round(base * (1 - ratio + Random(0.0, 2 * ratio)))

IndexOf(arr, val) {
    for i, v in arr
        if (v = val)
            return i
    return 0
}

IsTiered(key) => IndexOf(TIERED_KEYS, key) > 0

IsCycCalib(key) => SubStr(key, 1, 4) = "cyc_"

; 标定点显示名（货币名 或 旋风 Q/E）
CalibName(key) => IsCycCalib(key) ? "旋风 " StrUpper(SubStr(key, 5)) " 数字" : CURR_NAMES[key]

; 解析货币坐标（三级货币按级别向右偏移），未标定返回 0
CurrencyCoord(key, tier := 1) {
    global g_Currency
    if !g_Currency.Has(key)
        return 0
    c := g_Currency[key]
    dx := IsTiered(key) ? (tier - 1) * TIER_SPACING : 0
    return { x: c.x + dx, y: c.y }
}

; ============================================================
; 配置读写
; ============================================================
LoadConfig() {
    global g_Cfg, g_Profiles, g_CurrentProfile, g_Currency, g_Cyc, g_CycCoord, g_CycText
    if !FileExist(INI_FILE)
        FileAppend("", INI_FILE, "UTF-8")
    g_Cfg["CombatHotkey"] := IniRead(INI_FILE, "General", "CombatHotkey", "F2")
    g_Cfg["DumpHotkey"]   := IniRead(INI_FILE, "General", "DumpHotkey", "F1")
    g_Cfg["WayHotkey"]    := IniRead(INI_FILE, "Waystone", "Hotkey", "F6")
    g_Cfg["WayCurrency"]  := IniRead(INI_FILE, "Waystone", "Currency", "alch")
    if (IndexOf(CURR_KEYS, g_Cfg["WayCurrency"]) = 0)
        g_Cfg["WayCurrency"] := "alch"
    g_Cfg["WayTier"]      := Clamp(ToInt(IniRead(INI_FILE, "Waystone", "Tier", "1"), 1), 1, 3)
    g_Cfg["WayInterval"]  := Clamp(ToInt(IniRead(INI_FILE, "Waystone", "Interval", DEF_WAY_INTERVAL), DEF_WAY_INTERVAL), MIN_BATCH_INTERVAL, 5000)
    g_Cfg["MapHotkey"]    := IniRead(INI_FILE, "Map", "Hotkey", "F7")
    g_Cfg["MapInterval"]  := Clamp(ToInt(IniRead(INI_FILE, "Map", "Interval", DEF_MAP_INTERVAL), DEF_MAP_INTERVAL), MIN_BATCH_INTERVAL, 5000)
    g_Cfg["CellSize"]     := ToInt(IniRead(INI_FILE, "Bag", "CellSize", "0"), 0)
    g_Cfg["Rows"]         := Clamp(ToInt(IniRead(INI_FILE, "Bag", "Rows", "5"), 5), 1, 30)
    g_Cfg["Cols"]         := Clamp(ToInt(IniRead(INI_FILE, "Bag", "Cols", "11"), 11), 1, 30)
    g_Cfg["DumpInterval"] := Clamp(ToInt(IniRead(INI_FILE, "Bag", "DumpInterval", DEF_DUMP_INTERVAL), DEF_DUMP_INTERVAL), MIN_BATCH_INTERVAL, 5000)
    g_CurrentProfile      := ToInt(IniRead(INI_FILE, "General", "ActiveProfile", "1"), 1)
    if (g_CurrentProfile < 1 || g_CurrentProfile > CYCLONE_PROFILE)
        g_CurrentProfile := 1
    ; 旋风配置（[Cyclone] 节：鼠标键策略 + Q/E 标定点 + FindText 字库代码）
    for key in CYC_KEYS {
        defMode := (key = "LButton") ? MODE_SPAM : MODE_OFF
        mode := ToInt(IniRead(INI_FILE, "Cyclone", key "_mode", defMode), defMode)
        if (mode < MODE_OFF || mode > MODE_HOLD)
            mode := defMode
        interval := ToInt(IniRead(INI_FILE, "Cyclone", key "_interval", 100), 100)
        rnd := ToInt(IniRead(INI_FILE, "Cyclone", key "_random", 1), 1)
        g_Cyc[key] := { mode: mode, interval: Max(MIN_INTERVAL, interval), random: rnd ? 1 : 0 }
    }
    for key in ["q", "e"] {
        x := IniRead(INI_FILE, "Cyclone", key "_x", "")
        y := IniRead(INI_FILE, "Cyclone", key "_y", "")
        if (x != "" && y != "")
            g_CycCoord[key] := { x: ToInt(x, 0), y: ToInt(y, 0) }
        g_CycText[key] := IniRead(INI_FILE, "Cyclone", key "_text", "")
    }
    ; 货币坐标（[Currency] 节，未标定的货币不入 Map）
    for key in CURR_KEYS {
        x := IniRead(INI_FILE, "Currency", key "_x", "")
        y := IniRead(INI_FILE, "Currency", key "_y", "")
        if (x != "" && y != "")
            g_Currency[key] := { x: ToInt(x, 0), y: ToInt(y, 0) }
    }
    loop PROFILE_COUNT {
        p := A_Index
        prof := Map()
        for key in SKILL_KEYS {
            defMode := (key = "LButton") ? MODE_SPAM : MODE_OFF
            defInterval := (key = "LButton") ? 100 : DEF_INTERVAL
            mode := ToInt(IniRead(INI_FILE, "配置" p, key "_mode", defMode), defMode)
            if (mode < MODE_OFF || mode > MODE_HOLD)
                mode := defMode
            interval := ToInt(IniRead(INI_FILE, "配置" p, key "_interval", defInterval), defInterval)
            rnd := ToInt(IniRead(INI_FILE, "配置" p, key "_random", 1), 1)
            prof[key] := { mode: mode, interval: Max(MIN_INTERVAL, interval), random: rnd ? 1 : 0 }
        }
        g_Profiles.Push(prof)
    }
}

SaveConfig() {
    global g_Cfg, g_Profiles, g_CurrentProfile, g_Cyc, g_CycText
    IniWrite(g_CurrentProfile, INI_FILE, "General", "ActiveProfile")
    IniWrite(g_Cfg["CombatHotkey"], INI_FILE, "General", "CombatHotkey")
    IniWrite(g_Cfg["DumpHotkey"], INI_FILE, "General", "DumpHotkey")
    IniWrite(g_Cfg["WayHotkey"], INI_FILE, "Waystone", "Hotkey")
    IniWrite(g_Cfg["WayCurrency"], INI_FILE, "Waystone", "Currency")
    IniWrite(g_Cfg["WayTier"], INI_FILE, "Waystone", "Tier")
    IniWrite(g_Cfg["WayInterval"], INI_FILE, "Waystone", "Interval")
    IniWrite(g_Cfg["MapHotkey"], INI_FILE, "Map", "Hotkey")
    IniWrite(g_Cfg["MapInterval"], INI_FILE, "Map", "Interval")
    IniWrite(g_Cfg["CellSize"], INI_FILE, "Bag", "CellSize")
    IniWrite(g_Cfg["Rows"], INI_FILE, "Bag", "Rows")
    IniWrite(g_Cfg["Cols"], INI_FILE, "Bag", "Cols")
    IniWrite(g_Cfg["DumpInterval"], INI_FILE, "Bag", "DumpInterval")
    for key in CYC_KEYS {
        c := g_Cyc[key]
        IniWrite(c.mode, INI_FILE, "Cyclone", key "_mode")
        IniWrite(c.interval, INI_FILE, "Cyclone", key "_interval")
        IniWrite(c.random, INI_FILE, "Cyclone", key "_random")
    }
    for key in ["q", "e"]
        IniWrite(g_CycText[key], INI_FILE, "Cyclone", key "_text")
    loop PROFILE_COUNT {
        p := A_Index
        prof := g_Profiles[p]
        for key in SKILL_KEYS {
            c := prof[key]
            IniWrite(c.mode, INI_FILE, "配置" p, key "_mode")
            IniWrite(c.interval, INI_FILE, "配置" p, key "_interval")
            IniWrite(c.random, INI_FILE, "配置" p, key "_random")
        }
    }
}

; ============================================================
; GUI
; ============================================================
BuildGui() {
    global g_Gui, g_Tab, g_UI, g_CycUI, g_CurrUI, g_StatusText, g_CellText
    global g_HkCombatCtrl, g_HkDumpCtrl, g_HkWayCtrl, g_HkMapCtrl
    global g_WayCurrCtrl, g_WayTierCtrl, g_WayIntervalCtrl, g_MapIntervalCtrl
    global g_BagRowsCtrl, g_BagColsCtrl, g_BagIntervalCtrl
    g_Gui := Gui("", "POE2 按键助手 v1.5")
    g_Gui.SetFont("s9", "Microsoft YaHei")
    g_Gui.MarginX := 10
    g_Gui.MarginY := 10

    tabNames := []
    loop PROFILE_COUNT
        tabNames.Push("配置" A_Index)
    tabNames.Push("旋风")
    tabNames.Push("坐标")
    g_Tab := g_Gui.Add("Tab3", "x10 y10 w560 h330 Choose" g_CurrentProfile, tabNames)

    ; ---- 战斗配置页（配置1-4）----
    loop PROFILE_COUNT {
        p := A_Index
        g_Tab.UseTab(p)
        g_Gui.Add("Text", "x30 y44 w70", "按键")
        g_Gui.Add("Text", "x110 y44 w90", "策略")
        g_Gui.Add("Text", "x216 y44 w100", "执行间隔(毫秒)")
        g_Gui.Add("Text", "x320 y44 w120", "随机抖动(±15%)")
        ctrls := Map()
        y := 66
        for key in SKILL_KEYS {
            prof := g_Profiles[p][key]
            g_Gui.Add("Text", "x30 y" (y + 3) " w70", SKILL_NAMES[key])
            ddl := g_Gui.Add("DropDownList", "x106 y" y " w90 Choose" prof.mode, STRATEGIES)
            edt := g_Gui.Add("Edit", "x216 y" y " w70 Number Limit5", prof.interval)
            chk := g_Gui.Add("CheckBox", "x320 y" (y + 2), "随机")
            chk.Value := prof.random
            ctrls[key] := { mode: ddl, interval: edt, random: chk }
            y += 26
        }
        g_UI.Push(ctrls)
    }

    ; ---- 旋风页（左/中/右键 + Q/E 数字检测触发）----
    g_Tab.UseTab(CYCLONE_PROFILE)
    g_Gui.Add("Text", "x30 y44 w70", "按键")
    g_Gui.Add("Text", "x110 y44 w90", "策略")
    g_Gui.Add("Text", "x216 y44 w100", "执行间隔(毫秒)")
    g_Gui.Add("Text", "x320 y44 w120", "随机抖动(±15%)")
    cycCtrls := Map()
    y := 66
    for key in CYC_KEYS {
        c := g_Cyc[key]
        g_Gui.Add("Text", "x30 y" (y + 3) " w70", CYC_NAMES[key])
        ddl := g_Gui.Add("DropDownList", "x106 y" y " w90 Choose" c.mode, STRATEGIES)
        edt := g_Gui.Add("Edit", "x216 y" y " w70 Number Limit5", c.interval)
        chk := g_Gui.Add("CheckBox", "x320 y" (y + 2), "随机")
        chk.Value := c.random
        cycCtrls[key] := { mode: ddl, interval: edt, random: chk }
        y += 26
    }
    g_Gui.Add("Text", "x30 y150 w530", "Q / E 技能：图标左上角出现数字时自动按一下（优先级高于鼠标按键）")
    y := 178
    for key in ["q", "e"] {
        g_Gui.Add("Text", "x30 y" (y + 2) " w85", StrUpper(key) " 数字坐标:")
        txt := g_Gui.Add("Text", "x115 y" (y + 2) " w85", CycCoordText(key))
        btn := g_Gui.Add("Button", "x206 y" (y - 2) " w52 h21", "标定")
        btn.OnEvent("Click", StartCalib.Bind("cyc_" key))
        btn2 := g_Gui.Add("Button", "x264 y" (y - 2) " w52 h21", "截图")
        btn2.OnEvent("Click", StartCapture.Bind(key))
        edt := g_Gui.Add("Edit", "x322 y" (y - 2) " w228 h21", g_CycText[key])
        edt.ToolTip := "FindText 字库代码（截图生成后粘贴到这里）"
        g_CycUI[key] := txt
        g_CycUI[key "_text"] := edt
        y += 26
    }
    g_CycUI["mouse"] := cycCtrls
    g_Gui.Add("Text", "x30 y240 w530 h70"
        , "① 标定: 点「标定」→ 游戏内鼠标指向技能图标上的数字按 F5（确定搜索范围中心）`n② 截图: 点「截图」打开 FindText 工具 → 截取数字图像 → 生成字库代码点 Copy → 粘贴到输入框`n③ 检测: 有字库代码用 FindText 图像匹配，否则用白色像素检测；2 秒一次、边沿触发只按一下`n调试日志: ahk\cyclone_debug.log（启动战斗时重置）")
    g_Tab.UseTab()

    ; ---- 坐标页（货币坐标读取/标定/展示，双列：左三级货币、右普通货币）----
    g_Tab.UseTab(CYCLONE_PROFILE + 1)
    g_Gui.Add("Text", "x30 y44 w70", "货币(三级)")
    g_Gui.Add("Text", "x105 y44 w100", "一级坐标")
    g_Gui.Add("Text", "x300 y44 w70", "货币")
    g_Gui.Add("Text", "x375 y44 w100", "坐标")
    y := 66
    for i, key in CURR_KEYS {
        if IsTiered(key) {
            g_Gui.Add("Text", "x30 y" (y + 2) " w70", CURR_NAMES[key])
            txt := g_Gui.Add("Text", "x105 y" (y + 2) " w100", CoordText(key))
            btn := g_Gui.Add("Button", "x210 y" (y - 2) " w56 h21", "标定")
            y += 26
        } else {
            ry := 66 + (i - 6) * 26
            g_Gui.Add("Text", "x300 y" (ry + 2) " w70", CURR_NAMES[key])
            txt := g_Gui.Add("Text", "x375 y" (ry + 2) " w100", CoordText(key))
            btn := g_Gui.Add("Button", "x480 y" (ry - 2) " w56 h21", "标定")
        }
        btn.OnEvent("Click", StartCalib.Bind(key))
        g_CurrUI[key] := txt
    }
    g_Gui.Add("Text", "x30 y210 w530 h60"
        , "标定方法: 点「标定」后切到游戏窗口，鼠标指向该货币按 F5 记录(再点一次「标定」取消)`n三级货币(蜕变/增幅/富豪/崇高/混沌)只需标定一级，二级 = 一级+70px、三级 = +140px(向右)`n坐标供石碑速点/地图速点使用")
    g_Tab.UseTab()

    ; ---- 右侧功能区 ----
    g_Gui.Add("GroupBox", "x580 y10 w240 h330", "功能设置")
    g_Gui.Add("Text", "x596 y34 w95", "战斗宏热键:")
    g_Gui.Add("Text", "x700 y34 w95", "整理热键:")
    g_HkCombatCtrl := g_Gui.Add("Hotkey", "x596 y52 w95", g_Cfg["CombatHotkey"])
    g_HkDumpCtrl := g_Gui.Add("Hotkey", "x700 y52 w95", g_Cfg["DumpHotkey"])
    g_Gui.Add("Text", "x596 y80 w95", "石碑速点热键:")
    g_Gui.Add("Text", "x700 y80 w95", "地图速点热键:")
    g_HkWayCtrl := g_Gui.Add("Hotkey", "x596 y98 w95", g_Cfg["WayHotkey"])
    g_HkMapCtrl := g_Gui.Add("Hotkey", "x700 y98 w95", g_Cfg["MapHotkey"])
    g_Gui.Add("Text", "x596 y126", "行数 / 列数 / 整理间隔(ms):")
    g_BagRowsCtrl := g_Gui.Add("Edit", "x596 y144 w60 Number Limit2", g_Cfg["Rows"])
    g_BagColsCtrl := g_Gui.Add("Edit", "x664 y144 w60 Number Limit2", g_Cfg["Cols"])
    g_BagIntervalCtrl := g_Gui.Add("Edit", "x732 y144 w60 Number Limit4", g_Cfg["DumpInterval"])
    g_Gui.Add("Text", "x596 y172", "石碑货币 / 级别:")
    currNames := []
    for key in CURR_KEYS
        currNames.Push(CURR_NAMES[key])
    g_WayCurrCtrl := g_Gui.Add("DropDownList", "x596 y190 w116 Choose" IndexOf(CURR_KEYS, g_Cfg["WayCurrency"]), currNames)
    g_WayTierCtrl := g_Gui.Add("DropDownList", "x718 y190 w76 Choose" g_Cfg["WayTier"], ["一级", "二级", "三级"])
    g_Gui.Add("Text", "x596 y218", "石碑间隔 / 地图间隔(ms):")
    g_WayIntervalCtrl := g_Gui.Add("Edit", "x596 y236 w60 Number Limit4", g_Cfg["WayInterval"])
    g_MapIntervalCtrl := g_Gui.Add("Edit", "x664 y236 w60 Number Limit4", g_Cfg["MapInterval"])
    g_CellText := g_Gui.Add("Text", "x596 y264 w210"
        , "格子间距: " (g_Cfg["CellSize"] > 0 ? g_Cfg["CellSize"] " px" : "未标定"))
    g_Gui.Add("Text", "x596 y286 w210", "F3/F4 标定背包格距 · F12 全局急停")
    btnSave := g_Gui.Add("Button", "x580 y348 w240 h32", "保存配置")
    btnSave.OnEvent("Click", (*) => SaveFromGui(false))

    g_StatusText := g_Gui.Add("Text", "x10 y352 w560 h22", "")
    g_Tab.OnEvent("Change", OnTabChange)
    g_Gui.OnEvent("Close", OnGuiClose)
    SetTimer(UpdateStatus, 500)
    UpdateStatus()
    g_Gui.Show("w830 h392")
}

; 把配置页 p 的界面值读回内存
SyncProfileFromUI(p) {
    global g_UI, g_Profiles
    if (p < 1 || p > g_UI.Length)
        return
    ctrls := g_UI[p]
    prof := g_Profiles[p]
    for key in SKILL_KEYS {
        c := ctrls[key]
        prof[key] := { mode: c.mode.Value
                     , interval: Max(MIN_INTERVAL, ToInt(c.interval.Value, DEF_INTERVAL))
                     , random: c.random.Value ? 1 : 0 }
    }
}

; 把旋风页界面值读回内存
SyncCycloneFromUI() {
    global g_CycUI, g_Cyc, g_CycText
    ctrls := g_CycUI["mouse"]
    for key in CYC_KEYS {
        c := ctrls[key]
        g_Cyc[key] := { mode: c.mode.Value
                      , interval: Max(MIN_INTERVAL, ToInt(c.interval.Value, 100))
                      , random: c.random.Value ? 1 : 0 }
    }
    for key in ["q", "e"]
        g_CycText[key] := Trim(g_CycUI[key "_text"].Value)
}

OnTabChange(ctrl, *) {
    global g_CurrentProfile
    if (g_CurrentProfile <= PROFILE_COUNT)
        SyncProfileFromUI(g_CurrentProfile)
    else if (g_CurrentProfile = CYCLONE_PROFILE)
        SyncCycloneFromUI()
    if (ctrl.Value <= CYCLONE_PROFILE)
        g_CurrentProfile := ctrl.Value
}

SaveFromGui(quiet) {
    global g_Cfg, g_CurrentProfile
    SyncProfileFromUI(g_CurrentProfile)
    SyncCycloneFromUI()
    if (g_HkCombatCtrl.Value != "")
        g_Cfg["CombatHotkey"] := g_HkCombatCtrl.Value
    if (g_HkDumpCtrl.Value != "")
        g_Cfg["DumpHotkey"] := g_HkDumpCtrl.Value
    if (g_HkWayCtrl.Value != "")
        g_Cfg["WayHotkey"] := g_HkWayCtrl.Value
    if (g_HkMapCtrl.Value != "")
        g_Cfg["MapHotkey"] := g_HkMapCtrl.Value
    ci := g_WayCurrCtrl.Value
    if (ci >= 1 && ci <= CURR_KEYS.Length)
        g_Cfg["WayCurrency"] := CURR_KEYS[ci]
    g_Cfg["WayTier"] := g_WayTierCtrl.Value
    g_Cfg["WayInterval"] := Clamp(ToInt(g_WayIntervalCtrl.Value, g_Cfg["WayInterval"]), MIN_BATCH_INTERVAL, 5000)
    g_Cfg["MapInterval"] := Clamp(ToInt(g_MapIntervalCtrl.Value, g_Cfg["MapInterval"]), MIN_BATCH_INTERVAL, 5000)
    g_Cfg["Rows"] := Clamp(ToInt(g_BagRowsCtrl.Value, g_Cfg["Rows"]), 1, 30)
    g_Cfg["Cols"] := Clamp(ToInt(g_BagColsCtrl.Value, g_Cfg["Cols"]), 1, 30)
    g_Cfg["DumpInterval"] := Clamp(ToInt(g_BagIntervalCtrl.Value, g_Cfg["DumpInterval"]), MIN_BATCH_INTERVAL, 5000)
    SaveConfig()
    RegisterHotkeys()
    if !quiet
        ShowTip("配置已保存")
}

OnGuiClose(*) {
    SaveFromGui(true)
    ExitApp()
}

UpdateCellText() {
    global g_CellText, g_Cfg
    g_CellText.Value := "格子间距: " (g_Cfg["CellSize"] > 0 ? g_Cfg["CellSize"] " px" : "未标定")
}

CoordText(key) {
    global g_Currency
    if !g_Currency.Has(key)
        return "未标定"
    c := g_Currency[key]
    return c.x ", " c.y
}

CycCoordText(key) {
    global g_CycCoord
    if !g_CycCoord.Has(key)
        return "未标定"
    c := g_CycCoord[key]
    return c.x ", " c.y
}

UpdateCurrencyUI() {
    global g_CurrUI
    for key, ctrl in g_CurrUI
        ctrl.Value := CoordText(key)
}

UpdateCycloneUI() {
    global g_CycUI
    for key in ["q", "e"]
        g_CycUI[key].Value := CycCoordText(key)
}

ProfileName() {
    global g_CurrentProfile
    return g_CurrentProfile = CYCLONE_PROFILE ? "旋风" : "配置" g_CurrentProfile
}

UpdateStatus() {
    global g_StatusText
    fg := WinActive(POE2_TITLE) ? "是" : "否"
    combat := g_CombatRunning ? "运行" : "停止"
    bag := g_BagRunning ? "整理中" : "空闲"
    way := g_WayRunning ? "速点中" : "空闲"
    map := g_MapRunning ? "速点中" : "空闲"
    g_StatusText.Value := "前台: " fg " | 战斗: " combat " | 整理: " bag " | 石碑: " way
        . " | 地图: " map " | " ProfileName()
}

ShowTip(text, ms := 2000) {
    ToolTip(text)
    SetTimer(() => ToolTip(), -ms)
}

; ============================================================
; 热键注册（战斗/整理/石碑/地图/标定仅在 POE2 窗口激活时生效，F12 全局）
; ============================================================
RegisterHotkeys() {
    global g_HK_Combat, g_HK_Dump, g_HK_Way, g_HK_Map, g_Cfg
    HotIfWinActive(POE2_TITLE)
    if (g_HK_Combat != "")
        try Hotkey(g_HK_Combat, "Off")
    if (g_HK_Dump != "")
        try Hotkey(g_HK_Dump, "Off")
    if (g_HK_Way != "")
        try Hotkey(g_HK_Way, "Off")
    if (g_HK_Map != "")
        try Hotkey(g_HK_Map, "Off")
    g_HK_Combat := g_Cfg["CombatHotkey"]
    g_HK_Dump := g_Cfg["DumpHotkey"]
    g_HK_Way := g_Cfg["WayHotkey"]
    g_HK_Map := g_Cfg["MapHotkey"]
    try Hotkey(g_HK_Combat, ToggleCombat, "On")
    try Hotkey(g_HK_Dump, ToggleDump, "On")
    try Hotkey(g_HK_Way, ToggleWaystone, "On")
    try Hotkey(g_HK_Map, ToggleMap, "On")
    try Hotkey("F3", CalibPoint1, "On")
    try Hotkey("F4", CalibPoint2, "On")
    HotIf()
    try Hotkey("F12", EmergencyStop, "On")
}

; ============================================================
; 战斗宏：10ms 单调度器 + 到期时间驱动（间隔精确、无多定时器抢占）
; 发送用 SendInput（Event 模式每次按键有系统级延迟，会导致间隔漂移）
; ============================================================
ToggleCombat(*) {
    if g_CombatRunning
        StopCombat(true)
    else
        StartCombat()
}

StartCombat() {
    global g_CombatRunning, g_SpamNext, g_HeldKeys, g_CycState, g_CycLastCheck
    if !WinActive(POE2_TITLE) {
        ShowTip("POE2 窗口未激活，无法启动战斗宏")
        return
    }
    if (g_CurrentProfile = CYCLONE_PROFILE)
        SyncCycloneFromUI()
    else
        SyncProfileFromUI(g_CurrentProfile)
    g_SpamNext := Map()
    g_HeldKeys := []
    g_CombatRunning := true
    ; 旋风页用鼠标三键配置，其余页用 8 键配置
    keys := g_CurrentProfile = CYCLONE_PROFILE ? CYC_KEYS : SKILL_KEYS
    cfg := g_CurrentProfile = CYCLONE_PROFILE ? g_Cyc : g_Profiles[g_CurrentProfile]
    for key in keys {
        c := cfg[key]
        if (c.mode = MODE_HOLD) {
            SendInput("{Blind}{" key " down}")
            g_HeldKeys.Push(key)
        } else if (c.mode = MODE_SPAM) {
            ; 首次触发时间随机错开，避免多键同帧
            g_SpamNext[key] := A_TickCount + Random(0, Max(MIN_INTERVAL, c.interval))
        }
    }
    g_CycState := Map("q", false, "e", false)
    g_CycLastCheck := 0
    ; 测试阶段：旋风页启动时重置检测调试日志
    if (g_CurrentProfile = CYCLONE_PROFILE) {
        try {
            if FileExist(CYC_DEBUG_LOG)
                FileDelete(CYC_DEBUG_LOG)
            FileAppend("=== 旋风检测日志 " A_Now " ===`n", CYC_DEBUG_LOG, "UTF-8")
        }
    }
    SetTimer(CombatScheduler, LOOP_TICK)
    SetTimer(CombatWatchdog, 200)
    ShowTip("战斗宏已启动 (" ProfileName() ")")
}

; 旋风：Q/E 数字检测（2 秒一次，边沿触发只按一次，全程写调试日志）
; 优先 FindText 图像匹配（已截图字库代码时），否则白色像素兜底
CycloneDetect() {
    global g_CycCoord, g_CycState, g_CycLastCheck, g_CycText
    if (A_TickCount - g_CycLastCheck < CYC_DETECT_MS)
        return
    g_CycLastCheck := A_TickCount
    for key in ["q", "e"] {
        if !g_CycCoord.Has(key)
            continue
        c := g_CycCoord[key]
        found := 0
        how := ""
        err := ""
        if (g_CycText[key] != "") {
            ; FindText 图像匹配：标定点 ±30px 搜索（坐标转屏幕坐标系）
            how := "FindText"
            try {
                WinGetClientPos(&wx, &wy, &ww, &wh, POE2_TITLE)
                ok := FindText(&fx, &fy, wx + c.x - CYC_FT_RADIUS, wy + c.y - CYC_FT_RADIUS
                             , wx + c.x + CYC_FT_RADIUS, wy + c.y + CYC_FT_RADIUS
                             , CYC_FT_ERR, CYC_FT_ERR, g_CycText[key])
                found := (IsObject(ok) && ok.Length > 0) ? 1 : 0
            } catch as e {
                err := " FindText异常:" e.Message
            }
        } else {
            ; 白色像素兜底：标定点为中心 17×19 区域找纯白(±20)
            how := "像素"
            x1 := c.x - CYC_NUM_HW, y1 := c.y - CYC_NUM_HH
            x2 := c.x + CYC_NUM_HW, y2 := c.y + CYC_NUM_HH
            try {
                found := PixelSearch(&fx, &fy, x1, y1, x2, y2, CYC_COLOR, CYC_VARIATION)
            } catch as e {
                err := " PixelSearch异常:" e.Message
            }
        }
        centerColor := ""
        try centerColor := PixelGetColor(c.x, c.y)
        ; 全黑 = 取色黑帧，视为读取失败：保持上次状态，不误判（仅像素法需要）
        if (how = "像素" && !found && (centerColor = "" || centerColor = "0x000000")) {
            try FileAppend(A_TickCount " " StrUpper(key) " [像素] 读取失败(全黑黑帧)，保持上次状态=" (g_CycState[key] ? "有" : "无") err "`n", CYC_DEBUG_LOG, "UTF-8")
            continue
        }
        pressed := (found && !g_CycState[key])
        try FileAppend(A_TickCount " " StrUpper(key) " [" how "] 中心色=" centerColor
            . " 检测=" (found ? "有" : "无") " 上次=" (g_CycState[key] ? "有" : "无") (pressed ? " → 按键" : "") err "`n", CYC_DEBUG_LOG, "UTF-8")
        if pressed
            SendInput("{Blind}{" key "}")
        g_CycState[key] := found ? true : false
    }
}

; 每 10ms 检查一次各连点键是否到期，到期即发并按当前时刻重排下次
CombatScheduler() {
    global g_CombatRunning, g_SpamNext
    if !g_CombatRunning
        return
    if !WinActive(POE2_TITLE) {
        StopCombat()
        ShowTip("窗口失焦，战斗宏已停止")
        return
    }
    now := A_TickCount
    ; Q/E 数字检测优先于鼠标按键
    if (g_CurrentProfile = CYCLONE_PROFILE)
        CycloneDetect()
    cfg := g_CurrentProfile = CYCLONE_PROFILE ? g_Cyc : g_Profiles[g_CurrentProfile]
    for key, due in g_SpamNext {
        if (now >= due) {
            c := cfg[key]
            SendInput("{Blind}{" key "}")
            interval := c.random ? Jitter(c.interval, JITTER_RATIO) : c.interval
            g_SpamNext[key] := now + Max(MIN_INTERVAL, interval)
        }
    }
}

StopCombat(showMsg := false) {
    global g_CombatRunning, g_SpamNext, g_HeldKeys
    if !g_CombatRunning
        return
    g_CombatRunning := false
    SetTimer(CombatScheduler, 0)
    g_SpamNext := Map()
    for key in g_HeldKeys
        SendInput("{Blind}{" key " up}")
    g_HeldKeys := []
    SetTimer(CombatWatchdog, 0)
    if showMsg
        ShowTip("战斗宏已停止")
}

; 失焦自动停止兜底（调度器内已检查，此处双保险）
CombatWatchdog() {
    if (g_CombatRunning && !WinActive(POE2_TITLE)) {
        StopCombat()
        ShowTip("窗口失焦，战斗宏已停止")
    }
}

; ============================================================
; 通用批量操作（统一约定：间隔可配置 + ±30% 随机抖动）
; ============================================================
; 背包一键存仓核心：Ctrl 按住，以 (ox,oy) 为第 1 格中心行优先遍历点击；返回是否被中断
RunDump(ox, oy) {
    global g_Cfg, g_BagStop
    cell := g_Cfg["CellSize"]
    rows := g_Cfg["Rows"]
    cols := g_Cfg["Cols"]
    SendEvent("{Blind}{Ctrl down}")
    aborted := false
    try {
        loop rows {
            if aborted
                break
            row := A_Index - 1
            loop cols {
                col := A_Index - 1
                if (g_BagStop || !WinActive(POE2_TITLE)) {
                    aborted := true
                    break
                }
                x := Round(ox + col * cell)
                y := Round(oy + row * cell)
                ; 快速整理：瞬间移动 + Input 模式点击（Event 模式每次点击开销大）
                MouseMove(x, y, 0)
                SendInput("{Blind}{Click}")
                Sleep(Jitter(g_Cfg["DumpInterval"], BATCH_JITTER))
            }
        }
    } finally {
        SendEvent("{Blind}{Ctrl up}")
    }
    return aborted
}

; 货币批量应用核心：Shift 按住 → 货币坐标右键选中 → 背包每格左键 clicksPerCell 次；返回是否被中断
ApplyCurrencyToBag(coord, clicksPerCell, ox, oy, interval, stopFn) {
    global g_Cfg
    cell := g_Cfg["CellSize"]
    rows := g_Cfg["Rows"]
    cols := g_Cfg["Cols"]
    SendEvent("{Blind}{Shift down}")
    aborted := false
    try {
        MouseMove(coord.x, coord.y, 0)
        SendInput("{Blind}{RButton}")
        Sleep(Jitter(interval, BATCH_JITTER))
        loop rows {
            if aborted
                break
            row := A_Index - 1
            loop cols {
                col := A_Index - 1
                if (stopFn.Call() || !WinActive(POE2_TITLE)) {
                    aborted := true
                    break
                }
                MouseMove(Round(ox + col * cell), Round(oy + row * cell), 0)
                loop clicksPerCell {
                    SendInput("{Blind}{Click}")
                    Sleep(Jitter(interval, BATCH_JITTER))
                }
            }
        }
    } finally {
        SendEvent("{Blind}{Shift up}")
    }
    return aborted
}

; ============================================================
; 背包一键存仓
; ============================================================
ToggleDump(*) {
    global g_BagRunning, g_BagStop
    if g_BagRunning {
        g_BagStop := true
        ShowTip("正在停止背包整理...")
        return
    }
    if !WinActive(POE2_TITLE)
        return
    if (g_Cfg["CellSize"] <= 0) {
        ShowTip("请先标定：F3 指向第 1 格中心，F4 指向右侧相邻格中心")
        return
    }
    g_BagRunning := true
    g_BagStop := false
    SetTimer(DumpWorker, -1)
    ShowTip("背包整理中，再按一次整理热键停止")
}

DumpWorker() {
    global g_BagRunning, g_BagStop
    MouseGetPos(&ox, &oy)   ; 触发时鼠标位置 = 第 1 格中心
    aborted := RunDump(ox, oy)
    g_BagRunning := false
    g_BagStop := false
    ShowTip(aborted ? "背包整理已中断" : "背包整理完成")
}

; ============================================================
; 石碑速点：Shift 按住 → 右键选中货币 → 背包逐格左键 → 触发一次背包整理
; 触发时鼠标位置 = 背包第 1 格中心（复用背包网格配置）
; ============================================================
ToggleWaystone(*) {
    global g_WayRunning, g_WayStop
    if g_WayRunning {
        g_WayStop := true
        ShowTip("正在停止石碑速点...")
        return
    }
    if !WinActive(POE2_TITLE)
        return
    if !CurrencyCoord(g_Cfg["WayCurrency"], g_Cfg["WayTier"]) {
        ShowTip("请先在「坐标」页标定「" CURR_NAMES[g_Cfg["WayCurrency"]] "」")
        return
    }
    if (g_Cfg["CellSize"] <= 0) {
        ShowTip("请先用 F3/F4 标定背包格子间距")
        return
    }
    g_WayRunning := true
    g_WayStop := false
    SetTimer(WaystoneWorker, -1)
    ShowTip("石碑速点中，再按一次停止")
}

WaystoneWorker() {
    global g_WayRunning, g_WayStop
    coord := CurrencyCoord(g_Cfg["WayCurrency"], g_Cfg["WayTier"])
    MouseGetPos(&ox, &oy)   ; 触发时鼠标位置 = 背包第 1 格中心
    aborted := ApplyCurrencyToBag(coord, 1, ox, oy, g_Cfg["WayInterval"], () => g_WayStop)
    dumped := false
    if !aborted {
        RunDump(ox, oy)     ; 完成后触发一次背包整理
        dumped := true
    }
    g_WayRunning := false
    g_WayStop := false
    ShowTip(aborted ? "石碑速点已中断" : "石碑速点完成" (dumped ? "，背包整理已触发" : ""))
}

; ============================================================
; 地图速点：点金×1 → 崇高×4 → 瓦尔×1 → 触发一次背包整理
; 触发时鼠标位置 = 背包第 1 格中心（复用背包网格配置）
; ============================================================
ToggleMap(*) {
    global g_MapRunning, g_MapStop
    if g_MapRunning {
        g_MapStop := true
        ShowTip("正在停止地图速点...")
        return
    }
    if !WinActive(POE2_TITLE)
        return
    for phase in MAP_PHASES {
        if !CurrencyCoord(phase[1]) {
            ShowTip("请先在「坐标」页标定「" CURR_NAMES[phase[1]] "」")
            return
        }
    }
    if (g_Cfg["CellSize"] <= 0) {
        ShowTip("请先用 F3/F4 标定背包格子间距")
        return
    }
    g_MapRunning := true
    g_MapStop := false
    SetTimer(MapWorker, -1)
    ShowTip("地图速点中（点金→崇高→瓦尔→整理），再按一次停止")
}

MapWorker() {
    global g_MapRunning, g_MapStop
    MouseGetPos(&ox, &oy)   ; 触发时鼠标位置 = 背包第 1 格中心
    aborted := false
    for phase in MAP_PHASES {
        coord := CurrencyCoord(phase[1])
        if ApplyCurrencyToBag(coord, phase[2], ox, oy, g_Cfg["MapInterval"], () => g_MapStop) {
            aborted := true
            break
        }
    }
    dumped := false
    if !aborted {
        RunDump(ox, oy)     ; 完成后触发一次背包整理
        dumped := true
    }
    g_MapRunning := false
    g_MapStop := false
    ShowTip(aborted ? "地图速点已中断" : "地图速点完成" (dumped ? "，背包整理已触发" : ""))
}

; ============================================================
; 背包网格标定：F3 记录第 1 格中心，F4 记录右侧相邻格中心（仅保存水平间距）
; ============================================================
CalibPoint1(*) {
    global g_P1x, g_P1y
    MouseGetPos(&g_P1x, &g_P1y)
    ShowTip("已记录第 1 格中心 (" g_P1x ", " g_P1y ")，再按 F4 标定右侧相邻格")
}

CalibPoint2(*) {
    global g_P1x, g_P1y, g_Cfg
    if (g_P1x = 0) {
        ShowTip("请先按 F3 标定第 1 格")
        return
    }
    MouseGetPos(&x2, &y2)
    if (x2 <= g_P1x || Abs(y2 - g_P1y) > 10) {
        ShowTip("标定失败：第 2 格必须在第 1 格右侧同一行")
        return
    }
    cell := x2 - g_P1x
    g_Cfg["CellSize"] := cell
    IniWrite(cell, INI_FILE, "Bag", "CellSize")
    UpdateCellText()
    ShowTip("标定成功，格子间距: " cell " px")
}

; ============================================================
; 标定（货币坐标 / 旋风 QE 数字位置）：点「标定」→ 游戏内按 F5 记录
; ============================================================
StartCalib(key, *) {
    global g_PendingCalib
    if (g_PendingCalib = key) {
        ; 再点一次取消
        g_PendingCalib := ""
        HotIfWinActive(POE2_TITLE)
        try Hotkey("F5", "Off")
        HotIf()
        ShowTip("已取消「" CalibName(key) "」标定")
        return
    }
    g_PendingCalib := key
    HotIfWinActive(POE2_TITLE)
    try Hotkey("F5", RecordCalib, "On")
    HotIf()
    ShowTip("请在游戏窗口内把鼠标指向「" CalibName(key) "」按 F5 记录坐标", 4000)
}

RecordCalib(*) {
    global g_PendingCalib, g_Currency, g_CycCoord
    if (g_PendingCalib = "")
        return
    key := g_PendingCalib
    g_PendingCalib := ""
    HotIfWinActive(POE2_TITLE)
    try Hotkey("F5", "Off")
    HotIf()
    MouseGetPos(&x, &y)
    if IsCycCalib(key) {
        k := SubStr(key, 5)
        g_CycCoord[k] := { x: x, y: y }
        IniWrite(x, INI_FILE, "Cyclone", k "_x")
        IniWrite(y, INI_FILE, "Cyclone", k "_y")
        UpdateCycloneUI()
    } else {
        g_Currency[key] := { x: x, y: y }
        IniWrite(x, INI_FILE, "Currency", key "_x")
        IniWrite(y, INI_FILE, "Currency", key "_y")
        UpdateCurrencyUI()
    }
    ShowTip("已记录「" CalibName(key) "」坐标: " x ", " y)
}

; ============================================================
; 旋风 Q/E 截图：打开 FindText 工具，用户截取数字生成字库代码后粘贴到输入框
; ============================================================
StartCapture(key, *) {
    FindText().Gui("Show")
    ShowTip("在 FindText 窗口截取「" StrUpper(key) "」的数字图像 → 生成字库代码 → Copy → 粘贴到旋风页输入框", 5000)
}

; ============================================================
; 紧急停止（全局 F12）：停止宏/整理/速点，释放所有可能按住的键
; ============================================================
EmergencyStop(*) {
    global g_BagStop, g_WayStop, g_MapStop
    StopCombat()
    g_BagStop := true
    g_WayStop := true
    g_MapStop := true
    for k in ["Ctrl", "Shift", "Alt", "LButton", "RButton", "MButton"]
        SendEvent("{Blind}{" k " up}")
    ShowTip("已紧急停止并释放所有按键")
}

OnAppExit(*) {
    StopCombat()
    for k in ["Ctrl", "Shift", "Alt", "LButton", "RButton", "MButton"]
        SendEvent("{Blind}{" k " up}")
}

; ============================================================
; 启动
; ============================================================
LoadConfig()
BuildGui()
RegisterHotkeys()
OnExit(OnAppExit)
