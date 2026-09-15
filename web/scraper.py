"""抓取与解析 poe2db.tw 经济模块页面。

解析函数（parse_*）与网络请求（fetch_*）分离，便于单元测试。
"""

import re
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://poe2db.tw/tw/"
USER_AGENT = "poe2-economy-recorder/0.1 (+personal use)"
REQUEST_INTERVAL = 1.0  # 礼貌性限速：请求间隔 >= 1 秒
REQUEST_TIMEOUT = 30

# 14 个经济模块：slug -> 繁体名
MODULES = [
    ("Economy_Currency", "通貨"),
    ("Economy_Fragments", "碎片"),
    ("Economy_Ritual", "祭祀"),
    ("Economy_Essences", "精髓"),
    ("Economy_Breach", "裂痕聯盟"),
    ("Economy_Delirium", "譫妄異域"),
    ("Economy_Expedition", "死境探險"),
    ("Economy_Runes", "符文"),
    ("Economy_Soul_Cores", "靈魂核心"),
    ("Economy_Idols", "魔偶"),
    ("Economy_Uncut_Gems", "未切割的寶石"),
    ("Economy_Abyss", "深淵"),
    ("Economy_Gems", "寶石"),
    ("Economy_Atziris_Temple", "阿茲里的神廟"),
]
MODULE_SLUGS = [slug for slug, _ in MODULES]
MODULE_NAMES = dict(MODULES)

# 价格基准单位：神圣石
DIVINE_SLUG = "divine"
CHAOS_SLUG = "chaos"
# 神圣石在 Currency 模块中的 Wiki 名，用于提取混沌⇄神圣汇率
DIVINE_WIKI_SLUG = "Divine_Orb"


def _parse_number(text):
    """解析价格/数量文本，支持小数；失败返回 None。"""
    text = text.strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_price_cell(td):
    """解析 24h Value 列。

    格式：{ref数量} <a href="Economy_{参照slug}">图标</a> ⇄ {物品数量} <a>物品图标</a>
    语义：物品数量个该物品 = ref数量个参照货币。
    返回 (ref_amount, ref_currency, item_amount)，解析失败字段为 None。
    """
    anchors = td.find_all("a")
    texts = [t.strip() for t in td.find_all(string=True) if t.strip()]
    numbers = [_parse_number(t) for t in texts]
    numbers = [n for n in numbers if n is not None]
    ref_amount = numbers[0] if numbers else None
    item_amount = numbers[1] if len(numbers) > 1 else (1.0 if numbers else None)
    ref_currency = None
    if anchors:
        href = anchors[0].get("href", "")
        if href.startswith("Economy_"):
            ref_currency = href[len("Economy_"):]
    return ref_amount, ref_currency, item_amount


def parse_change_cell(td):
    """解析 Last 7 days 列，返回 (sparkline_d, change_color, change_7d_pct)。"""
    sparkline_d = None
    path = td.find("path")
    if path and path.get("d"):
        sparkline_d = path["d"]
    change_color = None
    change_pct = None
    span = td.find("span")
    if span:
        m = re.search(r"color:\s*(\w+)", span.get("style", ""))
        if m:
            change_color = m.group(1)
        m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", span.get_text())
        if m:
            change_pct = float(m.group(1))
    return sparkline_d, change_color, change_pct


def parse_module_row(tr):
    """解析单个物品行，返回 dict；非数据行返回 None。"""
    tds = tr.find_all("td")
    if len(tds) < 4:
        return None
    name_td, price_td, change_td, volume_td = tds[0], tds[1], tds[2], tds[3]

    item_anchor = None
    wiki_slug = None
    for a in name_td.find_all("a"):
        href = a.get("href", "")
        if href.startswith("Economy_") and item_anchor is None:
            item_anchor = a
        elif a.get_text(strip=True) == "Wiki":
            wiki_slug = href
    if item_anchor is None:
        return None

    slug = item_anchor["href"][len("Economy_"):]
    img = item_anchor.find("img")
    ref_amount, ref_currency, item_amount = parse_price_cell(price_td)
    sparkline_d, change_color, change_pct = parse_change_cell(change_td)
    volume = _parse_number(volume_td.get_text())

    return {
        "slug": slug,
        "name_zh": item_anchor.get_text(strip=True),
        "name_en": wiki_slug.replace("_", " ") if wiki_slug else None,
        "wiki_slug": wiki_slug,
        "icon_url": img["src"] if img and img.get("src") else None,
        "ref_amount": ref_amount,
        "ref_currency": ref_currency,
        "item_amount": item_amount,
        "sparkline_d": sparkline_d,
        "change_color": change_color,
        "change_7d_pct": change_pct,
        "volume_24h": int(volume) if volume is not None else None,
    }


def parse_module_cards(soup):
    """解析页面顶部的模块卡片列表，返回 [{slug, name_zh, icon_url}]。"""
    cards = []
    for a in soup.find_all("a", href=re.compile(r"^Economy_[A-Za-z_]+$")):
        classes = a.get("class") or []
        if "col" not in classes:
            continue
        img = a.find("img")
        cards.append({
            "slug": a["href"],
            "name_zh": a.get_text(strip=True),
            "icon_url": img["src"] if img and img.get("src") else None,
        })
    return cards


def parse_pagination_urls(soup, module_slug):
    """防御性分页支持：若页面出现 pagination 链接则返回需跟随的 URL 列表。"""
    urls = []
    for ul in soup.find_all("ul", class_="pagination"):
        for a in ul.find_all("a", href=True):
            href = a["href"]
            if module_slug in href:
                if href.startswith("http"):
                    urls.append(href)
                else:
                    urls.append(BASE_URL + href.lstrip("/"))
    return urls


def parse_module_page(html):
    """解析一个模块页面，返回 {"items": [...], "modules": [...], "pagination": [...]}。"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_=lambda c: c and "filters" in c.split())
    items = []
    if table:
        for tr in table.find_all("tr"):
            row = parse_module_row(tr)
            if row:
                items.append(row)
    return {
        "items": items,
        "modules": parse_module_cards(soup),
        "pagination": [],
    }


def extract_chaos_per_divine(items):
    """从 Currency 模块物品列表提取混沌⇄神圣汇率（1 神圣 = N 混沌）。

    找不到时返回 None。
    """
    for item in items:
        if item.get("wiki_slug") == DIVINE_WIKI_SLUG and item.get("ref_currency") == CHAOS_SLUG:
            ref = item.get("ref_amount")
            amt = item.get("item_amount")
            if ref and amt:
                return ref / amt
    return None


def compute_prices(ref_currency, ref_amount, item_amount, chaos_per_divine):
    """计算 price_divine / price_chaos。

    单价（参照货币）= ref数量 / 物品数量。
    参照 = divine → 直接为 price_divine；参照 = chaos → 除以汇率；
    其他参照 → None（仍保留原始字段）。无法换算时 price_chaos 为 None。
    """
    if ref_amount is None or not item_amount:
        return None, None
    unit_price = ref_amount / item_amount
    price_divine = None
    if ref_currency == DIVINE_SLUG:
        price_divine = unit_price
    elif ref_currency == CHAOS_SLUG and chaos_per_divine:
        price_divine = unit_price / chaos_per_divine
    price_chaos = None
    if price_divine is not None and chaos_per_divine:
        price_chaos = price_divine * chaos_per_divine
    elif ref_currency == CHAOS_SLUG:
        price_chaos = unit_price
    return price_divine, price_chaos


# ---------- 网络抓取 ----------

def _make_session():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_module_items(module_slug, session=None, interval=REQUEST_INTERVAL):
    """抓取一个模块（含防御性分页跟随），返回 (items, module_cards)。

    多页时按 interval 限速依次请求。
    """
    session = session or _make_session()
    visited = set()
    to_visit = [BASE_URL + module_slug]
    all_items = []
    module_cards = []
    while to_visit:
        url = to_visit.pop(0)
        if url in visited:
            continue
        visited.add(url)
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        parsed = parse_module_page(resp.text)
        all_items.extend(parsed["items"])
        if not module_cards:
            module_cards = parsed["modules"]
        for page_url in parse_pagination_urls(
            BeautifulSoup(resp.text, "html.parser"), module_slug
        ):
            if page_url not in visited and page_url not in to_visit:
                to_visit.append(page_url)
        if to_visit:
            time.sleep(interval)
    return all_items, module_cards


def fetch_all_modules(season_modules=None, interval=REQUEST_INTERVAL, progress_cb=None):
    """一次完整刷新抓全部 14 个模块，请求间隔 >= interval 秒。

    progress_cb(slug, index, total) 在每个模块完成后回调。
    返回 {module_slug: (items, module_cards)}。
    """
    session = _make_session()
    slugs = season_modules or MODULE_SLUGS
    results = {}
    for i, slug in enumerate(slugs):
        if i > 0:
            time.sleep(interval)
        results[slug] = fetch_module_items(slug, session=session, interval=interval)
        if progress_cb:
            progress_cb(slug, i + 1, len(slugs))
    return results
