#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pytest 共享夹具：把配置文件重定向到临时目录。"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

from poe2_tools.config import settings as settings_module


@pytest.fixture(autouse=True)
def temp_ini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把配置文件重定向到临时目录，避免污染真实配置。"""
    ini = tmp_path / "poe2_tools.ini"
    monkeypatch.setattr(settings_module, "INI_PATH", ini)
    return ini


def write_ini(ini: Path, section: str, values: dict[str, str]) -> None:
    """以 UTF-8 写入测试用 ini 文件（追加到已有内容）。"""
    config = configparser.ConfigParser()
    config.optionxform = str
    if ini.exists():
        with open(ini, "r", encoding="utf-8") as f:
            config.read_file(f)
    if not config.has_section(section):
        config.add_section(section)
    for key, value in values.items():
        config.set(section, key, value)
    with open(ini, "w", encoding="utf-8") as f:
        config.write(f)
