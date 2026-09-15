# 2026-09-14 POE2 经济记录 Web 应用

## 新增

- 全新独立 Web 应用「POE2 经济记录」，代码位于 `web/` 目录，与 tkinter 桌面工具互不影响
- 技术栈：FastAPI 后端（`uv run python -m web.app`，端口 8321）+ React 18 CDN 单页前端（无构建链）+ SQLite（标准库 sqlite3）
- `web/scraper.py`：抓取 poe2db.tw 14 个经济模块页面（请求间隔 ≥1 秒、带 User-Agent、防御性分页跟随），解析器与网络分离
- `web/db.py`：SQLite schema（seasons / modules / items / snapshots / fetch_runs / settings），写操作全局锁串行化
- `web/icons.py`：物品与模块图标下载缓存到 `web/static/icons/`（sha1 前 16 位命名），前端引用本地路径
- `web/service.py`：手动刷新（单模块/全量）后台线程编排，内存态刷新进度供前端轮询
- `web/scheduler.py`：APScheduler 定时抓取——开服 ≤ 阈值天数（默认 14）每天抓，之后每周抓；规则页面可配置，存 settings 表
- 价格基准为神圣石：记录混沌⇄神圣汇率（抓 Currency 模块时自动更新），同时存 price_divine 与换算后 price_chaos
- 前端三级菜单：顶部「经济」（策略/做装/开荒禁用占位）、左侧赛季列表、14 个经济模块；表格复刻原站深色四列样式（图标、Wiki 链接、迷你走势 SVG、红/绿涨跌幅），支持排序/中英文搜索/开服天数筛选
- 赛季名称与开服日期界面手动录入，新旧赛季数据都保留可查；开服天数 = 快照日期 - 开服日期 + 1
- `tests/test_web_scraper.py`：20 项解析器单元测试（fixtures 为真实页面快照），`uv run pytest` 全部 44 项通过
- `.gitignore` 增加 `web/data/`、`web/static/icons/`

## 端到端验证

- 启动服务 → 创建赛季「0.5.5闪回」（开服 2026-09-04）→ 刷新 Economy_Fragments / Economy_Currency 真实抓取成功
- 汇率自动入库（1 神聖 ≈ 17.4 混沌）、price_divine/price_chaos 换算正确、33 个图标本地化、静态图标可访问
- 前端 JSX 经 babel-standalone 离线编译校验通过；浏览器端表现待人工验证

## 2026-09-15 浏览器验证与修复

- 修复：babel-standalone 新版默认 automatic JSX 运行时会生成 `import` 语句导致页面空白，改为 `text/x-jsx` + 手动 `Babel.transform(..., {runtime: "classic"})` 执行；同时规避 babel 对 `text/jsx` 的自动处理
- 修复：FastAPI `on_event` 弃用警告迁移为 lifespan 写法；增加空 favicon 消除 404
- 新增 `web/browser_check.py`：Playwright + 本机 Chrome 自动化验证（菜单/表格/本地图标/中英文搜索/排序/开服天数/定时配置保存/赛季新增切换/刷新按钮/控制台无报错），24 项全部通过；开发依赖新增 playwright
- 全量刷新 14 个模块真实数据入库（107 个物品、118 个本地图标），页面截图确认渲染与原站一致
