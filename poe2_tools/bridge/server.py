#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可选 WebSocket 适配器：把进程内事件总线暴露给外部前端。

默认关闭（[Bridge] Enabled=0），仅在本机回环地址监听。
- 下行：总线上的 log/status/event 消息原样广播给所有连接
- 上行：{"type": "command", "action": "...", "params": {...}}
  由注册的命令处理器路由到业务层

桌面工具主界面是 tkinter（进程内直连总线），本适配器面向
未来 Web 前端或外部控制端，非必需组件。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

from poe2_tools.bridge.bus import EventBus

logger = logging.getLogger(__name__)

CommandHandler = Callable[[dict], None]


class BridgeServer:
    """WebSocket 桥：总线消息广播 + 命令上行。"""

    def __init__(self, bus: EventBus, port: int, on_command: CommandHandler | None = None) -> None:
        self._bus = bus
        self._port = port
        self._on_command = on_command
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: uvicorn.Server | None = None
        self._clients: set[WebSocket] = set()
        self._clients_lock = threading.Lock()

    # --------------------------------------------------------
    # 生命周期
    # --------------------------------------------------------
    def start(self) -> None:
        """在后台线程启动 uvicorn（幂等）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True

    # --------------------------------------------------------
    # 内部
    # --------------------------------------------------------
    def _build_app(self) -> FastAPI:
        app = FastAPI(title="poe2_tools bridge", docs_url=None, redoc_url=None)

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket) -> None:
            await ws.accept()
            with self._clients_lock:
                self._clients.add(ws)
            try:
                while True:
                    raw = await ws.receive_text()
                    self._handle_message(raw)
            except WebSocketDisconnect:
                pass
            finally:
                with self._clients_lock:
                    self._clients.discard(ws)

        return app

    def _handle_message(self, raw: str) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return
        if message.get("type") == "command" and self._on_command is not None:
            try:
                self._on_command(message)
            except Exception as exc:
                logger.warning("命令处理失败: %s", exc)

    def _broadcast(self, message: dict) -> None:
        """总线回调：广播给全部连接（在 uvicorn 事件循环中执行）。"""
        if self._loop is None:
            return
        payload = json.dumps(message, ensure_ascii=False)
        with self._clients_lock:
            clients = list(self._clients)

        async def _send_all() -> None:
            for ws in clients:
                try:
                    await ws.send_text(payload)
                except Exception:
                    pass

        asyncio.run_coroutine_threadsafe(_send_all(), self._loop)

    def _serve(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._bus.subscribe(self._broadcast)
        config = uvicorn.Config(
            self._build_app(), host="127.0.0.1", port=self._port, log_level="warning"
        )
        self._server = uvicorn.Server(config)
        try:
            self._loop.run_until_complete(self._server.serve())
        finally:
            self._bus.unsubscribe(self._broadcast)
            self._loop.close()
            self._loop = None
