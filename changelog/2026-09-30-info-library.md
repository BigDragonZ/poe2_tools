# 2026-09-30 信息库页面

## 需求

基于经济记录 Web 应用（0.5.5闪回赛季）新增「信息库」页面，数据库存储：物品中文名、英文名、所属模块、wiki 链接，并用爬虫从 wiki 页获取 `Currency Exchange` 值（游戏内市场交易时每单位物品消耗的金币，供后续交易分析使用）。涉及字段中英文都入库，方便后续全文检索。

## 变更

- **web/scraper.py**：新增 `parse_wiki_item_info(html)` 纯解析函数——从 wiki 物品页属性表提取 `Currency Exchange` 行金币值（如 `800 Gold` → 800.0，无该行则为 None），并从 `BaseType` 行按是否含 CJK 字符拆分中/英文名称；新增 `fetch_wiki_item_info(wiki_slug)` 网络函数（解析与网络分离，沿用既有模式）
- **web/db.py**：新增 `item_info` 表（item_id 唯一、wiki_url、gold_cost、wiki 端中/英文名、fetched_at）；新增 `upsert_item_info`、`list_wiki_scrape_targets`（missing/all 两种抓取清单）、`list_library_items`（联表 items/modules/item_info，名称优先取 wiki 端，支持对物品中/英文名、模块中/英文名、slug、wiki_slug 的 LIKE 模糊检索与模块过滤）
- **web/service.py**：新增信息库后台抓取编排 `_run_library_scrape` / `start_library_scrape`（mode=missing 只抓缺失、all 全部重抓），独立 `_LIBRARY_STATUS` 进度态（running/done/total/updated/current_item），限速 ≥1 秒/次，单物品失败不中断
- **web/app.py**：新增 `GET /api/library`（search/module_slug 检索）、`POST /api/library/refresh?mode=`（409 防重入）、`GET /api/library/status`
- **web/static/index.html**：新增 `LibraryPage` 组件（搜索防抖 300ms 走服务端检索、模块下拉过滤、金币列排序、抓取进度轮询），左侧边栏「工具」区新增「信息库」入口
- **tests/**：新增 fixture `wiki_divine_orb.html`（真实页面截取，Currency Exchange 800 Gold）、`wiki_uncut_gem.html`（无该行）；新增 `tests/test_library.py` 9 项单测（解析、存储覆盖、双语检索、模块过滤、抓取清单、编排含单物品失败容错）

## 验证

- `uv run pytest`：66 项全部通过（含信息库 9 项）
- 端到端：8322 端口实测实例，`POST /api/library/refresh?mode=missing` 对真实库 112 个物品逐个抓取 poe2db.tw wiki 页全部成功（神聖石 800、混沌石 160、高階混沌石 500、完美混沌石 1500 金币等入库）
- 桌面浏览器自动化：信息库页面渲染正常，中/英文名、模块、金币、Wiki 链接、抓取时间列齐全
