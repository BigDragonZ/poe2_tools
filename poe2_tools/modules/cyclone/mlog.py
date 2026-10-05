#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旋风模块文件日志：logs/cyclone.log（utf-8，毫秒时间戳，追加模式）。

- 视觉线程 / 输入线程 / 热键回调都可能写日志，用 logging 自带锁保证线程安全
- 文件日志用于事后排查，打得比 UI 日志细；节流由调用方负责
- 重复调用 get_file_logger 不重复挂 handler
"""

from __future__ import annotations

import logging
from pathlib import Path

# 仓库根目录（本文件在 poe2_tools/modules/cyclone/ 内，需向上四级）
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 默认日志文件
LOG_PATH = REPO_ROOT / "logs" / "cyclone.log"

_LOGGER_NAME = "poe2_tools.cyclone.file"


def get_file_logger(log_path: Path | str | None = None) -> logging.Logger:
    """获取旋风模块文件日志器；目录自动创建，同路径重复调用不重复挂 handler。"""
    path = Path(log_path) if log_path is not None else LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    target = str(path)
    for handler in logger.handlers:
        if getattr(handler, "_cyclone_log_path", None) == target:
            return logger
    handler = logging.FileHandler(path, encoding="utf-8")
    # 默认 asctime 自带毫秒（2026-10-01 12:00:00,123）
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    handler._cyclone_log_path = target  # type: ignore[attr-defined]
    logger.addHandler(handler)
    return logger
