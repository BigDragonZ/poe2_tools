# 2026-09-13 背包整理模块迁移

## 新增

- 迁移 `poe1_tools/poe_tools/common.py` → `poe2_tools/common.py`：配置读写改为 UTF-8 编码（纯 Python，不再兼容 AHK），窗口检测改为 "Path of Exile 2"
- 迁移 `poe1_tools/poe_tools/bag.py` → `poe2_tools/bag.py`：两点标定（F3/F4）、一键存仓；抽出纯函数 `grid_points()` 便于单测
- 背包整理页接入功能：热键捕获设置、行数/列数保存、标定说明
- 主窗口接入全局热键：整理（默认 F1）、标定 F3/F4、紧急停止 F12；运行状态区（POE2 前台 / 标定 / 整理）每 500ms 刷新；共享日志区
- `tests/test_bag.py`：网格坐标、热键与行列配置读写、标定配置、UTF-8 编码共 18 项单元测试
