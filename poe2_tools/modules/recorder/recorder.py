#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输入记录器：F2 切换记录，采集鼠标按键与 Q/E 按下事件，按轮写 JSON。

- 只记录「按下」事件（不记录抬起、移动），时间戳为相对本轮开始的秒数
- 键盘用 keyboard.on_press_key、鼠标用 mouse.hook，首次开始时注册一次并常驻，
  用记录开关过滤事件（不反复注册/摘除，避免与其它模块的钩子互相干扰）
- 注意：刷图助手停止时会 unhook_all 清空全部鼠标/键盘钩子，
  记录期间请勿启停刷图助手，否则本轮记录会中断采数
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import keyboard
import mouse

Logger = Callable[[str], None]

# 仓库根目录（本文件在 poe2_tools/modules/recorder/ 内，需向上四级）
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 记录文件目录（logs/ 不入库）
RECORD_DIR = REPO_ROOT / "logs" / "recordings"

# 采集的键盘按键（鼠标按键全量采集）
KEYS = ("q", "e")

# 切换防抖：F2 按住自动重复不会反复翻转记录状态
TOGGLE_DEBOUNCE_S = 0.5


class InputRecorder:
    """手动输入记录器（F2 开始/停止一轮）。"""

    def __init__(self, logger: Logger | None = None, record_dir: Path | str | None = None) -> None:
        self._logger = logger
        self.record_dir = Path(record_dir) if record_dir is not None else RECORD_DIR
        self._lock = threading.Lock()
        self._recording = False
        self._events: list[dict] = []
        self._start_perf = 0.0
        self._start_wall = ""
        self._last_toggle = 0.0
        self._hooked = False

    # --------------------------------------------------------
    # 对外接口
    # --------------------------------------------------------
    @property
    def recording(self) -> bool:
        return self._recording

    def log(self, message: str) -> None:
        print(message)
        if self._logger is not None:
            self._logger(message)

    def toggle(self) -> None:
        """F2 入口：记录中 → 停止并保存；空闲 → 开始新一轮。"""
        now = time.perf_counter()
        with self._lock:
            if now - self._last_toggle < TOGGLE_DEBOUNCE_S:
                return
            self._last_toggle = now
        if self.recording:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        """开始新一轮记录（清空上一轮未保存的缓冲）。"""
        with self._lock:
            if self._recording:
                return
            self._events = []
            self._start_perf = time.perf_counter()
            self._start_wall = datetime.now().isoformat(timespec="milliseconds")
            self._recording = True
        self._ensure_hooks()
        self.log("开始记录输入（再按 F2 停止）：采集鼠标按键与 Q/E 按下")

    def stop(self) -> Path | None:
        """停止记录并保存本轮 JSON；未在记录时返回 None。"""
        with self._lock:
            if not self._recording:
                return None
            self._recording = False
            events = list(self._events)
            started = self._start_wall
            duration = time.perf_counter() - self._start_perf
        path = self._save_round(started, duration, events)
        self.log(f"已停止记录：{len(events)} 个事件，保存 logs/recordings/{path.name}")
        return path

    def status(self) -> dict:
        """状态快照（界面轮询用）。"""
        with self._lock:
            return {
                "recording": self._recording,
                "event_count": len(self._events),
                "rounds": len(self.list_rounds()),
            }

    def list_rounds(self) -> list[Path]:
        """已保存的轮次文件（按文件名升序 = 时间升序）。"""
        if not self.record_dir.exists():
            return []
        return sorted(self.record_dir.glob("round-*.json"))

    def clear_rounds(self) -> int:
        """删除全部轮次文件，返回删除数量。"""
        count = 0
        for path in self.list_rounds():
            try:
                path.unlink()
                count += 1
            except OSError:
                pass
        return count

    # --------------------------------------------------------
    # 事件采集（keyboard/mouse 钩子线程）
    # --------------------------------------------------------
    def _ensure_hooks(self) -> None:
        """首次开始时注册常驻钩子，之后用记录开关过滤事件。"""
        if self._hooked:
            return
        for key in KEYS:
            keyboard.on_press_key(key, lambda _event, name=key: self._on_key(name))
        mouse.hook(self._on_mouse)
        self._hooked = True

    def _on_key(self, name: str) -> None:
        with self._lock:
            if not self._recording:
                return
            t = time.perf_counter() - self._start_perf
            self._events.append({"t": round(t, 3), "kind": "key", "name": name})

    def _on_mouse(self, event: object) -> None:
        if not isinstance(event, mouse.ButtonEvent) or event.event_type != "down":
            return
        with self._lock:
            if not self._recording:
                return
            t = time.perf_counter() - self._start_perf
            x, y = mouse.get_position()
            self._events.append(
                {"t": round(t, 3), "kind": "mouse", "name": event.button, "x": x, "y": y}
            )

    # --------------------------------------------------------
    # 保存
    # --------------------------------------------------------
    def _save_round(self, started: str, duration: float, events: list[dict]) -> Path:
        self.record_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        path = self.record_dir / f"round-{stamp}.json"
        payload = {
            "version": 1,
            "started_at": started,
            "duration_s": round(duration, 3),
            "events": events,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
