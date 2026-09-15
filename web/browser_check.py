"""浏览器端自动化验证：用本机 Chrome 打开经济页面，逐项验证交互功能。

用法：先启动服务（uv run python -m web.app），再执行 uv run python -m web.browser_check。
截图输出到 temp/browser/，验证结果打印到 stdout，失败时退出码为 1。
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8321"
SHOTS_DIR = Path("temp/browser")
DB_PATH = Path(__file__).parent / "data" / "economy.db"

PASS = "PASS"
results = []


def check(name, ok, detail=""):
    """记录一项验证结果。"""
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {detail}" if detail else ""))


def cleanup_test_seasons():
    """删除以往运行遗留的测试赛季，保证幂等。"""
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM seasons WHERE name = 'UI自动化测试赛季'")
            conn.commit()


def main():
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_test_seasons()
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        # 1. 页面加载
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector(".topnav", timeout=10000)
        check("页面加载", True)

        # 2. 顶部一级菜单
        nav_texts = page.locator(".topnav .item").all_inner_texts()
        check("一级菜单（经济/策略/做装/开荒）", nav_texts == ["经济", "策略", "做装", "开荒"],
              str(nav_texts))

        # 3. 左侧三级菜单：14 个经济模块
        module_items = page.locator(".sidebar .half:not(.seasons) .side-item")
        check("经济模块数量=14", module_items.count() == 14, f"实际 {module_items.count()}")

        # 4. 赛季列表存在且默认选中
        season_items = page.locator(".sidebar .half.seasons .side-item")
        check("赛季列表非空", season_items.count() >= 1, f"实际 {season_items.count()}")
        active_season = page.locator(".sidebar .half.seasons .side-item.active")
        check("默认选中当前赛季", active_season.count() == 1,
              active_season.inner_text() if active_season.count() else "无选中")

        # 5. 切换到「通貨」模块，等待表格数据
        page.locator(".sidebar .half:not(.seasons) .side-item", has_text="通貨").first.click()
        page.wait_for_selector("table.eco tbody tr", timeout=10000)
        row_count = page.locator("table.eco tbody tr").count()
        check("通貨模块表格有数据", row_count > 0, f"{row_count} 行")
        page.screenshot(path=str(SHOTS_DIR / "01_currency_table.png"), full_page=True)

        # 6. 表格内容：图标、英文名、Wiki 链接、走势 SVG、涨跌幅
        check("物品图标使用本地缓存",
              page.locator("table.eco .name-main img").first.get_attribute("src").startswith("/icons/"))
        check("英文名称显示", page.locator("table.eco .name-en").first.inner_text() != "")
        wiki_href = page.locator("table.eco .wiki-link").first.get_attribute("href")
        check("Wiki 链接指向原站", wiki_href.startswith("https://poe2db.tw/tw/"), wiki_href)
        check("走势 SVG 重绘", page.locator("table.eco svg path").count() > 0,
              f"{page.locator('table.eco svg path').count()} 个")

        # 7. 搜索（中文与英文）
        search_box = page.locator("input[placeholder*='搜索']")
        search_box.fill("混沌")
        page.wait_for_timeout(300)
        zh_rows = page.locator("table.eco tbody tr").count()
        check("中文搜索「混沌」", 0 < zh_rows < row_count, f"{zh_rows}/{row_count} 行")
        search_box.fill("chaos")
        page.wait_for_timeout(300)
        en_rows = page.locator("table.eco tbody tr").count()
        check("英文搜索「chaos」", 0 < en_rows < row_count, f"{en_rows}/{row_count} 行")
        search_box.fill("")
        page.wait_for_timeout(300)

        # 8. 排序：点「Last 7 days」表头，验证涨跌幅降序
        page.locator("th.sortable", has_text="Last 7 days").click()
        page.wait_for_timeout(300)
        pcts = page.locator("table.eco tbody tr td:nth-child(3) span").all_inner_texts()
        nums = [float(t.replace("%", "").replace("+", "")) for t in pcts]
        check("按涨跌幅降序", nums == sorted(nums, reverse=True), str(nums[:5]))
        page.locator("th.sortable", has_text="Last 7 days").click()
        page.wait_for_timeout(300)
        pcts2 = page.locator("table.eco tbody tr td:nth-child(3) span").all_inner_texts()
        nums2 = [float(t.replace("%", "").replace("+", "")) for t in pcts2]
        check("再次点击切换为升序", nums2 == sorted(nums2), str(nums2[:5]))

        # 9. 按交易量排序
        page.locator("th.sortable", has_text="volume").click()
        page.wait_for_timeout(300)
        vols = page.locator("table.eco tbody tr td.vol").all_inner_texts()
        vol_nums = [int(v) for v in vols if v.strip().isdigit()]
        check("按交易量降序", vol_nums == sorted(vol_nums, reverse=True), str(vol_nums[:5]))

        # 10. 开服天数下拉
        day_options = page.locator(".toolbar select option").all_inner_texts()
        check("开服天数下拉有选项", len(day_options) >= 1, str(day_options))

        # 11. 定时配置面板：展开、修改、保存、通过 API 验证
        page.locator(".panel-title", has_text="定时抓取配置").click()
        page.wait_for_timeout(300)
        page.screenshot(path=str(SHOTS_DIR / "02_schedule_panel.png"))
        checkbox = page.locator(".panel input[type='checkbox']")
        was_enabled = checkbox.is_checked()
        checkbox.click()
        page.locator(".panel button", has_text="保存").click()
        page.wait_for_timeout(800)
        saved = page.evaluate("fetch('/api/schedule').then(r => r.json())")
        check("定时配置保存生效", saved["enabled"] == (not was_enabled),
              f"enabled={saved['enabled']}")
        checkbox.click()  # 还原
        page.locator(".panel button", has_text="保存").click()
        page.wait_for_timeout(500)

        # 12. 赛季管理：新增测试赛季 → 侧边栏出现 → 切换显示空态 → 切回
        page.locator(".panel-title", has_text="赛季管理").click()
        page.wait_for_timeout(300)
        page.locator(".panel input[type='text']").fill("UI自动化测试赛季")
        page.locator(".panel input[type='date']").fill("2026-09-01")
        page.locator(".panel button", has_text="新增赛季").click()
        page.wait_for_timeout(800)
        new_season = page.locator(".sidebar .half.seasons .side-item", has_text="UI自动化测试赛季")
        check("新增赛季出现在侧边栏", new_season.count() == 1)
        page.screenshot(path=str(SHOTS_DIR / "03_season_created.png"))
        new_season.first.click()
        page.wait_for_timeout(800)
        empty = page.locator(".empty")
        check("新赛季显示空态提示", empty.count() == 1 and "暂无数据" in empty.inner_text())
        # 切回原赛季
        page.locator(".sidebar .half.seasons .side-item").first.click()
        page.wait_for_selector("table.eco tbody tr", timeout=10000)
        check("切回原赛季数据恢复", page.locator("table.eco tbody tr").count() > 0)

        # 13. 刷新本模块按钮（真实抓取一次通货模块）
        page.locator("button.primary", has_text="刷新本模块").click()
        deadline = time.time() + 120
        final_status = ""
        while time.time() < deadline:
            st = page.evaluate("fetch('/api/refresh_status').then(r => r.json())")
            if not st.get("running"):
                final_status = st.get("error") or "ok"
                break
            time.sleep(2)
        page.wait_for_timeout(1500)
        check("刷新本模块完成", final_status == "ok", final_status)
        check("刷新后表格仍有数据", page.locator("table.eco tbody tr").count() > 0)
        page.screenshot(path=str(SHOTS_DIR / "04_after_refresh.png"), full_page=True)

        browser.close()

    # 14. 清理测试赛季
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("DELETE FROM seasons WHERE name = 'UI自动化测试赛季'")
        conn.commit()
        check("清理测试赛季", cur.rowcount == 1)

    # 15. 浏览器控制台无报错
    real_errors = [e for e in console_errors if "favicon" not in e]
    check("浏览器控制台无报错", not real_errors, str(real_errors[:3]))

    failed = [r for r in results if r[1] is not True]
    print(f"\n共 {len(results)} 项验证，失败 {len(failed)} 项。截图目录：{SHOTS_DIR}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
