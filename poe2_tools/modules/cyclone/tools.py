#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旋风模板提取工具：从监控样本 sheet 图提取数字模板与测试 fixtures。

样本布局（游戏内 4 倍放大监控录制拼接）：
- sheet1（temp/qe_watch_sheet.png）：5 列 × 8 行，单元格 CW×CH，
  Q 数字在 (col*CW+4, row*CH+20) 起 112×120，帧号→数字映射 Q_FRAME_TO_DIGIT；
  E 数字在单元格右半（x+116 起 112×120），全部白字 3
- sheet2（temp/qe_watch2_sheet.png）：10 列，同单元格几何；
  含暗色描边 E 数字样本（帧号见 DARK_E_SAMPLES，已人工核对）

产物：
- 模板：templates/cyclone/white_<d>.png、dark_<d>.png（归一化掩模，gitignore 不入库）
- 测试 fixtures：tests/fixtures/cyclone/*.png（原始 ROI 小图 + templates/ 掩模副本，入库）

用法：uv run python -m poe2_tools.modules.cyclone.tools
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

from poe2_tools.modules.cyclone import vision

# 仓库根目录（本文件在 poe2_tools/modules/cyclone/ 内，需向上四级）
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

SHEET1_PATH = REPO_ROOT / "temp" / "qe_watch_sheet.png"
SHEET2_PATH = REPO_ROOT / "temp" / "qe_watch2_sheet.png"
TEMPLATE_DIR = REPO_ROOT / "templates" / "cyclone"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "cyclone"

# 单元格几何（两张 sheet 一致）
CELL_W = 232
CELL_H = 142
ROI_W = 112
ROI_H = 120
Q_OFFSET_X = 4    # Q 数字在单元格左半
E_OFFSET_X = 116  # E 数字在单元格右半
ROI_OFFSET_Y = 20

SHEET1_COLS = 5
SHEET2_COLS = 10

# sheet1 帧号 → Q 白字数字（人工核对）
Q_FRAME_TO_DIGIT = {4: 0, 5: 1, 7: 2, 10: 3, 12: 4, 14: 5, 0: 6}

# sheet2 暗色 E 样本帧号 → 数字（人工核对 montage）
DARK_E_SAMPLES = {0: 2, 90: 3}
# sheet2 白字 E 样本帧号 → 数字（人工核对 montage）
WHITE_E_SAMPLES = {92: 2, 100: 3}
# sheet2 无数字（药瓶图标）样本帧号
NO_DIGIT_SAMPLES = [20]


def _cell(sheet: np.ndarray, idx: int, cols: int, offset_x: int) -> np.ndarray:
    """取 sheet 中第 idx 帧的数字 ROI（112×120）。"""
    x = (idx % cols) * CELL_W + offset_x
    y = (idx // cols) * CELL_H + ROI_OFFSET_Y
    return sheet[y : y + ROI_H, x : x + ROI_W]


def extract_templates(
    sheet1_path: Path | str = SHEET1_PATH,
    sheet2_path: Path | str = SHEET2_PATH,
    out_dir: Path | str = TEMPLATE_DIR,
) -> vision.TemplateLibrary:
    """从样本 sheet 提取双态模板库并写盘，返回模板库。"""
    sheet1 = cv2.imread(str(sheet1_path))
    sheet2 = cv2.imread(str(sheet2_path))
    if sheet1 is None:
        raise FileNotFoundError(f"样本 sheet 不存在: {sheet1_path}")
    if sheet2 is None:
        raise FileNotFoundError(f"样本 sheet 不存在: {sheet2_path}")

    library = vision.TemplateLibrary()
    for idx, digit in sorted(Q_FRAME_TO_DIGIT.items()):
        mask = vision.build_template(_cell(sheet1, idx, SHEET1_COLS, Q_OFFSET_X), vision.DigitState.WHITE)
        if mask is None:
            raise ValueError(f"sheet1 帧 {idx} 白字 {digit} 模板提取失败")
        library.white[digit] = mask
    for idx, digit in sorted(DARK_E_SAMPLES.items()):
        mask = vision.build_template(_cell(sheet2, idx, SHEET2_COLS, E_OFFSET_X), vision.DigitState.DARK)
        if mask is None:
            raise ValueError(f"sheet2 帧 {idx} 暗字 {digit} 模板提取失败")
        library.dark[digit] = mask

    vision.save_templates(library, out_dir)
    return library


def extract_fixtures(
    sheet1_path: Path | str = SHEET1_PATH,
    sheet2_path: Path | str = SHEET2_PATH,
    out_dir: Path | str = FIXTURE_DIR,
) -> Path:
    """
    提取单测 fixtures：原始数字 ROI 小图 + 模板掩模副本（templates/ 子目录）。
    fixtures 入库，使单测不依赖 gitignore 的 templates/。
    """
    sheet1 = cv2.imread(str(sheet1_path))
    sheet2 = cv2.imread(str(sheet2_path))
    if sheet1 is None or sheet2 is None:
        raise FileNotFoundError("样本 sheet 缺失，无法提取 fixtures")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for idx, digit in sorted(Q_FRAME_TO_DIGIT.items()):
        cv2.imwrite(str(out / f"q_white_{digit}.png"), _cell(sheet1, idx, SHEET1_COLS, Q_OFFSET_X))
    for idx, digit in sorted(WHITE_E_SAMPLES.items()):
        cv2.imwrite(str(out / f"e_white_{digit}.png"), _cell(sheet2, idx, SHEET2_COLS, E_OFFSET_X))
    for idx, digit in sorted(DARK_E_SAMPLES.items()):
        cv2.imwrite(str(out / f"e_dark_{digit}.png"), _cell(sheet2, idx, SHEET2_COLS, E_OFFSET_X))
    for idx in NO_DIGIT_SAMPLES:
        cv2.imwrite(str(out / f"e_nodigit_{idx}.png"), _cell(sheet2, idx, SHEET2_COLS, E_OFFSET_X))

    # 模板掩模副本（与运行时模板同内容）
    library = extract_templates(sheet1_path, sheet2_path, out / "templates")
    # 自校验：fixtures 逐一分类，全部命中才算成功
    failures: list[str] = []
    for file in sorted(out.glob("*.png")):
        img = cv2.imread(str(file))
        stem = file.stem
        if stem.startswith("e_nodigit"):
            digit, state, conf = vision.classify_digit(img, library)
            if digit is not None:
                failures.append(f"{stem}: 期望无数字，识别为 {state.value} {digit} ({conf:.2f})")
            continue
        _name, state_name, digit_text = stem.split("_")
        digit, state, conf = vision.classify_digit(img, library)
        if digit != int(digit_text) or state != vision.DigitState(state_name):
            failures.append(f"{stem}: 识别为 {state} {digit} ({conf:.2f})")
    if failures:
        raise ValueError("fixtures 自校验失败：" + "；".join(failures))
    return out


def main(argv: list[str] | None = None) -> int:
    """提取模板与 fixtures 并打印摘要。"""
    _ = argv or sys.argv[1:]
    library = extract_templates()
    print(f"模板已写入 {TEMPLATE_DIR}：白 {sorted(library.white)}，暗 {sorted(library.dark)}")
    fixture_dir = extract_fixtures()
    print(f"fixtures 已写入 {fixture_dir}（含自校验）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
