"""物品/模块图标本地化：下载外链图标到 web/static/icons/，前端引用本地路径。"""

import hashlib
import os
from pathlib import Path
from urllib.parse import urlparse

import requests

ICONS_DIR = Path(__file__).parent / "static" / "icons"
USER_AGENT = "poe2-economy-recorder/0.1 (+personal use)"
DOWNLOAD_TIMEOUT = 30


def icon_filename(url):
    """文件名 = URL 的 sha1 前 16 位 + 原扩展名（默认 .png）。"""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext not in (".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg"):
        ext = ".png"
    return digest + ext


def localize_icon(url, icons_dir=None, session=None):
    """下载图标到本地（已存在则跳过），返回前端可引用的路径 /icons/{文件名}。

    下载失败返回 None，调用方保留原外链或空值。
    """
    if not url:
        return None
    icons_dir = Path(icons_dir) if icons_dir else ICONS_DIR
    icons_dir.mkdir(parents=True, exist_ok=True)
    filename = icon_filename(url)
    target = icons_dir / filename
    if not target.exists():
        sess = session or requests.Session()
        sess.headers.update({"User-Agent": USER_AGENT})
        resp = sess.get(url, timeout=DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
        target.write_bytes(resp.content)
    return "/icons/" + filename
