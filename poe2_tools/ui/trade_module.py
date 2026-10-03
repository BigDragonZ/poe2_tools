#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易模块：通货市场比例抓取（内嵌 Notebook 四子页）。

- 「默认通货」：抓取三种默认通货（崇高/混沌/神圣）的两两市场比例，
  同步到 Web「交易 → 默认」页（最佳兑换路径与金币折算由页面计算展示，
  本页不展示结果；同方向自动记录每次只保留最近一次）
- 「指定」：输入指定通货游戏内英文全名，抓取其与三种默认通货的市场比例，
  同步到 Web「交易 → 指定」页参与计算
- 「自动」：预留（定时自动抓取，暂未开放；输出对应 Web「交易 → 自动」页）
- 「比例测试」：A/B 双向抓取测试入口与挂单结果展示（调试/标定核对用）

抓取编排逻辑在 modules/market/exchange.py，底层抓取在 modules/market/scanner.py，
本页只负责展示与触发（工作线程执行，结果经 after 回主线程）。
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from poe2_tools.config.settings import Settings
from poe2_tools.modules.market.exchange import (
    CATEGORY_LABELS,
    ExchangeScanRunner,
    custom_pairs,
    default_pairs,
)
from poe2_tools.modules.market.scanner import CurrencyTradeScanner

HELP_TEXT = (
    "使用：先在「研发 → 开发」页标定市场坐标（point1~5 = 我需要的/我拥有的/搜索框/"
    "市场比率按键/搜索结果首项，range3 = 结果面板），游戏内打开交易市场界面后按对应"
    "启动热键（或点页面按钮）开始抓取。\n"
    "抓取结果按类别同步到 Web 交易菜单对应页面（默认通货→交易·默认，指定→交易·指定）"
    "展示并计算最佳兑换比例，每次只保留最近一次；"
    "抓取期间请勿操作键鼠；F12 可随时急停释放按键。"
)

DEFAULT_HELP = (
    "抓取三种默认通货（崇高石 / 混沌石 / 神圣石）两两之间的市场比例（3 对 × 双向），"
    "同步到 Web「交易 → 默认」页计算最佳兑换比例（买边按 Currency Exchange 值折算金币"
    "消耗）；结果在该页展示，每次只保留最近一次。"
)

CUSTOM_HELP = (
    "输入指定通货的游戏内英文全名（如 Orb of Annulment），抓取它与三种默认通货的"
    "市场比例（3 对 × 双向），同步到 Web「交易 → 指定」页参与最佳兑换计算；"
    "结果在该页展示，每次只保留最近一次。"
)

_TREE_COLUMNS = ("rank", "ratio", "stock")
_TREE_HEADINGS = {"rank": "序号", "ratio": "比例", "stock": "库存"}
_TREE_WIDTHS = {"rank": 50, "ratio": 120, "stock": 100}


class TradeModule(ttk.Frame):
    """交易模块页：默认通货 / 指定 / 自动 / 比例测试 四子页。"""

    def __init__(
        self,
        master: tk.Misc,
        scanner: CurrencyTradeScanner,
        on_save: Callable[[], None] | None = None,
        logger: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(master, padding=8)
        self.scanner = scanner
        self._on_save = on_save
        self._logger = logger
        self._running = False

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self._build_default_tab()
        self._build_custom_tab()
        self._build_auto_tab()
        self._build_test_tab()

        ttk.Label(self, text=HELP_TEXT, foreground="#64748b", justify=tk.LEFT).pack(
            anchor=tk.W, pady=(8, 0)
        )

    # ============================================================
    # 子页构建
    # ============================================================
    def _build_default_tab(self) -> None:
        """「默认通货」子页：三种默认通货两两抓取 + 同步交易·默认页。"""
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="默认通货")

        frame = ttk.LabelFrame(
            tab, text="默认通货比例抓取（游戏内需已打开交易市场）", padding=6
        )
        frame.pack(fill=tk.X)
        ttk.Label(frame, text="启动热键:").grid(row=0, column=0, sticky=tk.W)
        self._hotkey_default_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._hotkey_default_var, width=10).grid(
            row=0, column=1, sticky=tk.W, padx=(4, 12)
        )
        if self._on_save is not None:
            ttk.Button(frame, text="保存配置", width=10, command=self._on_save).grid(
                row=0, column=2, padx=(0, 12)
            )
        self._default_button = ttk.Button(
            frame, text="开始抓取", width=10, command=self.trigger_default
        )
        self._default_button.grid(row=0, column=3, padx=(8, 12))
        ttk.Label(frame, text="状态:").grid(row=0, column=4, sticky=tk.W)
        self._default_state_var = tk.StringVar(value="空闲")
        ttk.Label(frame, textvariable=self._default_state_var, foreground="#22c55e").grid(
            row=0, column=5, sticky=tk.W, padx=(4, 0)
        )
        ttk.Label(
            tab, text=DEFAULT_HELP, foreground="#64748b", justify=tk.LEFT, wraplength=760
        ).pack(anchor=tk.W, pady=(10, 0))

    def _build_custom_tab(self) -> None:
        """「指定」子页：指定通货与三种默认通货抓取 + 同步交易·指定页。"""
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="指定")

        frame = ttk.LabelFrame(
            tab, text="指定通货比例抓取（游戏内需已打开交易市场）", padding=6
        )
        frame.pack(fill=tk.X)
        ttk.Label(frame, text="通货名称:").grid(row=0, column=0, sticky=tk.W)
        self._custom_currency_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._custom_currency_var, width=22).grid(
            row=0, column=1, sticky=tk.W, padx=(4, 12)
        )
        ttk.Label(frame, text="启动热键:").grid(row=0, column=2, sticky=tk.W)
        self._hotkey_custom_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._hotkey_custom_var, width=10).grid(
            row=0, column=3, sticky=tk.W, padx=(4, 12)
        )
        if self._on_save is not None:
            ttk.Button(frame, text="保存配置", width=10, command=self._on_save).grid(
                row=0, column=4, padx=(0, 12)
            )
        self._custom_button = ttk.Button(
            frame, text="开始抓取", width=10, command=self.trigger_custom
        )
        self._custom_button.grid(row=0, column=5, padx=(8, 12))
        ttk.Label(frame, text="状态:").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        self._custom_state_var = tk.StringVar(value="空闲")
        ttk.Label(frame, textvariable=self._custom_state_var, foreground="#22c55e").grid(
            row=1, column=1, columnspan=5, sticky=tk.W, padx=(4, 0), pady=(6, 0)
        )
        ttk.Label(
            tab, text=CUSTOM_HELP, foreground="#64748b", justify=tk.LEFT, wraplength=760
        ).pack(anchor=tk.W, pady=(10, 0))

    def _build_auto_tab(self) -> None:
        """「自动」子页：预留。"""
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="自动")
        ttk.Label(
            tab,
            text="暂未开放（预留：定时自动抓取默认/指定通货比例并同步 Web「交易 → 自动」页）",
            foreground="#64748b",
        ).pack(anchor=tk.W, pady=(4, 0))

    def _build_test_tab(self) -> None:
        """「比例测试」子页：A/B 双向抓取测试与挂单结果展示。"""
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="比例测试")

        frame = ttk.LabelFrame(tab, text="通货市场比例抓取（游戏内需已打开交易市场）", padding=6)
        frame.pack(fill=tk.X)

        ttk.Label(frame, text="通货 A:").grid(row=0, column=0, sticky=tk.W)
        self._currency_a_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._currency_a_var, width=18).grid(
            row=0, column=1, sticky=tk.W, padx=(4, 12)
        )
        ttk.Label(frame, text="通货 B:").grid(row=0, column=2, sticky=tk.W)
        self._currency_b_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._currency_b_var, width=18).grid(
            row=0, column=3, sticky=tk.W, padx=(4, 12)
        )
        ttk.Label(frame, text="启动热键:").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        self._hotkey_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._hotkey_var, width=10).grid(
            row=1, column=1, sticky=tk.W, padx=(4, 12), pady=(6, 0)
        )
        if self._on_save is not None:
            ttk.Button(frame, text="保存配置", width=10, command=self._on_save).grid(
                row=1, column=2, padx=(0, 12), pady=(6, 0)
            )
        self._test_button = ttk.Button(frame, text="测试抓取", width=10, command=self.trigger_test)
        self._test_button.grid(row=1, column=3, padx=(8, 12), pady=(6, 0))
        ttk.Label(frame, text="状态:").grid(row=1, column=4, sticky=tk.W, pady=(6, 0))
        self._state_var = tk.StringVar(value="空闲")
        ttk.Label(frame, textvariable=self._state_var, foreground="#22c55e").grid(
            row=1, column=5, columnspan=2, sticky=tk.W, padx=(4, 0), pady=(6, 0)
        )

        # 结果区：两个方向并排
        result_frame = ttk.Frame(tab)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self._tree_b2a = self._build_result_tree(result_frame, "B → A（付出 B 换取 A）", tk.LEFT)
        self._tree_a2b = self._build_result_tree(result_frame, "A → B（付出 A 换取 B）", tk.RIGHT)

    def _build_result_tree(self, master: tk.Misc, title: str, side: str) -> ttk.Treeview:
        """构建一个方向的结果表格（序号/比例/库存）。"""
        frame = ttk.LabelFrame(master, text=title, padding=4)
        frame.pack(side=side, fill=tk.BOTH, expand=True, padx=(0, 4) if side == tk.LEFT else (4, 0))
        tree = ttk.Treeview(frame, columns=_TREE_COLUMNS, show="headings", height=10)
        for col in _TREE_COLUMNS:
            tree.heading(col, text=_TREE_HEADINGS[col])
            tree.column(col, width=_TREE_WIDTHS[col], anchor=tk.CENTER)
        tree.pack(fill=tk.BOTH, expand=True)
        return tree

    # ============================================================
    # 配置同步
    # ============================================================
    def load_from(self, settings: Settings) -> None:
        """把配置载入控件。"""
        self._currency_a_var.set(settings.market_scan.currency_a)
        self._currency_b_var.set(settings.market_scan.currency_b)
        self._hotkey_var.set(settings.market_scan.hotkey)
        self._hotkey_default_var.set(settings.market_scan.hotkey_default)
        self._hotkey_custom_var.set(settings.market_scan.hotkey_custom)
        self._custom_currency_var.set(settings.market_scan.custom_currency)

    def sync_to(self, settings: Settings) -> None:
        """把控件值同步回配置。"""
        a = self._currency_a_var.get().strip()
        b = self._currency_b_var.get().strip()
        if a:
            settings.market_scan.currency_a = a
        if b:
            settings.market_scan.currency_b = b
        hotkey = self._hotkey_var.get().strip().lower()
        if hotkey:
            settings.market_scan.hotkey = hotkey
        hotkey_default = self._hotkey_default_var.get().strip().lower()
        if hotkey_default:
            settings.market_scan.hotkey_default = hotkey_default
        hotkey_custom = self._hotkey_custom_var.get().strip().lower()
        if hotkey_custom:
            settings.market_scan.hotkey_custom = hotkey_custom
        settings.market_scan.custom_currency = self._custom_currency_var.get().strip()

    # ============================================================
    # 默认/指定批量抓取（工作线程执行，进度经 after 回主线程）
    # ============================================================
    def trigger_default(self) -> None:
        """「默认通货」按钮 / 启动热键入口（主线程调用）。"""
        self._trigger_batch(
            default_pairs(), "default", self._default_state_var, self._default_button
        )

    def trigger_custom(self) -> None:
        """「指定」按钮 / 启动热键入口（主线程调用）：校验名称后抓取。"""
        name = self._custom_currency_var.get().strip()
        if not name:
            self._custom_state_var.set("请填写指定通货名称")
            return
        self._trigger_batch(
            custom_pairs(name), "custom", self._custom_state_var, self._custom_button
        )

    def _trigger_batch(
        self,
        pairs: list,
        category: str,
        state_var: tk.StringVar,
        button: ttk.Button,
    ) -> None:
        """启动一次批量抓取（运行中重复触发直接忽略）。"""
        if self._running:
            return
        self._running = True
        button.config(state=tk.DISABLED)
        state_var.set(f"准备抓取 {len(pairs)} 对通货…")
        threading.Thread(
            target=self._batch_worker,
            args=(pairs, category, state_var, button),
            daemon=True,
        ).start()

    def _batch_worker(
        self,
        pairs: list,
        category: str,
        state_var: tk.StringVar,
        button: ttk.Button,
    ) -> None:
        """工作线程：逐对抓取并发布，进度/结果经 after 回主线程。"""
        runner = ExchangeScanRunner(self.scanner, logger=self._logger)

        def progress(message: str) -> None:
            self.after(0, lambda: state_var.set(message))

        try:
            summary = runner.run(pairs, category=category, progress=progress)
        except Exception as exc:
            self.after(0, lambda: self._batch_done(state_var, button, None, str(exc)))
            return
        self.after(0, lambda: self._batch_done(state_var, button, summary, None))

    def _batch_done(
        self,
        state_var: tk.StringVar,
        button: ttk.Button,
        summary: dict | None,
        error: str | None,
    ) -> None:
        """渲染批量抓取结论（主线程）。"""
        if error is not None:
            state_var.set(f"失败:{error}")
        elif summary is not None:
            page_label = CATEGORY_LABELS.get(summary["category"], summary["category"])
            text = (
                f"完成：已同步 {summary['published']} 条比例到交易·{page_label}页"
                f"（{summary['pairs']} 对）"
            )
            if summary["errors"]:
                text += f"；{len(summary['errors'])} 对失败（详见日志）"
            if summary["published"] == 0 and not summary["errors"]:
                text = "完成：未抓取到可用比例（详见日志）"
            state_var.set(text)
        self._running = False
        button.config(state=tk.NORMAL)

    # ============================================================
    # 测试抓取（工作线程执行，结果回主线程渲染）
    # ============================================================
    def trigger_test(self) -> None:
        """「测试抓取」按钮 / 启动热键入口（主线程调用）：校验输入后在工作线程执行 scan。"""
        if self._running:
            return
        currency_a = self._currency_a_var.get().strip()
        currency_b = self._currency_b_var.get().strip()
        if not currency_a or not currency_b:
            self._state_var.set("请填写通货 A 与 B")
            return
        self._running = True
        self._test_button.config(state=tk.DISABLED)
        self._state_var.set(f"抓取中：{currency_a} ↔ {currency_b}")
        threading.Thread(
            target=self._scan_worker, args=(currency_a, currency_b), daemon=True
        ).start()

    def _scan_worker(self, currency_a: str, currency_b: str) -> None:
        """工作线程：执行抓取，结果经 after 回主线程。"""
        try:
            result = self.scanner.scan(currency_a, currency_b)
        except Exception as exc:
            self.after(0, lambda: self._show_error(str(exc)))
            return
        self.after(0, lambda: self._show_result(result))

    def _show_result(self, result: dict) -> None:
        """渲染双向结果并弹出完成提示（主线程）。"""
        b_to_a = result.get("b_to_a", [])
        a_to_b = result.get("a_to_b", [])
        self._fill_tree(self._tree_b2a, b_to_a)
        self._fill_tree(self._tree_a2b, a_to_b)
        pair = result.get("pair", "")
        self._state_var.set(f"完成：{pair}")
        self._finish()
        messagebox.showinfo(
            "市场抓取",
            f"处理完成：{pair}\nB → A：{len(b_to_a)} 条挂单\nA → B：{len(a_to_b)} 条挂单",
        )

    def _show_error(self, message: str) -> None:
        """渲染失败原因（主线程）。"""
        self._fill_tree(self._tree_b2a, [])
        self._fill_tree(self._tree_a2b, [])
        self._state_var.set(f"失败：{message}")
        self._finish()

    def _finish(self) -> None:
        self._running = False
        self._test_button.config(state=tk.NORMAL)

    @staticmethod
    def _fill_tree(tree: ttk.Treeview, rows: list[dict]) -> None:
        """清空并填充结果表格；空列表显示「无可用交易」占位行。"""
        tree.delete(*tree.get_children())
        if not rows:
            tree.insert("", tk.END, values=("-", "无可用交易", "-"))
            return
        for row in rows:
            stock = row.get("stock")
            tree.insert(
                "", tk.END,
                values=(row.get("rank"), row.get("ratio"), stock if stock is not None else "-"),
            )
