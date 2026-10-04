#!/usr/bin/env bash
# 应用管理脚本：快速 启动 / 关闭 / 重启 / 查看状态
# 用法（Git Bash 或 PowerShell 中均可）：
#   bash scripts/app.sh start   [web|desktop|all]   # 启动（默认 all）
#   bash scripts/app.sh stop    [web|desktop|all]   # 关闭
#   bash scripts/app.sh restart [web|desktop|all]   # 重启
#   bash scripts/app.sh status  [web|desktop|all]   # 查看状态
#
# web     = 经济记录 Web 应用（uv run python -m web.app，端口 8321）
# desktop = Python 桌面端主界面（uv run python main.py，tkinter）
# 日志输出到 logs/web.log、logs/desktop.log

set -u
cd "$(dirname "$0")/.."

WEB_PORT=8321
WEB_LOG="logs/web.log"
DESKTOP_LOG="logs/desktop.log"

mkdir -p logs

# 查询监听 WEB_PORT 的进程 PID（空表示未运行）
web_pid() {
    netstat -ano | grep LISTENING | grep ":${WEB_PORT} " | awk '{print $NF}' | head -n 1
}

# 查询桌面端进程 PID（命令行含 main.py 的 python 进程，空表示未运行）
desktop_pid() {
    powershell -NoProfile -Command \
        "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'main\.py' } | Select-Object -First 1 -ExpandProperty ProcessId)" 2>/dev/null \
        | tr -d '\r'
}

# 校验 PID 对应进程的命令行包含指定关键字，避免误杀
_pid_cmdline_match() {
    local pid="$1" pattern="$2"
    local cmdline
    cmdline=$(powershell -NoProfile -Command \
        "(Get-CimInstance Win32_Process -Filter 'ProcessId=$pid').CommandLine" 2>/dev/null | tr -d '\r')
    [[ -n "$cmdline" && "$cmdline" == *"$pattern"* ]]
}

kill_pid() {
    local pid="$1" pattern="$2"
    if _pid_cmdline_match "$pid" "$pattern"; then
        taskkill //PID "$pid" //F //T >/dev/null 2>&1
        return 0
    fi
    echo "  警告：PID $pid 命令行不含 '$pattern'，跳过（避免误杀）"
    return 1
}

start_web() {
    local pid
    pid=$(web_pid)
    if [[ -n "$pid" ]]; then
        echo "Web 应用已在运行（PID $pid，http://127.0.0.1:${WEB_PORT}）"
        return 0
    fi
    nohup uv run python -m web.app >>"$WEB_LOG" 2>&1 &
    disown
    sleep 3
    pid=$(web_pid)
    if [[ -n "$pid" ]]; then
        echo "Web 应用已启动（PID $pid，http://127.0.0.1:${WEB_PORT}，日志 $WEB_LOG）"
    else
        echo "Web 应用启动失败，请查看 $WEB_LOG"
        return 1
    fi
}

stop_web() {
    local pid
    pid=$(web_pid)
    if [[ -z "$pid" ]]; then
        echo "Web 应用未在运行"
        return 0
    fi
    kill_pid "$pid" "web.app"
    sleep 1
    if [[ -z "$(web_pid)" ]]; then
        echo "Web 应用已关闭"
    else
        echo "Web 应用关闭失败（PID $pid 仍占用端口 ${WEB_PORT}）"
        return 1
    fi
}

start_desktop() {
    local pid
    pid=$(desktop_pid)
    if [[ -n "$pid" ]]; then
        echo "桌面端已在运行（PID $pid）"
        return 0
    fi
    nohup uv run python main.py >>"$DESKTOP_LOG" 2>&1 &
    disown
    sleep 3
    pid=$(desktop_pid)
    if [[ -n "$pid" ]]; then
        echo "桌面端已启动（PID $pid，日志 $DESKTOP_LOG）"
    else
        echo "桌面端启动失败，请查看 $DESKTOP_LOG"
        return 1
    fi
}

stop_desktop() {
    local pid
    pid=$(desktop_pid)
    if [[ -z "$pid" ]]; then
        echo "桌面端未在运行"
        return 0
    fi
    kill_pid "$pid" "main.py"
    sleep 1
    if [[ -z "$(desktop_pid)" ]]; then
        echo "桌面端已关闭"
    else
        echo "桌面端关闭失败（PID $pid）"
        return 1
    fi
}

status_web() {
    local pid
    pid=$(web_pid)
    if [[ -n "$pid" ]]; then
        echo "Web 应用：运行中（PID $pid，http://127.0.0.1:${WEB_PORT}）"
    else
        echo "Web 应用：未运行"
    fi
}

status_desktop() {
    local pid
    pid=$(desktop_pid)
    if [[ -n "$pid" ]]; then
        echo "桌面端：运行中（PID $pid）"
    else
        echo "桌面端：未运行"
    fi
}

run_for() {
    local action="$1" target="$2"
    case "$target" in
        web)     "${action}_web" ;;
        desktop) "${action}_desktop" ;;
        all)     "${action}_web"; "${action}_desktop" ;;
        *) echo "未知目标：$target（可选 web / desktop / all）"; exit 1 ;;
    esac
}

ACTION="${1:-status}"
TARGET="${2:-all}"

case "$ACTION" in
    start|stop|status)
        run_for "$ACTION" "$TARGET"
        ;;
    restart)
        run_for stop "$TARGET"
        run_for start "$TARGET"
        ;;
    *)
        echo "用法：bash scripts/app.sh <start|stop|restart|status> [web|desktop|all]"
        exit 1
        ;;
esac
