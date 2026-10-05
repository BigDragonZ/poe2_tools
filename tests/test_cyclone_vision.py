#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旋风视觉单元测试：真实样本 fixtures 的数字分类（白/暗双态）与生命文本解析。

fixtures 由 tools.extract_fixtures 从 temp/ 监控样本 sheet 提取（入库），
含白字 0-6、E 白字 2/3、E 暗字 2/3、无数字（药瓶图标）样本，
以及模板掩模副本（templates/ 子目录，与运行时模板同内容）。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import pytest

from poe2_tools.modules.cyclone import vision

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cyclone"
TEMPLATE_DIR = FIXTURE_DIR / "templates"


@pytest.fixture(scope="module")
def library() -> vision.TemplateLibrary:
    lib = vision.load_templates(TEMPLATE_DIR)
    assert sorted(lib.white) == [0, 1, 2, 3, 4, 5, 6]
    assert sorted(lib.dark) == [2, 3]
    return lib


def load(name: str):
    img = cv2.imread(str(FIXTURE_DIR / name))
    assert img is not None, f"fixture 缺失: {name}"
    return img


# ============================================================
# 白字分类（Q 0-6 全量 + E 白字 2/3）
# ============================================================
@pytest.mark.parametrize("digit", range(7))
def test_classify_white_q_digits(library, digit):
    result, state, conf = vision.classify_digit(load(f"q_white_{digit}.png"), library)
    assert result == digit
    assert state == vision.DigitState.WHITE
    assert conf >= vision.DEFAULT_MATCH_CONFIDENCE


@pytest.mark.parametrize("digit", [2, 3])
def test_classify_white_e_digits(library, digit):
    """E 白字与 Q 同字形：用 Q 派生的白字模板库应能正确分类。"""
    result, state, _conf = vision.classify_digit(load(f"e_white_{digit}.png"), library)
    assert result == digit
    assert state == vision.DigitState.WHITE


# ============================================================
# 暗字分类（E 暗色描边 2/3）
# ============================================================
@pytest.mark.parametrize("digit", [2, 3])
def test_classify_dark_e_digits(library, digit):
    result, state, conf = vision.classify_digit(load(f"e_dark_{digit}.png"), library)
    assert result == digit
    assert state == vision.DigitState.DARK
    assert conf >= vision.DEFAULT_MATCH_CONFIDENCE


def test_dark_digit_not_misread_as_white(library):
    """暗字不应落入白字态（双态区分）。"""
    _result, state, _conf = vision.classify_digit(load("e_dark_3.png"), library)
    assert state == vision.DigitState.DARK


# ============================================================
# 无数字与缩放回退
# ============================================================
def test_no_digit_returns_none(library):
    """药瓶图标（无数字）不应误识别。"""
    result, state, _conf = vision.classify_digit(load("e_nodigit_20.png"), library)
    assert result is None
    assert state is None


@pytest.mark.parametrize(
    "name,expected_digit,expected_state",
    [("q_white_6.png", 6, vision.DigitState.WHITE), ("e_dark_2.png", 2, vision.DigitState.DARK)],
)
def test_classify_at_runtime_scale(library, name, expected_digit, expected_state):
    """运行时为 28×30 小 ROI：缩放到运行尺度后分类仍正确。"""
    img = load(name)
    small = cv2.resize(img, (28, 30), interpolation=cv2.INTER_AREA)
    result, state, _conf = vision.classify_digit(small, library)
    assert result == expected_digit
    assert state == expected_state


def test_classify_empty_inputs(library):
    assert vision.classify_digit(None, library) == (None, None, 0.0)
    empty = vision.TemplateLibrary()
    assert vision.classify_digit(load("q_white_3.png"), empty) == (None, None, 0.0)


# ============================================================
# 生命数值文本解析
# ============================================================
@pytest.mark.parametrize(
    "text,expected",
    [
        ("1234/5678", (1234, 5678)),
        ("1,234/5,678", (1234, 5678)),
        ("1234 / 5678", (1234, 5678)),
        ("1 234/5 678", (1234, 5678)),
        ("1.234/5.678", (1234, 5678)),  # OCR 把逗号识别成句点
        ("1234|5678", (1234, 5678)),    # 分隔符误识别为竖线
        ("1234l5678", (1234, 5678)),    # 分隔符误识别为字母 l
        ("生命 1234/5678", (1234, 5678)),  # 前缀杂文本
        ("0/5678", (0, 5678)),
    ],
)
def test_parse_life_text_valid(text, expected):
    assert vision.parse_life_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "1234",        # 无分隔符
        "abc/def",     # 无数字
        "1234/0",      # 最大值为 0
        "生命值",       # 无数字
        "/5678",       # 缺当前值
    ],
)
def test_parse_life_text_invalid(text):
    assert vision.parse_life_text(text) is None
