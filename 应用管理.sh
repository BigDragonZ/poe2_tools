# =============================================================================
# 应用管理速查（本文档仅记录命令，复制粘贴即用，不要直接执行本文件）
#
# 管理对象：
#   web     = 经济记录 Web 应用（uv run python -m web.app，http://127.0.0.1:8321）
#   desktop = Python 桌面端主界面（uv run python main.py，tkinter）
#
# 统一管理脚本：scripts/app.sh（Git Bash / WSL / PowerShell 均可，内部自动调用
# powershell.exe 操作 Windows 进程，不依赖当前 shell 的 netstat/uv）
# =============================================================================

# -----------------------------------------------------------------------------
# 一、统一管理脚本（推荐）
# -----------------------------------------------------------------------------

# 查看状态（默认全部，可换 web / desktop / all）
bash scripts/app.sh status

# 启动
bash scripts/app.sh start web        # 只启动 Web 应用
bash scripts/app.sh start desktop    # 只启动桌面端
bash scripts/app.sh start all        # 全部启动

# 关闭
bash scripts/app.sh stop web
bash scripts/app.sh stop desktop
bash scripts/app.sh stop all

# 重启
bash scripts/app.sh restart web
bash scripts/app.sh restart desktop
bash scripts/app.sh restart all

# 查看运行日志
tail -f logs/web.log        # Web 应用日志
tail -f logs/desktop.log    # 桌面端日志

# -----------------------------------------------------------------------------
# 二、单条命令（不依赖脚本，仅限 Git Bash；WSL 无 netstat/uv 请用脚本）
# -----------------------------------------------------------------------------

# 查 8321 端口占用（最后一列是 PID）
netstat -ano | grep LISTENING | grep ":8321 "

# 按 PID 强制结束（含子进程，注意双斜杠防路径转换）
taskkill //PID <PID> //F //T

# 后台启动 Web 应用
nohup uv run python -m web.app >> logs/web.log 2>&1 & disown

# 后台启动桌面端
nohup uv run python main.py >> logs/desktop.log 2>&1 & disown

# -----------------------------------------------------------------------------
# 三、单条命令（PowerShell）
# -----------------------------------------------------------------------------

# 查 8321 端口占用 PID
netstat -ano | Select-String ":8321 " | Select-String LISTENING

# 查看 PID 对应进程信息（确认识别无误再结束）
Get-Process -Id <PID>

# 强制结束进程
Stop-Process -Id <PID> -Force

# 前台启动（当前窗口独占，Ctrl+C 停止）
uv run python -m web.app      # Web 应用
uv run python main.py         # 桌面端

# 后台启动（隐藏窗口，日志写入 logs/，每次启动覆盖）
Start-Process cmd -ArgumentList '/c uv run python -m web.app > logs\web.log 2>&1' -WorkingDirectory 'D:\game\poe2_tools' -WindowStyle Hidden
Start-Process cmd -ArgumentList '/c uv run python main.py > logs\desktop.log 2>&1' -WorkingDirectory 'D:\game\poe2_tools' -WindowStyle Hidden

# 按端口查 PID 的另一种方式（不依赖 netstat）
(Get-NetTCPConnection -LocalPort 8321 -State Listen).OwningProcess

# -----------------------------------------------------------------------------
# 常见问题
# -----------------------------------------------------------------------------

# 启动报 "error while attempting to bind on address ('127.0.0.1', 8321)"
# => 端口被旧实例占用，执行 bash scripts/app.sh restart web 即可
