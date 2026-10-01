; ============================================================
; 战斗调度逻辑验证（测试程序，非正式脚本）
; 与 poe2_key_helper.ahk 的 CombatScheduler / StartCombat 逻辑保持一致，
; 仅把 SendInput 按键发送替换为 "时间戳 按键" 日志，用于验证间隔是否准确。
; 用法: AutoHotkey64.exe test_scheduler.ahk <用例号 1|2|3>
; ============================================================
#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent
SetWorkingDir A_ScriptDir

; ===== 以下与正式脚本一致的常量与函数 =====
JITTER_RATIO := 0.15
MIN_INTERVAL := 50
LOOP_TICK    := 10

Jitter(base, ratio) => Round(base * (1 - ratio + Random(0.0, 2 * ratio)))

; ===== 测试状态 =====
LOG_FILE  := A_ScriptDir "\scheduler_test.log"
g_Running := false
g_SpamNext := Map()
g_Profile := Map()
g_T0 := 0
g_DurMs := 25000

; 用例选择（命令行参数）
caseNum := A_Args.Length ? Integer(A_Args[1]) : 1
if (caseNum = 1) {
    ; 用例1：q=4600 / e=3280，不随机 —— 验证间隔精确性
    g_Profile := Map("q", { interval: 4600, random: 0 }, "e", { interval: 3280, random: 0 })
    g_DurMs := 25000
} else if (caseNum = 2) {
    ; 用例2：q=4600 / e=3280，随机 ±15% —— 验证抖动范围
    g_Profile := Map("q", { interval: 4600, random: 1 }, "e", { interval: 3280, random: 1 })
    g_DurMs := 30000
} else {
    ; 用例3：8 键 100ms 全随机 —— 高负载下是否有键被饿死
    for k in ["LButton", "RButton", "Space", "q", "w", "e", "r", "t"]
        g_Profile[k] := { interval: 100, random: 1 }
    g_DurMs := 15000
}

if FileExist(LOG_FILE)
    FileDelete(LOG_FILE)
FileAppend("case " caseNum " start`n", LOG_FILE)
StartTest()

StartTest() {
    global g_Running, g_SpamNext, g_T0
    g_SpamNext := Map()
    g_Running := true
    g_T0 := A_TickCount
    for key, c in g_Profile
        g_SpamNext[key] := A_TickCount + Random(0, Max(MIN_INTERVAL, c.interval))
    SetTimer(Scheduler, LOOP_TICK)
    SetTimer(EndTest, -g_DurMs)
}

; 与正式脚本 CombatScheduler 一致（仅输出替换为日志）
Scheduler() {
    global g_Running, g_SpamNext
    if !g_Running
        return
    now := A_TickCount
    for key, due in g_SpamNext {
        if (now >= due) {
            c := g_Profile[key]
            FileAppend((now - g_T0) " " key "`n", LOG_FILE)   ; 正式脚本此处为 SendInput("{Blind}{" key "}")
            interval := c.random ? Jitter(c.interval, JITTER_RATIO) : c.interval
            g_SpamNext[key] := now + Max(MIN_INTERVAL, interval)
        }
    }
}

EndTest() {
    global g_Running
    g_Running := false
    FileAppend("case end`n", LOG_FILE)
    ExitApp()
}
