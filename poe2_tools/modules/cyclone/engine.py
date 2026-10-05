#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旋风引擎：三线程装配 + 窗口感知 + 切换键 + 生命周期 + 执行日志。

三线程生产者-消费者模型，强隔离：
- 截图线程（CaptureThread，dxcam）→ FrameBuffer（只存最新帧）
- 视觉仲裁线程（本类 _vision_loop，16ms 节拍）→ 数字分类 + 拾取检测
  + FSM 仲裁 → 动作队列
- 输入执行线程（InputExecutor，SendInput）← 动作队列
- 生命 OCR 低频分支（_life_loop，500ms 节拍）：RapidOCR 生命数值区
  → parse_life_text → life_ratio 缓存，视觉线程随取随用（不阻塞 16ms 节拍）

数字识别（vision.classify_digit）：
- 模板：templates/cyclone/（tools.py 从监控样本提取），缺失时数字检测禁用
  （拾取/喝药不受影响），日志提示，不崩溃
- ROI：config vision.q_roi/e_roi（客户区坐标）+ client_origin() 换算屏幕坐标

感知：
- 仅 POE2 前台时激活；每 foreground_check_ms 校验一次，非前台强制压入 IDLE
- F2（app 层热键调 engine.toggle）或鼠标侧键（x2，可配置）切换 启动/停止
- 停止/急停一律走 FSM force_idle → 执行线程 CLEAR_ALL（补发物理 Left Up）

执行日志：
- 文件日志 logs/cyclone.log（mlog.get_file_logger，毫秒时间戳，线程安全）：
  启动配置摘要、FSM 转移（含原因）、动作链摘要、拾取/黑名单、识别节流日志
- UI 日志（logger 回调）只保留关键事件，避免刷屏
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from typing import Any

from poe2_tools.core import window
from poe2_tools.modules.cyclone import loot, mlog, vision
from poe2_tools.modules.cyclone.capture import CaptureThread, FrameBuffer
from poe2_tools.modules.cyclone.config import load_config
from poe2_tools.modules.cyclone.executor import InputExecutor
from poe2_tools.modules.cyclone.fsm import (
    Action,
    ActionKind,
    CycloneFSM,
    FrameSignals,
    State,
)

logger = logging.getLogger(__name__)

# 仓库根目录（本文件在 poe2_tools/modules/cyclone/ 内，需向上四级）
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 默认模板目录
TEMPLATE_DIR = REPO_ROOT / "templates" / "cyclone"

# 视觉仲裁循环节拍（秒）
_VISION_TICK = 0.016

# 识别节流日志间隔（秒）
_DETECT_LOG_INTERVAL_S = 2.0


def format_actions(actions: list[Action]) -> str:
    """动作链摘要，如 RELEASE_LEFT→LOCK_CURSOR(1234,567,30ms)→CLICK_LEFT。"""
    parts = []
    for a in actions:
        if a.kind == ActionKind.LOCK_CURSOR:
            parts.append(f"LOCK_CURSOR({a.x},{a.y},{a.duration_ms}ms)")
        elif a.kind == ActionKind.PRESS_KEY:
            parts.append(f"PRESS_{(a.key or '').upper()}")
        elif a.kind == ActionKind.WAIT:
            parts.append(f"WAIT({a.duration_ms}ms)")
        else:
            parts.append(a.kind.name)
    return "→".join(parts)


class _LifeOcr:
    """生命数值 OCR：RapidOCR 懒加载封装（识别失败不拖垮引擎）。"""

    def __init__(self) -> None:
        self._engine: Any = None
        self._failed = False

    def recognize(self, roi_bgr: Any) -> str | None:
        """识别 ROI 文本；引擎不可用或识别失败返回 None。"""
        if self._failed:
            return None
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415 懒导入

                self._engine = RapidOCR()
            except Exception as exc:  # noqa: BLE001
                logger.warning("生命 OCR 引擎初始化失败: %s", exc)
                self._failed = True
                return None
        try:
            import cv2  # noqa: PLC0415

            result, _ = self._engine(cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2RGB))
        except Exception as exc:  # noqa: BLE001 单帧失败不中断
            logger.warning("生命 OCR 识别异常: %s", exc)
            return None
        if not result:
            return None
        return " ".join(str(item[1]) for item in result)


class CycloneEngine:
    """旋风引擎编排器。"""

    def __init__(
        self,
        logger: Callable[[str, str], None] | None = None,
        config_path: Path | str | None = None,
        template_dir: Path | str | None = None,
    ) -> None:
        self._logger = logger
        self.config: dict[str, Any] = load_config(config_path)
        self._template_dir = Path(template_dir) if template_dir is not None else TEMPLATE_DIR
        self._flog = mlog.get_file_logger()

        self.buffer = FrameBuffer()
        self.capture = CaptureThread(self.buffer, int(self.config["system"]["capture_fps"]))
        self.fsm = CycloneFSM(self.config["loot"], self.config["combat"])
        self.executor = InputExecutor()
        self._templates = vision.TemplateLibrary()
        self._life_ocr = _LifeOcr()

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._vision_thread: threading.Thread | None = None
        self._life_thread: threading.Thread | None = None
        self._life_lock = threading.Lock()
        self._life_ratio: float | None = None
        self._running = False
        self._last_foreground_check = 0.0
        self._next_detect_log = 0.0
        # 最近一次识别结果（状态展示用）
        self._last_q_stacks: int | None = None
        self._last_e_charges: int | None = None

    # ============================================================
    # 日志与状态
    # ============================================================
    def log(self, message: str, level: str = "INFO") -> None:
        """UI 日志（关键事件）；同时写入文件日志。"""
        flog = {"WARN": self._flog.warning, "ERROR": self._flog.error}.get(level, self._flog.info)
        flog(message)
        if self._logger is not None:
            self._logger(message, level)

    @property
    def running(self) -> bool:
        return self._running

    def status(self) -> dict[str, Any]:
        """UI 状态：运行标志、FSM 状态、Q 层数、E 充能、生命比值、检测启用标志。"""
        with self._life_lock:
            life_ratio = self._life_ratio
        return {
            "running": self._running,
            "state": self.fsm.state.value,
            "q_stacks": self._last_q_stacks,
            "e_charges": self._last_e_charges,
            "life_ratio": life_ratio,
            "digits_enabled": not self._templates.empty(),
        }

    # ============================================================
    # 生命周期
    # ============================================================
    def start(self) -> bool:
        """启动全部线程与监听；dxcam 不可用或 POE2 未前台时失败。"""
        with self._lock:
            if self._running:
                return True
            if not window.is_poe_active():
                self.log("POE2 窗口未激活，无法启动旋风引擎", "WARN")
                return False
            if not self.capture.start():
                self.log("dxcam 初始化失败，旋风引擎未启动", "ERROR")
                return False
            self.reload_templates()
            self._flog.info(
                "启动配置：q_roi=%s e_roi=%s life_roi=%s 模板=%s（白 %s 暗 %s）| "
                "combat(接敌帧=%d, 脱战=%.1fs, Q满=%d, E满=%d, E冷却=%.1fs, 血阈=%.2f, 药间隔=%.1fs)",
                self.config["vision"]["q_roi"], self.config["vision"]["e_roi"],
                self.config["vision"]["life_roi"], self._template_dir,
                sorted(self._templates.white), sorted(self._templates.dark),
                int(self.config["combat"]["engage_growth_frames"]),
                float(self.config["combat"]["disengage_timeout_s"]),
                int(self.config["combat"]["q_max_stacks"]),
                int(self.config["combat"]["e_full_charges"]),
                float(self.config["combat"]["e_cooldown_s"]),
                float(self.config["combat"]["life_threshold"]),
                float(self.config["combat"]["flask_interval_s"]),
            )
            self.executor.start()
            self._stop.clear()
            self._last_foreground_check = 0.0
            self._next_detect_log = 0.0
            self._last_q_stacks = None
            self._last_e_charges = None
            with self._life_lock:
                self._life_ratio = None
            self._register_listeners()
            self._vision_thread = threading.Thread(target=self._vision_loop, daemon=True)
            self._vision_thread.start()
            self._life_thread = threading.Thread(target=self._life_loop, daemon=True)
            self._life_thread.start()
            self._running = True
        self.log("旋风引擎已启动：F2/侧键切换 赶路/停止")
        return True

    def stop(self, source: str = "界面按钮") -> None:
        """停止全部线程与监听，急停清空模拟输入。source 记录触发源。"""
        with self._lock:
            if not self._running:
                return
            self._running = False
        self._flog.info("停止旋风引擎（来源：%s），急停清空模拟输入", source)
        self._stop.set()
        self._unregister_listeners()
        self.capture.stop()
        for action in self.fsm.force_idle():
            self.executor.submit([action])
        self.executor.stop()
        if self._vision_thread is not None:
            self._vision_thread.join(timeout=1.0)
            self._vision_thread = None
        if self._life_thread is not None:
            self._life_thread.join(timeout=2.0)
            self._life_thread = None
        self.log("旋风引擎已停止，所有模拟输入已清空")

    # ============================================================
    # 模板热重载
    # ============================================================
    def reload_templates(self) -> bool:
        """加载/热重载数字模板库；返回数字检测是否启用。"""
        self._templates = vision.load_templates(self._template_dir)
        if self._templates.empty():
            self._flog.info("数字检测禁用：模板目录不可用 %s", self._template_dir)
            self.log(f"缺少旋风数字模板（{self._template_dir}），Q/E 检测已禁用："
                     "请先运行模板提取", "WARN")
            return False
        self._flog.info(
            "数字模板已加载：白 %s，暗 %s",
            sorted(self._templates.white), sorted(self._templates.dark),
        )
        return True

    # ============================================================
    # 切换键
    # ============================================================
    def toggle(self) -> None:
        """F2/侧键切换：仅 POE2 前台时生效。"""
        if not window.is_poe_active():
            return
        now = time.monotonic()
        prev = self.fsm.state
        actions = self.fsm.toggle(now)
        self.executor.submit(actions)
        self._flog.info(
            "切换：%s→%s 动作=%s", prev.value, self.fsm.state.value, format_actions(actions)
        )
        if self.fsm.state == State.IDLE:
            self.log("旋风引擎：已关闭（急停清空）")
        else:
            self.log("旋风引擎：赶路模式（按住左键）")

    def _register_listeners(self) -> None:
        """注册侧键切换监听（mouse 库全局钩子）；F2 由 app 层热键调 toggle()。"""
        import mouse  # noqa: PLC0415 监听仅运行期需要

        toggle_button = str(self.config["system"]["toggle_button"])
        mouse.on_button(self.toggle, buttons=(toggle_button,), types=("down",))

    def _unregister_listeners(self) -> None:
        import mouse  # noqa: PLC0415

        try:
            mouse.unhook_all()
        except Exception:
            pass

    # ============================================================
    # 生命 OCR 低频分支
    # ============================================================
    def _life_loop(self) -> None:
        """生命 OCR 低频循环：按 life_ocr_interval_ms 节拍识别生命数值区。"""
        interval = int(self.config["vision"]["life_ocr_interval_ms"]) / 1000.0
        life_roi = self.config["vision"]["life_roi"]
        while not self._stop.is_set():
            frame, _stamp = self.buffer.get()
            if frame is not None and self.fsm.state != State.IDLE:
                origin = window.client_origin()
                if origin is not None:
                    try:
                        x1, y1, x2, y2 = _roi_screen(origin, life_roi)
                        roi = frame[y1:y2, x1:x2]
                        if roi.size > 0:
                            text = self._life_ocr.recognize(roi)
                            parsed = vision.parse_life_text(text or "")
                            ratio = None
                            if parsed is not None:
                                cur, maximum = parsed
                                ratio = cur / maximum
                            with self._life_lock:
                                self._life_ratio = ratio
                    except Exception as exc:  # noqa: BLE001 单帧失败不中断
                        logger.warning("生命检测异常: %s", exc)
            self._stop.wait(interval)

    # ============================================================
    # 视觉仲裁线程
    # ============================================================
    def _vision_loop(self) -> None:
        """仲裁主循环：取最新帧 → 检测 → FSM.step → 动作队列。"""
        resolution = self.config["system"]["resolution"]
        loot_cfg = self.config["loot"]
        foreground_interval = int(self.config["system"]["foreground_check_ms"]) / 1000.0
        while not self._stop.is_set():
            now = time.monotonic()
            # 前台校验（每 foreground_check_ms 一次，非前台强制 IDLE）
            if now - self._last_foreground_check >= foreground_interval:
                self._last_foreground_check = now
                active = window.is_poe_active()
                prev = self.fsm.state
                actions = self.fsm.set_foreground(active)
                if prev != self.fsm.state:
                    self._flog.info(
                        "前台校验：%s，%s→%s 动作=%s",
                        "前台" if active else "失焦", prev.value,
                        self.fsm.state.value, format_actions(actions),
                    )
                self.executor.submit(actions)
            frame, _stamp = self.buffer.get()
            if frame is not None and self.fsm.state != State.IDLE:
                signals = self._detect(frame, resolution, loot_cfg)
                self._log_detect_throttled(signals, now)
                prev = self.fsm.state
                blacklist_before = len(self.fsm.blacklist)
                actions = self.fsm.step(signals, now)
                self._log_step(prev, signals, actions, blacklist_before)
                self.executor.submit(actions)
            self._stop.wait(_VISION_TICK)

    def _detect(
        self,
        frame: Any,
        resolution: list[int],
        loot_cfg: dict[str, Any],
    ) -> FrameSignals:
        """单帧检测：光标附近黑框 + Q/E 数字 + 生命缓存比值。"""
        cursor = self._cursor_pos()
        loot_center = None
        if cursor is not None:
            try:
                loot_center = loot.find_loot_box(frame, cursor[0], cursor[1], loot_cfg, resolution)
            except Exception as exc:  # noqa: BLE001 单帧失败不中断仲裁
                logger.warning("拾取检测异常: %s", exc)
        q_stacks: int | None = None
        e_charges: int | None = None
        e_usable = False
        if not self._templates.empty():
            origin = window.client_origin()
            if origin is not None:
                confidence = float(self.config["vision"]["match_confidence"])
                q_stacks = self._classify_roi(
                    frame, origin, self.config["vision"]["q_roi"], confidence
                )[0]
                e_charges, e_state = self._classify_roi(
                    frame, origin, self.config["vision"]["e_roi"], confidence
                )
                e_usable = e_state == vision.DigitState.WHITE
        self._last_q_stacks = q_stacks
        self._last_e_charges = e_charges
        with self._life_lock:
            life_ratio = self._life_ratio
        return FrameSignals(
            q_stacks=q_stacks,
            e_charges=e_charges,
            e_usable=e_usable,
            loot_center=loot_center,
            life_ratio=life_ratio,
        )

    def _classify_roi(
        self,
        frame: Any,
        origin: Any,
        roi_box: list[int],
        confidence: float,
    ) -> tuple[int | None, vision.DigitState | None]:
        """按客户区 ROI 裁剪帧并分类数字；异常时返回 (None, None)。"""
        try:
            x1, y1, x2, y2 = _roi_screen(origin, roi_box)
            roi = frame[y1:y2, x1:x2]
            if roi.size == 0:
                return None, None
            digit, state, _conf = vision.classify_digit(roi, self._templates, confidence)
            return digit, state
        except Exception as exc:  # noqa: BLE001
            logger.warning("数字检测异常: %s", exc)
            return None, None

    # ============================================================
    # 文件日志打点（节流，避免拖垮 60fps 循环）
    # ============================================================
    def _log_detect_throttled(self, signals: FrameSignals, now: float) -> None:
        """识别节流日志：每 2 秒一次当前层数/充能/生命状态。"""
        if now < self._next_detect_log:
            return
        self._next_detect_log = now + _DETECT_LOG_INTERVAL_S
        self._flog.info(
            "检测：Q=%s E=%s(%s) 生命=%s 拾取=%s",
            signals.q_stacks if signals.q_stacks is not None else "-",
            signals.e_charges if signals.e_charges is not None else "-",
            "可用" if signals.e_usable else "冷却/未知",
            f"{signals.life_ratio:.2f}" if signals.life_ratio is not None else "-",
            signals.loot_center if signals.loot_center is not None else "-",
        )

    def _log_step(
        self,
        prev: State,
        signals: FrameSignals,
        actions: list[Action],
        blacklist_before: int,
    ) -> None:
        """FSM 转移与动作链日志（仅状态变化或有动作时写）。"""
        blacklist_after = len(self.fsm.blacklist)
        if blacklist_after < blacklist_before:
            self._flog.info("黑名单过期 %d 项（剩余 %d）", blacklist_before - blacklist_after, blacklist_after)
        curr = self.fsm.state
        if curr == prev and not actions:
            return
        reason = self._transition_reason(prev, curr, signals, blacklist_after > blacklist_before)
        self._flog.info(
            "转移 %s→%s 原因=%s 动作=%s",
            prev.value, curr.value, reason, format_actions(actions) or "（无）",
        )

    def _transition_reason(
        self, prev: State, curr: State, signals: FrameSignals, blacklisted: bool
    ) -> str:
        """推断状态转移原因（用于日志）。"""
        if curr == State.LOOTING and signals.loot_center is not None:
            return f"拾取命中{signals.loot_center}"
        if prev == State.LOOTING:
            return "寻路超时进黑名单" if blacklisted else "拾取成功（黑框消失）"
        if curr == State.ENGAGE:
            return f"接敌（Q 层数 {signals.q_stacks} 连续增长）"
        if prev == State.ENGAGE and curr == State.TRAVEL:
            return "脱战（层数归零且无增长）"
        if curr == State.IDLE:
            return "强制压入 IDLE"
        return "状态转移"

    @staticmethod
    def _cursor_pos() -> tuple[int, int] | None:
        """当前光标屏幕绝对坐标。"""
        point = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return None
        return point.x, point.y


def _roi_screen(origin: Any, roi_box: list[int]) -> tuple[int, int, int, int]:
    """客户区坐标 ROI → 屏幕坐标 ROI。"""
    return (
        origin.x + int(roi_box[0]),
        origin.y + int(roi_box[1]),
        origin.x + int(roi_box[2]),
        origin.y + int(roi_box[3]),
    )
