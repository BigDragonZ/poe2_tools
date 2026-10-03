#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dxcam 截图线程：最新帧共享 buffer。

dxcam（Desktop Duplication API，≥60FPS）仅在本模块内懒导入：
纯逻辑与测试不依赖 dxcam（测试环境可能无法初始化）。
buffer 只保留最新一帧，视觉仲裁线程随取随用，不排队积压。
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)

# 无新帧时的轮询休眠（秒）
_IDLE_SLEEP = 0.002


class FrameBuffer:
    """最新帧共享 buffer（线程安全，只存一帧）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._stamp = 0.0

    def put(self, frame: np.ndarray) -> None:
        with self._lock:
            self._frame = frame
            self._stamp = time.monotonic()

    def get(self) -> tuple[np.ndarray | None, float]:
        """返回 (最新帧, 采集时间戳)；尚无帧时帧为 None。"""
        with self._lock:
            return self._frame, self._stamp


class CaptureThread:
    """dxcam 采集线程：按目标帧率抓全屏（BGR），写入 FrameBuffer。"""

    def __init__(self, buffer: FrameBuffer, target_fps: int = 60) -> None:
        self._buffer = buffer
        self._interval = 1.0 / max(1, target_fps)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._camera = None

    def start(self) -> bool:
        """启动采集线程；dxcam 初始化失败时记日志并返回 False。"""
        if self._thread is not None and self._thread.is_alive():
            return True
        try:
            import dxcam  # noqa: PLC0415 懒导入，隔离到本模块

            # output_color=BGR 直接喂给 OpenCV（dxcam ≥0.2 的参数名）
            try:
                self._camera = dxcam.create(output_color="BGR")
            except TypeError:
                self._camera = dxcam.create()
        except Exception as exc:
            logger.warning("dxcam 初始化失败: %s", exc)
            self._camera = None
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """停止采集线程并释放相机。"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._camera is not None:
            try:
                self._camera.release()
            except Exception:
                pass
            self._camera = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._camera.grab() if self._camera is not None else None
            except Exception as exc:  # noqa: BLE001 单帧失败不中断采集
                logger.warning("dxcam 抓帧异常: %s", exc)
                frame = None
            if frame is None:
                # 无新帧（画面未变化）时短暂休眠，避免空转
                self._stop.wait(_IDLE_SLEEP)
                continue
            self._buffer.put(frame)
            self._stop.wait(self._interval)
