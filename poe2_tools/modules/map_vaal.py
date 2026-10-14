#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
瓦地图（仓库批量）：取图 → 打造满 6 词 → 瓦前检查 → 盲点瓦尔 → 分类读图 → 分流存回。

流程（热键触发，触发前需手动打开仓库界面）：
1. 取图：切到仓库「Map」页，先把背包里未鉴定的地图移回仓库（未鉴定读不到词缀、
   不能打造）；点目标阶级按钮（默认 XV）→ 点回第 1 页从头开始；每页先截图做
   OpenCV 占用检测，无地图的页直接跳过，只对有物品的格子悬停 + Ctrl+C 读文本
   （剪贴板哨兵判空）；非已汙染且词缀数 < 6 的地图 Ctrl+左键移入背包并计数
   （背包最左列为保留列，取满 行×列 即停，默认 5×11=55）；
   取完后校验格子已空，未空说明背包已满，停止取图
2. 打造：切到「通货」页，逐张读状态自适应——普通/魔法 → 点金石（固定出 4 词），
   稀有未满 6 词 → 崇高石逐次补满；每次应用后复读校验，同一货币连续应用无变化
   则判定失败并跳过。本阶段不做瓦尔
3. 瓦前检查：快速重读背包全部地图，不满 6 词的补满（非稀有先点金再崇高），
   仍不满 6 词的标记跳过（不瓦未满 6 词的地图）
4. 瓦尔：对检查通过的格子盲点瓦尔（右键瓦尔 + 左键应用，不复读），
   间隔兜底 500ms 避免腐化动画漏点
5. 分类读图：每张瓦过的图读一次，解析阶级 / 词缀数 / 物品稀有度+怪物效能
6. 分流存回（按优先级）：T16 → Map 仓 Ctrl+左键自动归 XVI 页；
   物品稀有度+怪物效能 ≥ 阈值（默认 100）→「100 地图」仓 Ctrl+Shift+左键强存；
   8 词 → 高级地图仓 Ctrl+Shift+左键强存；其他 → Map 仓 Ctrl+左键自动归页

坐标约定：仓库界面布局走 [StashUI]（2026-10-13 当前布局实测默认值，可在 ini 调整；
标签列表纵坐标随选中页变化，tab 坐标以 Map 页选中状态实测为准）；
背包网格沿用既有约定 = 触发时鼠标位置为第 1 格中心 + 通用页格距/行列。
中断/失焦/F12 立即停止；货币点击间隔取通用页地图间隔（瓦尔阶段 500ms 兜底）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from poe2_tools.config.settings import (
    BATCH_JITTER,
    CURRENCY_NAMES,
    MAP_MIN_INTERVAL_MS,
    Point,
    Settings,
    StashUISettings,
    currency_coord,
)
from poe2_tools.core import input as core_input
from poe2_tools.core import window
from poe2_tools.core.timing import jitter_ms
from poe2_tools.modules.base import Logger, ToggleRunner
from poe2_tools.modules.stash.detect import stash_open

# 悬停读取节奏（毫秒）：移动后等 tooltip / Ctrl+C 后等剪贴板落地
HOVER_WAIT_MS = 350
COPY_WAIT_MS = 150
# 切页/切标签后的界面刷新等待
TAB_WAIT_MS = 900
# 单张地图最多应用货币次数（白图最坏情况 点金1+崇高5，兜住异常防死循环）
MAX_CRAFT_ATTEMPTS = 8
# 同一货币连续应用状态无变化的判定阈值（超过则判定该货币无效，放弃此图）
NO_CHANGE_LIMIT = 2
# 剪贴板哨兵：读取前写入，读后仍是它说明格子无物品（或复制失败）
CLIP_SENTINEL = "@@POE2_TOOLS_EMPTY@@"
# 格子占用检测（OpenCV 单帧截图逐格判定）：格心内侧半宽与亮度阈值
# （实测：空格≈8，有物品≥58，地图仓 medallion≈81）
CELL_OCCUPIED_THRESHOLD = 30
CELL_INNER_HALF = 22

WAYSTONE_KIND = "換界石"
CORRUPTED_MARK = "已汙染"
UNIDENTIFIED_MARK = "未鑑定"
MAX_AFFIXES = 6
# 瓦后分流：T16 直接存回 Map 仓；8 词存高级地图仓；数值达标存 100 地图仓
TIER_TOP = 16
ADVANCED_AFFIXES = 8

_AFFIX_RE = re.compile(r"^\{ (?:前綴|後綴) ", re.M)
_RARITY_RE = re.compile(r"^稀有度: (.+)$", re.M)
_TIER_RE = re.compile(r"換界石（階級 (\d+)）")
_ITEM_RARITY_RE = re.compile(r"^物品稀有度: \+(\d+)%", re.M)
_MONSTER_EFFECT_RE = re.compile(r"^怪物效能: \+(\d+)%", re.M)


# ============================================================
# 物品文本解析（纯逻辑）
# ============================================================
@dataclass
class WaystoneInfo:
    """换界石关键状态：稀有度原文 / 阶级 / 词缀数 / 是否已汙染 / 头部数值。"""

    rarity: str
    tier: int
    affixes: int
    corrupted: bool
    item_rarity_pct: int = 0  # 物品稀有度: +X%
    monster_effect_pct: int = 0  # 怪物效能: +X%

    @property
    def is_rare(self) -> bool:
        return self.rarity.startswith("稀有")


def parse_waystone(text: str | None) -> WaystoneInfo | None:
    """解析 Ctrl+C 物品文本；不是换界石返回 None。"""
    if not text or f"物品種類: {WAYSTONE_KIND}" not in text:
        return None
    rarity_match = _RARITY_RE.search(text)
    tier_match = _TIER_RE.search(text)
    item_rarity = _ITEM_RARITY_RE.search(text)
    monster_effect = _MONSTER_EFFECT_RE.search(text)
    return WaystoneInfo(
        rarity=rarity_match.group(1).strip() if rarity_match else "",
        tier=int(tier_match.group(1)) if tier_match else 0,
        affixes=len(_AFFIX_RE.findall(text)),
        corrupted=CORRUPTED_MARK in text,
        item_rarity_pct=int(item_rarity.group(1)) if item_rarity else 0,
        monster_effect_pct=int(monster_effect.group(1)) if monster_effect else 0,
    )


def needs_craft(info: WaystoneInfo) -> bool:
    """取图过滤条件：未汙染且词缀未满。"""
    return not info.corrupted and info.affixes < MAX_AFFIXES


def is_unidentified_waystone(text: str | None) -> bool:
    """是否为未鑑定的换界石（无法读取词缀，不能打造，需先从背包取出）。"""
    return bool(text) and WAYSTONE_KIND in text and UNIDENTIFIED_MARK in text


def craft_action(info: WaystoneInfo) -> str | None:
    """
    打造阶段按当前状态决定下一颗货币（不含瓦尔）：
    - 已汙染或稀有满 6 词 → None（不动）
    - 非稀有（普通/魔法）→ 点金石（固定出 4 词）
    - 稀有未满 6 词 → 崇高石
    """
    if info.corrupted:
        return None
    if not info.is_rare:
        return "alch"
    if info.affixes < MAX_AFFIXES:
        return "ex"
    return None


def vaal_ready(info: WaystoneInfo) -> bool:
    """瓦前检查通过条件：稀有、满 6 词、未汙染。"""
    return info.is_rare and info.affixes >= MAX_AFFIXES and not info.corrupted


def classify(info: WaystoneInfo, threshold: int) -> str:
    """
    瓦后分流（优先级从高到低）：
    - t16：阶级 16 → Map 仓自动归 XVI 页
    - map100：物品稀有度+怪物效能 ≥ threshold → 100 地图仓
    - advanced：8 词 → 高级地图仓
    - normal：其他 → Map 仓自动归页
    """
    if info.tier >= TIER_TOP:
        return "t16"
    if info.item_rarity_pct + info.monster_effect_pct >= threshold:
        return "map100"
    if info.affixes >= ADVANCED_AFFIXES:
        return "advanced"
    return "normal"


def occupied_cells_in_image(
    gray, origin: Point, cell: float, rows: int, cols: int
) -> set[tuple[int, int]]:
    """
    在网格区域的灰度图上逐格判定占用（纯逻辑，可单测）：
    格心内侧 CELL_INNER_HALF 区域平均亮度 > CELL_OCCUPIED_THRESHOLD 视为有物品。
    gray 为网格外接框的灰度图（左上角对应 origin - cell/2）。
    """
    import numpy as np  # noqa: PLC0415

    half = cell / 2
    result: set[tuple[int, int]] = set()
    for row in range(rows):
        for col in range(cols):
            cx = round(col * cell + half)  # 格心在截图内的偏移
            cy = round(row * cell + half)
            x1 = max(0, cx - CELL_INNER_HALF)
            y1 = max(0, cy - CELL_INNER_HALF)
            x2 = min(gray.shape[1], cx + CELL_INNER_HALF)
            y2 = min(gray.shape[0], cy + CELL_INNER_HALF)
            if x2 <= x1 or y2 <= y1:
                continue
            if float(np.mean(gray[y1:y2, x1:x2])) > CELL_OCCUPIED_THRESHOLD:
                result.add((row, col))
    return result


def tier_button(ui: StashUISettings, tier: int) -> Point:
    """地图阶级按钮中心（1~16：I-VIII 第 1 行，IX-XVI 第 2 行）。"""
    tier = max(1, min(16, tier))
    col = (tier - 1) % len(ui.tier_cols)
    row = 0 if tier <= len(ui.tier_cols) else 1
    return Point(ui.tier_cols[col], ui.tier_rows[row])


def page_button(ui: StashUISettings, page: int) -> Point:
    """仓库页绿色按钮中心（页码 1 起）。"""
    return Point(ui.page_x0 + (page - 1) * ui.page_pitch, ui.page_y)


# ============================================================
# 点击驱动层（可注入替身做单测）
# ============================================================
class MapVaalDriver:
    """真实驱动：客户区坐标点击 + 悬停 Ctrl+C 读物品文本 + 仓库开启检测。"""

    def __init__(self, interval_ms: int) -> None:
        self._interval_ms = interval_ms

    def sleep_ms(self, ms: int) -> None:
        """按毫秒等待，带 ±30% 随机抖动（保留人工操作痕迹）。"""
        import time  # noqa: PLC0415

        time.sleep(jitter_ms(ms, BATCH_JITTER) / 1000)

    def click_client(self, point: Point, button: str = "LButton") -> None:
        screen = window.client_to_screen(point)
        if screen is not None:
            core_input.click_at(screen.x, screen.y, button)

    def ctrl_click_client(self, point: Point) -> None:
        """Ctrl+左键（移动物品进/出仓库），Ctrl 在 finally 中释放。"""
        core_input.key_down("Ctrl")
        try:
            self.click_client(point)
        finally:
            core_input.key_up("Ctrl")

    def ctrl_shift_click_client(self, point: Point) -> None:
        """Ctrl+Shift+左键（强制存入当前打开的仓库页），修饰键在 finally 中释放。"""
        core_input.key_down("Ctrl")
        core_input.key_down("Shift")
        try:
            self.click_client(point)
        finally:
            core_input.key_up("Shift")
            core_input.key_up("Ctrl")

    def read_item(self, point: Point) -> str | None:
        """
        悬停指定格子并 Ctrl+C 读取物品文本。
        先写剪贴板哨兵：读后仍为哨兵说明该格无物品（或复制失败），返回 None。
        """
        from poe2_tools.core import clipboard  # noqa: PLC0415 懒导入

        screen = window.client_to_screen(point)
        if screen is None:
            return None
        try:
            clipboard.write_clipboard(CLIP_SENTINEL)
        except Exception:
            pass  # 哨兵写入失败时退化为直接读（可能拿到旧文本，由解析层过滤）
        core_input.move_to(screen.x, screen.y)
        self.sleep_ms(HOVER_WAIT_MS)
        core_input.key_down("Ctrl")
        try:
            core_input.press("c")
        finally:
            core_input.key_up("Ctrl")
        self.sleep_ms(COPY_WAIT_MS)
        try:
            text = clipboard.read_clipboard()
        except Exception:
            return None
        return None if text == CLIP_SENTINEL else text

    def stash_open(self) -> bool:
        """仓库界面是否打开（公共实现见 modules/stash/detect.py）。"""
        return stash_open()

    def occupied_cells(
        self, origin: Point, cell: float, rows: int, cols: int
    ) -> set[tuple[int, int]]:
        """一次截图 + OpenCV 逐格亮度判定网格占用，返回 {(row, col)}。

        用于跳过空格子：只对有物品的格子做悬停 Ctrl+C 读取，大幅减少读取次数；
        页面无任何占用时整页跳过。
        """
        import mss  # noqa: PLC0415 懒导入
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        client = window.client_origin()
        if client is None:
            return set()
        half = cell / 2
        left = client.x + round(origin.x - half)
        top = client.y + round(origin.y - half)
        width = round(cols * cell)
        height = round(rows * cell)
        with mss.MSS() as sct:
            shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
        frame = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        return occupied_cells_in_image(gray, origin, cell, rows, cols)


# ============================================================
# 任务主体
# ============================================================
class MapVaalRunner(ToggleRunner):
    """瓦地图（取图 → 打造满 6 词 → 瓦前检查 → 盲点瓦尔 → 分类分流存回）。"""

    name = "瓦地图"

    def __init__(self, settings: Settings, logger: Logger | None = None) -> None:
        super().__init__(settings, logger)
        self._driver: MapVaalDriver | None = None

    def missing_currencies(self) -> list[str]:
        """返回尚未标定坐标的流程货币（中文名），供启动前检查与界面提示。"""
        return [
            CURRENCY_NAMES[key]
            for key in ("alch", "ex", "vaal")
            if currency_coord(self.settings, key) is None
        ]

    def preflight(self) -> Point | None:
        if not window.is_poe_active():
            return None
        missing = self.missing_currencies()
        if missing:
            self.log(f"请先在「坐标」页标定「{missing[0]}」", "WARN")
            return None
        origin = self._check_common()
        if origin is None:
            return None
        driver = self._make_driver()
        if not driver.stash_open():
            self.log("未检测到仓库界面：请先打开仓库再启动瓦地图", "WARN")
            return None
        self._driver = driver
        tier = self.settings.general.map_vaal.tier
        self.log(f"瓦地图中（Map 页 T{tier} 取图 → 点金/崇高至 6 词 → 瓦尔 → 分流存回），再按一次停止")
        return origin

    def _make_driver(self) -> MapVaalDriver:
        return MapVaalDriver(self.settings.general.map_vaal.interval_ms)

    # --------------------------------------------------------
    # 主流程
    # --------------------------------------------------------
    def _work(self, origin: Point) -> None:
        assert self._driver is not None  # preflight 已创建
        driver = self._driver
        aborted = False
        try:
            pulled, aborted = self._pull_phase(driver, origin)
            if not aborted and pulled > 0:
                crafted, aborted = self._craft_phase(driver, origin)
                if not aborted and crafted > 0:
                    ready, aborted = self._check_phase(driver, origin)
                    if not aborted and ready:
                        self._vaal_phase(driver, ready)
                        results = self._classify_phase(driver, ready)
                        self._return_phase(driver, results)
                    elif not aborted:
                        self.log("瓦前检查：没有满 6 词的地图可瓦", "WARN")
                elif not aborted:
                    self.log("没有可打造的地图")
            elif not aborted:
                self.log("没有需要处理的地图（全部已汙染或已满 6 词）")
        finally:
            self._driver = None
        if aborted:
            self.log("瓦地图已中断：背包内剩余地图请自行处理", "WARN")

    # --------------------------------------------------------
    # 阶段一：从仓库 Map 页取图
    # --------------------------------------------------------
    def _pull_phase(self, driver: MapVaalDriver, origin: Point) -> tuple[int, bool]:
        """先取出背包未鉴定地图，再逐页筛选取图，返回 (取图数量, 是否中断)。

        点 Map 页后先做阶段零（未鉴定地图出包）；点阶级按钮后先点回第 1 页从头开始；
        每页先截图做 OpenCV 占用检测，无地图的页直接跳过；只读取有物品的格子。
        背包最左列为保留列，可用格子 = 通用页 行×列（默认 5×11=55），取满即停。
        """
        ui = self.settings.stash_ui
        interval = self.settings.general.map_vaal.interval_ms
        capacity = self.settings.general.sort.rows * self.settings.general.sort.cols
        driver.click_client(ui.tab_map)
        driver.sleep_ms(TAB_WAIT_MS)
        self._extract_unidentified(driver, origin)
        driver.click_client(tier_button(ui, self.settings.general.map_vaal.tier))
        driver.sleep_ms(TAB_WAIT_MS)
        driver.click_client(page_button(ui, 1))
        driver.sleep_ms(TAB_WAIT_MS)

        pulled = 0
        for page in range(1, ui.page_count + 1):
            if self._should_stop() or not window.is_poe_active():
                return pulled, True
            occupied = driver.occupied_cells(
                ui.stash_grid_origin, ui.stash_grid_cell,
                ui.stash_grid_rows, ui.stash_grid_cols,
            )
            if not occupied:
                self.log(f"第 {page} 页无地图，跳过")
            else:
                skipped_unidentified = 0
                for row, col in sorted(occupied):
                    if self._should_stop() or not window.is_poe_active():
                        return pulled, True
                    cell = Point(
                        ui.stash_grid_origin.x + col * ui.stash_grid_cell,
                        ui.stash_grid_origin.y + row * ui.stash_grid_cell,
                    )
                    text = driver.read_item(cell)
                    if is_unidentified_waystone(text):
                        skipped_unidentified += 1
                        continue
                    info = parse_waystone(text)
                    if info is None:
                        continue
                    if not needs_craft(info):
                        continue
                    if pulled >= capacity:
                        self.log(f"背包容量已满（{pulled}/{capacity}），停止取图")
                        return pulled, False
                    driver.ctrl_click_client(cell)
                    driver.sleep_ms(interval)
                    # 取图校验：格子仍未空说明背包已满，停止取图
                    if parse_waystone(driver.read_item(cell)) is not None:
                        self.log("背包已满，停止取图", "WARN")
                        return pulled, False
                    pulled += 1
                if skipped_unidentified:
                    self.log(f"第 {page} 页跳过 {skipped_unidentified} 张未鉴定地图")
            if page == ui.page_count:
                break
            driver.click_client(page_button(ui, page + 1))
            driver.sleep_ms(TAB_WAIT_MS)
        self.log(f"取图完成：共 {pulled}/{capacity} 张待瓦地图")
        return pulled, False

    def _extract_unidentified(self, driver: MapVaalDriver, origin: Point) -> int:
        """阶段零：取出背包里所有未鉴定的地图（Map 页打开时 Ctrl+左键自动归仓）。

        未鉴定地图读不到词缀、不能打造，留在背包只会占用容量，先移回仓库。
        """
        sort = self.settings.general.sort
        interval = self.settings.general.map_vaal.interval_ms
        occupied = driver.occupied_cells(origin, sort.cell_size, sort.rows, sort.cols)
        moved = 0
        for row, col in sorted(occupied):
            if self._should_stop() or not window.is_poe_active():
                break
            cell = Point(
                round(origin.x + col * sort.cell_size),
                round(origin.y + row * sort.cell_size),
            )
            text = driver.read_item(cell)
            if not is_unidentified_waystone(text):
                continue
            driver.ctrl_click_client(cell)
            driver.sleep_ms(interval)
            moved += 1
        if moved:
            self.log(f"已从背包取出 {moved} 张未鉴定地图回仓库")
        return moved

    # --------------------------------------------------------
    # 阶段二：背包内打造（点金/崇高补满 6 词，不做瓦尔）
    # --------------------------------------------------------
    def _craft_phase(self, driver: MapVaalDriver, origin: Point) -> tuple[int, bool]:
        """遍历背包逐张打造至稀有 6 词，返回 (打造成功数量, 是否中断)。"""
        ui = self.settings.stash_ui
        sort = self.settings.general.sort
        driver.click_client(ui.tab_currency)
        driver.sleep_ms(TAB_WAIT_MS)

        done = failed = 0
        occupied = driver.occupied_cells(origin, sort.cell_size, sort.rows, sort.cols)
        for row, col in sorted(occupied):
            if self._should_stop() or not window.is_poe_active():
                return done, True
            cell = Point(
                round(origin.x + col * sort.cell_size),
                round(origin.y + row * sort.cell_size),
            )
            text = driver.read_item(cell)
            if is_unidentified_waystone(text):
                self.log(f"({cell.x},{cell.y}) 未鉴定地图，跳过（未鉴定不能打造）", "WARN")
                continue
            info = parse_waystone(text)
            if info is None:
                continue
            if not needs_craft(info):
                done += 1  # 已滿 6 词未汙染：无需打造，计入可瓦
                continue
            final, aborted = self._top_up(driver, cell, info)
            if aborted:
                return done, True
            if final is not None and vaal_ready(final):
                done += 1
            else:
                failed += 1
        self.log(f"打造完成：{done} 张满 6 词" + (f"，{failed} 张失败" if failed else ""))
        return done, False

    def _top_up(
        self, driver: MapVaalDriver, cell: Point, info: WaystoneInfo
    ) -> tuple[WaystoneInfo | None, bool]:
        """
        单张地图打造循环（只点金/崇高，不瓦尔）：读状态 → 决定货币 → 应用 → 复读校验。
        返回 (最终状态, 是否中断)；最终状态为 None 表示读取失败或无法补满（放弃此图）。
        """
        interval = self.settings.general.map_vaal.interval_ms
        no_change: dict[str, int] = {}
        last_sig = (info.rarity, info.affixes, info.corrupted)
        for _ in range(MAX_CRAFT_ATTEMPTS):
            if self._should_stop() or not window.is_poe_active():
                return info, True
            action = craft_action(info)
            if action is None:
                return (info if not info.corrupted else None), False
            coord = currency_coord(self.settings, action)
            if coord is None:
                return None, False  # preflight 已校验，理论上不会到这里
            driver.click_client(coord, "RButton")  # 从货币堆拿起一颗
            driver.sleep_ms(interval)
            driver.click_client(cell)  # 应用到地图
            driver.sleep_ms(interval)
            new_info = parse_waystone(driver.read_item(cell))
            if new_info is None:
                self.log(f"({cell.x},{cell.y}) 读取失败，放弃此图", "WARN")
                return None, False
            sig = (new_info.rarity, new_info.affixes, new_info.corrupted)
            if sig == last_sig:
                no_change[action] = no_change.get(action, 0) + 1
                if no_change[action] >= NO_CHANGE_LIMIT:
                    self.log(
                        f"({cell.x},{cell.y}) {CURRENCY_NAMES[action]}连续应用无变化，放弃此图",
                        "WARN",
                    )
                    return None, False
            else:
                no_change.clear()
            last_sig = sig
            info = new_info
        self.log(f"({cell.x},{cell.y}) 打造次数超限，放弃此图", "WARN")
        return None, False

    # --------------------------------------------------------
    # 阶段三：瓦前检查（确保全部满 6 词再瓦）
    # --------------------------------------------------------
    def _check_phase(
        self, driver: MapVaalDriver, origin: Point
    ) -> tuple[list[Point], bool]:
        """快速重读背包全部地图：不满 6 词的补满（非稀有先点金），
        仍不满的跳过不瓦。返回 (可瓦格子列表, 是否中断)。"""
        sort = self.settings.general.sort
        ready: list[Point] = []
        topped = skipped = 0
        occupied = driver.occupied_cells(origin, sort.cell_size, sort.rows, sort.cols)
        for row, col in sorted(occupied):
            if self._should_stop() or not window.is_poe_active():
                return ready, True
            cell = Point(
                round(origin.x + col * sort.cell_size),
                round(origin.y + row * sort.cell_size),
            )
            info = parse_waystone(driver.read_item(cell))
            if info is None:
                continue
            if not vaal_ready(info):
                if info.corrupted:
                    continue  # 已汙染（理论上不会出现）：不动也不瓦
                final, aborted = self._top_up(driver, cell, info)
                if aborted:
                    return ready, True
                if final is None or not vaal_ready(final):
                    self.log(f"({cell.x},{cell.y}) 瓦前检查仍不满 6 词，跳过（不瓦）", "WARN")
                    skipped += 1
                    continue
                topped += 1
            ready.append(cell)
        self.log(
            f"瓦前检查完成：{len(ready)} 张可瓦"
            + (f"，补满 {topped} 张" if topped else "")
            + (f"，{skipped} 张不满 6 词跳过" if skipped else "")
        )
        return ready, False

    # --------------------------------------------------------
    # 阶段四：盲点瓦尔（与点金/崇高同节奏，不逐张复读）
    # --------------------------------------------------------
    def _vaal_phase(self, driver: MapVaalDriver, cells: list[Point]) -> None:
        """对检查通过的格子逐格盲点瓦尔：右键瓦尔 + 左键应用。"""
        interval = self.settings.general.map_vaal.interval_ms
        vaal_interval = max(interval, MAP_MIN_INTERVAL_MS.get("vaal", 0))
        coord = currency_coord(self.settings, "vaal")
        assert coord is not None  # preflight 已校验
        done = 0
        for cell in cells:
            if self._should_stop() or not window.is_poe_active():
                break
            driver.click_client(coord, "RButton")
            driver.sleep_ms(interval)
            driver.click_client(cell)
            driver.sleep_ms(vaal_interval)
            done += 1
        self.log(f"瓦尔完成：{done}/{len(cells)} 张")

    # --------------------------------------------------------
    # 阶段五：分类读图（瓦后每张读一次，取最终状态）
    # --------------------------------------------------------
    def _classify_phase(
        self, driver: MapVaalDriver, cells: list[Point]
    ) -> list[tuple[Point, WaystoneInfo]]:
        """逐格读取瓦后结果，返回 (格子, 最终状态) 列表；读取失败的按 normal 兜底。"""
        results: list[tuple[Point, WaystoneInfo]] = []
        for cell in cells:
            if self._should_stop() or not window.is_poe_active():
                break
            info = parse_waystone(driver.read_item(cell))
            if info is None:
                self.log(f"({cell.x},{cell.y}) 瓦后读取失败，按普通图存回", "WARN")
                info = WaystoneInfo(rarity="", tier=0, affixes=0, corrupted=False)
            results.append((cell, info))
        return results

    # --------------------------------------------------------
    # 阶段六：分流存回（T16 → ≥阈值 → 8 词 → 其他）
    # --------------------------------------------------------
    def _return_phase(
        self, driver: MapVaalDriver, items: list[tuple[Point, WaystoneInfo]]
    ) -> None:
        """按 classify 结果分四批存回：
        T16 与其他在 Map 仓 Ctrl+左键（自动归对应阶级页）；≥阈值与 8 词分别切
        100 地图仓 / 高级地图仓 Ctrl+Shift+左键强存。存取顺序按优先级。"""
        ui = self.settings.stash_ui
        interval = self.settings.general.map_vaal.interval_ms
        threshold = self.settings.general.map_vaal.value_threshold
        buckets: dict[str, list[Point]] = {"t16": [], "map100": [], "advanced": [], "normal": []}
        for cell, info in items:
            buckets[classify(info, threshold)].append(cell)

        moved: dict[str, int] = {}
        # 1. T16 → Map 仓自动归 XVI 页
        moved["t16"] = self._store_auto(driver, ui.tab_map, buckets["t16"])
        # 2. ≥阈值 → 100 地图仓强存
        moved["map100"] = self._store_force(driver, ui.tab_map100, buckets["map100"])
        # 3. 8 词 → 高级地图仓强存
        moved["advanced"] = self._store_force(driver, ui.tab_advanced_map, buckets["advanced"])
        # 4. 其他 → Map 仓自动归页
        moved["normal"] = self._store_auto(driver, ui.tab_map, buckets["normal"])
        self.log(
            f"存回完成：T16 {moved['t16']} 张，100 地图仓 {moved['map100']} 张，"
            f"高级地图仓 {moved['advanced']} 张，普通 {moved['normal']} 张"
        )

    def _store_auto(
        self, driver: MapVaalDriver, tab: Point, cells: list[Point]
    ) -> int:
        """切到指定仓标签后 Ctrl+左键逐格存（自动归页），返回成功点击数。"""
        if not cells:
            return 0
        interval = self.settings.general.map_vaal.interval_ms
        driver.click_client(tab)
        driver.sleep_ms(TAB_WAIT_MS)
        moved = 0
        for cell in cells:
            if self._should_stop() or not window.is_poe_active():
                break
            driver.ctrl_click_client(cell)
            driver.sleep_ms(interval)
            moved += 1
        return moved

    def _store_force(
        self, driver: MapVaalDriver, tab: Point, cells: list[Point]
    ) -> int:
        """切到指定仓标签后 Ctrl+Shift+左键逐格强存当前页，返回成功点击数。"""
        if not cells:
            return 0
        interval = self.settings.general.map_vaal.interval_ms
        driver.click_client(tab)
        driver.sleep_ms(TAB_WAIT_MS)
        moved = 0
        for cell in cells:
            if self._should_stop() or not window.is_poe_active():
                break
            driver.ctrl_shift_click_client(cell)
            driver.sleep_ms(interval)
            moved += 1
        return moved
