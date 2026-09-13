#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pytest 共享夹具：把配置文件重定向到临时目录。"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

from poe2_tools import common


@pytest.fixture(autouse=True)
def temp_ini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把配置文件重定向到临时目录，避免污染真实配置。"""
    ini = tmp_path / "poe2_tools.ini"
    monkeypatch.setattr(common, "INI_PATH", ini)
    return ini


def write_ini(ini: Path, section: str, values: dict[str, str]) -> None:
    """以 UTF-8 写入测试用 ini 文件。"""
    config = configparser.ConfigParser()
    config.optionxform = str
    config.add_section(section)
    for key, value in values.items():
        config.set(section, key, value)
    with open(ini, "w", encoding="utf-8") as f:
        config.write(f)
