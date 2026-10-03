#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刷图自动化编排器：三线程装配 + 窗口/UI 感知 + 侧键切换 + 生命周期 + 执行日志。

三线程生产者-消费者模型，强隔离：
- 截图线程（CaptureThread，dxcam）→ FrameBuffer（只存最新帧）
- 视觉仲裁线程（本类 _vision_loop）→ 纯函数检测 + FSM 仲裁 → 动作队列
- 输入执行线程（InputExecutor，SendInput）← 动作队列

Q=6 检测（F5 + 右键两角标记标定）：
- 掩模：启动时加载 templates/q6.png 并二值化；标定成功可 reload_q6() 热重载；
  禁用状态下运行中每 Q6_RETRY_INTERVAL_S 秒自动重试加载（模板/坐标出现后自动启用）
- ROI：每帧取 settings.combat.q6_roi + client_origin()（重新标定即时生效）
- 未标定或无 q6.png 时 COMBOS 检测禁用，日志提示，不崩溃

执行日志：
- 文件日志 logs/mapping.log（mlog.get_file_logger，毫秒时间戳，线程安全）：
  启动配置摘要、Q ROI 截图测试、FSM 转移（含原因）、动作链摘要、拾取/黑名单、
  Q 匹配度节流日志
- UI 日志（bus.log）只保留关键事件，避免刷屏
- 启动时对标记区域截图做匹配测试（_test_q6_roi）：实况图存 templates/q6_live.png，
  匹配度/亮像素/阈值判定写入日志，供与 q6.png 模板对比排查

感知：
- 仅 POE2 前台时激活；每 foreground_check_ms 校验一次，非前台强制压入 IDLE
- I / Tab / Esc 切换「UI 打开」标志，UI 打开期间挂起 FSM
- 鼠标侧键（XButton2，mouse 库 'x2'）切换 启动/停止
- 停止/急停一律走 FSM force_idle → 执行线程 CLEAR_ALL（补发物理 Left Up）
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

from poe2_tools.config.settings import Settings
from poe2_tools.core import window
from poe2_tools.modules.mapping import loot, mlog, qstack
from poe2_tools.modules.mapping.calibrate import Q6_TEMPLATE_PATH
from poe2_tools.modules.mapping.capture import CaptureThread, FrameBuffer
from poe2_tools.modules.mapping.config import load_config
from poe2_tools.modules.mapping.fsm import (
    Action,
    ActionKind,
    FrameSignals,
    MappingFSM,
    State,
)
from poe2_tools.modules.mapping.input_exec import InputExecutor

logger = logging.getLogger(__name__)

# 视觉仲裁循环节拍（秒）
_VISION_TICK = 0.016

# COMBOS 禁用时的模板重试间隔（秒）
Q6_RETRY_INTERVAL_S = 2.0

# Q 匹配度节流日志间隔（秒）
_Q6_LOG_INTERVAL_S = 2.0

# Q ROI 实况调试快照（与 templates/q6.png 肉眼对比）
Q6_LIVE_PATH = Q6_TEMPLATE_PATH.parent / "q6_live.png"


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


class MappingAssistant:
    """刷图自动化编排器。"""

    def __init__(
        self,
        settings: Settings,
        logger: Callable[[str, str], None] | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self.settings = settings
        self._logger = logger
        self.config: dict[str, Any] = load_config(config_path)
        self._flog = mlog.get_file_logger()

        self.buffer = FrameBuffer()
        self.capture = CaptureThread(self.buffer, int(self.config["system"]["capture_fps"]))
        self.fsm = MappingFSM(self.config["loot"], self.config["combos"])
        self.executor = InputExecutor()
        self._q_mask: Any = None  # np.ndarray | None，启动时加载、可热重载

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._vision_thread: threading.Thread | None = None
        self._ui_open = False
        self._running = False
        self._last_foreground_check = 0.0
        # Q 检测日志/重试节流状态
        self._q6_next_retry = 0.0
        self._q6_next_log = 0.0
        self._q_full_prev = False
        self._last_q_conf: float | None = None

    # ============================================================
    # 日志与状态
    # ============================================================
    def log(self, message: str, level: str = "INFO") -> None:
        """UI 日志（关键事件）；同时写入文件日志（WARN/ERROR 对应文件日志级别）。"""
        flog = {"WARN": self._flog.warning, "ERROR": self._flog.error}.get(level, self._flog.info)
        flog(message)
        print(message)
        if self._logger is not None:
            self._logger(message, level)

    @property
    def running(self) -> bool:
        return self._running

    def status(self) -> dict[str, Any]:
        """UI 状态：运行标志、FSM 状态、Q 检测是否启用、UI 挂起标志。"""
        return {
            "running": self._running,
            "state": self.fsm.state.value,
            "q_enabled": self._q_mask is not None,
            "ui_open": self._ui_open,
        }

    # ============================================================
    # 生命周期
    # ============================================================
    def start(self) -> bool:
        """启动三线程与监听；dxcam 不可用或 POE2 未前台时失败。"""
        with self._lock:
            if self._running:
                return True
            if not window.is_poe_active():
                self.log("POE2 窗口未激活，无法启动刷图助手", "WARN")
                return False
            if not self.capture.start():
                self.log("dxcam 初始化失败，刷图助手未启动", "ERROR")
                return False
            self.reload_q6()
            self._log_config_summary()
            self._test_q6_roi()
            self.executor.start()
            self._stop.clear()
            self._ui_open = False
            self._last_foreground_check = 0.0
            self._q6_next_retry = time.monotonic() + Q6_RETRY_INTERVAL_S
            self._q6_next_log = 0.0
            self._q_full_prev = False
            self._register_listeners()
            self._vision_thread = threading.Thread(target=self._vision_loop, daemon=True)
            self._vision_thread.start()
            self._running = True
        self.log("刷图助手已启动：侧键切换 移动/拾取/连招 模式")
        return True

    def _log_config_summary(self) -> None:
        """启动配置摘要（文件日志）。"""
        loot_cfg = self.config["loot"]
        combo_cfg = self.config["combos"]
        mask_lit = int(self._q_mask.sum()) if self._q_mask is not None else 0
        self._flog.info(
            "启动配置：q6_roi=%s 模板=%s 掩模亮像素=%d COMBOS=%s | "
            "loot(roi=%d, V<=%d, 宽高比=%.1f~%.1f, 面积=%d~%d, 文本密度>=%.2f) | "
            "combos(阈值=%.2f, E→Q=%dms, 冷却=%dms)",
            self.settings.combat.q6_roi, Q6_TEMPLATE_PATH, mask_lit,
            "启用" if self._q_mask is not None else "禁用",
            loot_cfg["roi_size"], loot_cfg["black_v_max"],
            loot_cfg["aspect_ratio_min"], loot_cfg["aspect_ratio_max"],
            loot_cfg["area_min"], loot_cfg["area_max"], loot_cfg["text_density_min"],
            combo_cfg["match_confidence"], combo_cfg["e_to_q_delay_ms"],
            combo_cfg["combo_debounce_ms"],
        )

    def _test_q6_roi(self) -> None:
        """
        启动时对标记的 Q 区域截图测试：实况图存 templates/q6_live.png，
        二值化亮像素、与掩模的匹配度、阈值判定写入文件日志（失败不崩溃）。
        """
        roi_box = self.settings.combat.q6_roi
        if roi_box is None:
            self._flog.info("Q ROI 测试跳过：未标定（旋风页「标定 Q=6」→ 游戏内 F5 + 右键两角）")
            return
        origin = window.client_origin()
        if origin is None:
            self._flog.warning("Q ROI 测试失败：未找到 POE2 窗口")
            return
        try:
            import mss  # noqa: PLC0415 懒导入，与标定流程一致

            x1, y1, x2, y2 = qstack.q6_roi_screen(origin.x, origin.y, roi_box)
            with mss.mss() as sct:
                shot = sct.grab({"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1})
                import numpy as np  # noqa: PLC0415

                live = np.array(shot)[:, :, :3]
            import cv2  # noqa: PLC0415

            cv2.imwrite(str(Q6_LIVE_PATH), live)

            binary = qstack.binarize_roi(live)
            lit = int(binary.sum())
            x1c, y1c, x2c, y2c = roi_box
            size = f"{x2c - x1c}x{y2c - y1c}"
            if self._q_mask is None:
                self._flog.info(
                    "Q ROI 测试：区域 %s（%s）实况亮像素 %d；掩模不可用，COMBOS 检测禁用",
                    roi_box, size, lit,
                )
                return
            conf = qstack.mask_confidence(binary, self._q_mask)
            threshold = float(self.config["combos"]["match_confidence"])
            result = "达标" if conf >= threshold else "未达标"
            self._flog.info(
                "Q ROI 测试：区域 %s（%s）实况亮像素 %d，匹配度 %.3f（阈值 %.2f，%s），"
                "实况图 %s",
                roi_box, size, lit, conf, threshold, result, Q6_LIVE_PATH,
            )
            if conf < threshold:
                self.log(
                    f"Q ROI 测试未达标：匹配度 {conf:.3f} < {threshold:.2f}，"
                    f"请确认游戏内 Q 正显示 6，或对比 templates/q6_live.png 与 q6.png",
                    "WARN",
                )
        except Exception as exc:  # noqa: BLE001 截图测试失败不影响启动
            self._flog.warning("Q ROI 测试失败: %s", exc)

    def stop(self, source: str = "界面按钮") -> None:
        """停止全部线程与监听，急停清空模拟输入。source 记录触发源。"""
        with self._lock:
            if not self._running:
                return
            self._running = False
        self._flog.info("停止刷图助手（来源：%s），急停清空模拟输入", source)
        self._stop.set()
        self._unregister_listeners()
        self.capture.stop()
        for action in self.fsm.force_idle():
            self.executor.submit([action])
        self.executor.stop()
        if self._vision_thread is not None:
            self._vision_thread.join(timeout=1.0)
            self._vision_thread = None
        self.log("刷图助手已停止，所有模拟输入已清空")

    # ============================================================
    # Q=6 掩模热重载与自动恢复
    # ============================================================
    def reload_q6(self, template_path: Path | str | None = None, quiet: bool = False) -> bool:
        """
        热重载 Q=6 掩模（F5 标定成功后调用，立即生效无需重启）。
        返回加载后 COMBOS 是否启用；失败时 quiet=True 只写文件日志（自动重试用）。
        """
        was_enabled = self._q_mask is not None
        path = Path(template_path) if template_path is not None else Q6_TEMPLATE_PATH
        if self.settings.combat.q6_roi is None:
            self._q_mask = None
            self._flog.info("Q=6 检测禁用：q6_roi 未标定")
            if not quiet:
                self.log("未标定 Q=6 区域，COMBOS 检测已禁用：请在旋风页点「标定 Q=6」，游戏内按 F5 后右键标记数字两角", "WARN")
            return False
        self._q_mask = qstack.load_mask(path)
        if self._q_mask is None:
            self._flog.info("Q=6 检测禁用：模板不可用 %s", path)
            if not quiet:
                self.log("缺少 Q=6 模板（templates/q6.png），COMBOS 检测已禁用：请在旋风页点「标定 Q=6」，游戏内按 F5 后右键标记数字两角", "WARN")
            return False
        message = (
            f"Q=6 检测已启用：ROI {self.settings.combat.q6_roi}，"
            f"掩模亮像素 {int(self._q_mask.sum())}"
        )
        if not was_enabled:
            self.log(message)  # 禁用→启用是关键事件，UI 也提示
        else:
            self._flog.info("Q=6 掩模热重载：%s", message)
        return True

    def q6_retry_due(self, now: float) -> bool:
        """COMBOS 禁用时的重试节流判定：每 Q6_RETRY_INTERVAL_S 秒允许一次。"""
        return self._q_mask is None and now >= self._q6_next_retry

    # ============================================================
    # 侧键切换与 UI 感知
    # ============================================================
    def _register_listeners(self) -> None:
        """注册侧键切换与 UI 按键监听（mouse / keyboard 库全局钩子）。"""
        import keyboard  # noqa: PLC0415 监听仅运行期需要
        import mouse  # noqa: PLC0415

        toggle_button = str(self.config["system"]["toggle_button"])
        mouse.on_button(self._on_toggle, buttons=(toggle_button,), types=("down",))
        for key in self.config["system"]["ui_keys"]:
            keyboard.on_press_key(str(key), self._on_ui_key)

    def _unregister_listeners(self) -> None:
        import mouse  # noqa: PLC0415

        try:
            mouse.unhook_all()
        except Exception:
            pass
        # keyboard 的 UI 键监听交由全局 HotkeyManager 的 unhook_all 兜底；
        # 此处逐个解绑避免影响其他模块热键
        import keyboard  # noqa: PLC0415

        try:
            keyboard.unhook_all_keyboard()
        except Exception:
            pass

    def _on_toggle(self) -> None:
        """侧键回调：仅 POE2 前台时切换模式。"""
        if not window.is_poe_active():
            return
        now = time.monotonic()
        prev = self.fsm.state
        actions = self.fsm.toggle(now)
        self.executor.submit(actions)
        self._flog.info(
            "侧键切换：%s→%s 动作=%s", prev.value, self.fsm.state.value, format_actions(actions)
        )
        state = "移动模式（按住左键）" if self.fsm.state == State.MOVING else "已关闭（急停清空）"
        self.log(f"刷图助手：{state}")

    def _on_ui_key(self, _event: object) -> None:
        """UI 按键回调：仅 POE2 前台且模式开启时切换挂起标志。"""
        if not self._running or self.fsm.state == State.IDLE:
            return
        if not window.is_poe_active():
            return
        self._ui_open = not self._ui_open
        self.executor.submit(self.fsm.set_ui_open(self._ui_open))
        self._flog.info("UI %s：FSM %s", "打开" if self._ui_open else "关闭",
                        "挂起" if self._ui_open else "恢复")
        self.log("刷图助手：UI 打开，已挂起" if self._ui_open else "刷图助手：UI 关闭，已恢复")

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
            # COMBOS 禁用时自动重试加载（F5 标定后无需重启助手）
            if self.q6_retry_due(now):
                self._q6_next_retry = now + Q6_RETRY_INTERVAL_S
                self.reload_q6(quiet=True)
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
            if frame is not None and self.fsm.state != State.IDLE and not self._ui_open:
                signals = self._detect(frame, resolution, loot_cfg)
                self._log_q_throttled(signals, now)
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
        """单帧检测：光标附近黑框 + Q 层数（无坐标/无掩模时禁用）。"""
        cursor = self._cursor_pos()
        loot_center = None
        if cursor is not None:
            try:
                loot_center = loot.find_loot_box(frame, cursor[0], cursor[1], loot_cfg, resolution)
            except Exception as exc:  # noqa: BLE001 单帧失败不中断仲裁
                logger.warning("拾取检测异常: %s", exc)
        q_full = False
        self._last_q_conf = None
        if self._q_mask is not None:
            # ROI 每帧取：F5 重新标定后即时生效
            roi_box = self.settings.combat.q6_roi
            origin = window.client_origin()
            if roi_box is not None and origin is not None:
                try:
                    x1, y1, x2, y2 = qstack.q6_roi_screen(origin.x, origin.y, roi_box)
                    roi = frame[y1:y2, x1:x2]
                    conf = qstack.mask_confidence(qstack.binarize_roi(roi), self._q_mask)
                    self._last_q_conf = conf
                    q_full = conf >= float(self.config["combos"]["match_confidence"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Q 层数检测异常: %s", exc)
        return FrameSignals(loot_center=loot_center, q_full=q_full)

    # ============================================================
    # 文件日志打点（节流，避免拖垮 60fps 循环）
    # ============================================================
    def _log_q_throttled(self, signals: FrameSignals, now: float) -> None:
        """Q 检测节流日志：每 2 秒一次当前匹配度与 ROI 状态；达阈值边沿额外记一条。"""
        threshold = float(self.config["combos"]["match_confidence"])
        if signals.q_full and not self._q_full_prev:
            self._flog.info(
                "Q 达阈值：匹配度 %.3f ≥ %.2f，ROI %s",
                self._last_q_conf or 0.0, threshold, self.settings.combat.q6_roi,
            )
        self._q_full_prev = signals.q_full
        if now < self._q6_next_log:
            return
        self._q6_next_log = now + _Q6_LOG_INTERVAL_S
        if self._q_mask is None:
            self._flog.info("Q 检测禁用：等待标定/模板（每 %.0f 秒自动重试）", Q6_RETRY_INTERVAL_S)
        else:
            self._flog.info(
                "Q 匹配度 %.3f（阈值 %.2f，%s），ROI %s",
                self._last_q_conf if self._last_q_conf is not None else -1.0,
                threshold, "满" if signals.q_full else "未满", self.settings.combat.q6_roi,
            )

    def _log_step(
        self,
        prev: State,
        signals: FrameSignals,
        actions: list[Action],
        blacklist_before: int,
    ) -> None:
        """FSM 转移与动作链日志（仅状态变化或黑名单变化时写）。"""
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
        if curr == State.COMBOS:
            return f"Q 满（匹配度 {self._last_q_conf:.3f}）" if self._last_q_conf is not None else "Q 满"
        if prev == State.LOOTING and curr == State.MOVING:
            return "寻路超时进黑名单" if blacklisted else "拾取成功（黑框消失）"
        if prev == State.COMBOS and curr == State.MOVING:
            return "连招完成恢复移动"
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
