# 2026-09-13 项目骨架与主界面

## 新增

- 初始化 git 仓库，远程 `git@github.com:BigDragonZ/poe2_tools.git`，主分支 `main`
- uv 项目骨架：`pyproject.toml`（pydirectinput / keyboard / mouse + dev 组 pytest）、`uv.lock`、`.gitignore`
- tkinter 主界面（`uv run python main.py`）：ttk.Notebook 四个标签页
  - 背包整理：整理热键、行数/列数设置表单（功能逻辑待迁移）
  - 战斗：启停热键、七个按键的策略（禁用/连点/按住不放）与间隔表单（功能逻辑待迁移）
  - 地图、装备：占位页
- 文档：`AGENTS.md`、`docs/项目框架.md`、`docs/功能说明.md`（含待完成清单）
- 工作流文件：`changelog/` 目录规范、`response.md` 问答记录
