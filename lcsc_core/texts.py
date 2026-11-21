"""Bilingual interface text.

The language setting decides both the interface language and the storefront that
is queried, so every visible string goes through :func:`t`.  Both languages are
kept in one table so a missing translation is a syntax error rather than a
runtime surprise, and :func:`t` raises on an unknown key so tests catch typos.

Only interface text lives here.  Machine-readable tokens (batch log statuses,
SQLite values, storefront field names) stay untranslated.
"""

from __future__ import annotations

from lcsc_core.routing import DEFAULT_LANGUAGE, normalise_language

#: ``key -> (中文, English)``.  Keep keys grouped by screen.
_STRINGS: dict[str, tuple[str, str]] = {
    # -- product / general -------------------------------------------------
    "app.subtitle": ("LCSC 元件数据库管理", "LCSC component database manager"),
    "app.unofficial": (
        "非官方工具，与立创商城 / LCSC 无关。数据来自公开商品页面。",
        "Unofficial tool, not affiliated with LCSC. Data comes from the public "
        "storefront pages.",
    ),
    "common.close": ("关闭", "Close"),
    "common.cancel": ("取消", "Cancel"),
    "common.save": ("保存", "Save"),
    "common.search": ("搜索", "Search"),
    "common.refresh": ("刷新", "Refresh"),
    "common.clear": ("清除", "Clear"),
    "common.browse": ("浏览…", "Browse…"),
    "common.yes": ("是", "Yes"),
    "common.no": ("否", "No"),
    "common.details": ("详情", "Details"),
    "common.none": ("（无）", "(none)"),
    # -- toolbar -----------------------------------------------------------
    "toolbar.open": ("打开…", "Open…"),
    "toolbar.new": ("新建…", "New…"),
    "toolbar.batch": ("批量导入", "Batch import"),
    "toolbar.settings": ("设置", "Settings"),
    "toolbar.no_database": ("未打开数据库", "No database"),
    "toolbar.open_or_create": ("打开或新建数据库", "Open or create a database"),
    "toolbar.parts": ("{count} 个元件", "{count} parts"),
    "toolbar.parts_one": ("1 个元件", "1 part"),
    "toolbar.language": ("语言", "Language"),
    "toolbar.language_hint": (
        "中文 => 立创商城 (¥)；English => LCSC (US$)",
        "Chinese => szlcsc.com (CNY); English => LCSC (USD)",
    ),
    # -- tabs --------------------------------------------------------------
    "tab.search": ("搜索 {site}", "Search {site}"),
    "tab.database": ("数据库", "Database"),
    # -- search ------------------------------------------------------------
    "search.section": ("搜索 {site}", "SEARCH {site}"),
    "search.placeholder": ("立创编号 C25804、型号或关键词", "C-number, MPN or keywords"),
    "search.button": ("搜索", "Search"),
    "search.busy": ("搜索中…", "Searching…"),
    "search.tip": (
        "提示：直接输入立创编号（如 C25804）或完整型号，结果最准确。",
        "Tip: an LCSC part number (e.g. C2040) or a full MPN returns the fewest variants.",
    ),
    "search.empty_query": ("请输入要搜索的编号或关键词。", "Enter a part number or keyword."),
    "search.rate_limited": (
        "立创商城正在限流，请等待 {seconds} 秒后重试。",
        "LCSC is rate limiting. Wait {seconds} seconds and retry.",
    ),
    # -- results -----------------------------------------------------------
    "results.title": ("搜索结果", "Search results"),
    "results.count": ("{count} 条", "{count} found"),
    "results.searching": ("搜索中…", "searching…"),
    "results.empty": ("输入关键词开始搜索。", "Search to see parts here."),
    "results.empty_none": (
        "没有匹配的元件。试试立创编号或更具体的型号。",
        "No products matched that search. Try the LCSC part number or fewer keywords.",
    ),
    "results.page": ("第 {page} / {pages} 页", "Page {page} of {pages}"),
    "results.prev": ("上一页", "Prev"),
    "results.next": ("下一页", "Next"),
    "results.load_more": ("再加载 {count} 条", "Load {count} more"),
    "results.category_label": ("类目", "Category"),
    "results.category_all": ("全部类目", "All categories"),
    "results.enriching": ("正在读取详情…", "Loading details…"),
    "results.sort_note": ("按来源排序", "Source order"),
    # -- table columns -----------------------------------------------------
    "col.part": ("立创编号", "LCSC#"),
    "col.mpn": ("型号", "MPN"),
    "col.manufacturer": ("品牌", "Manufacturer"),
    "col.package": ("封装", "Package"),
    "col.stock": ("库存", "Stock"),
    "col.price": ("价格", "Price"),
    "col.description": ("描述", "Description"),
    "col.symbol": ("符号", "Symbol"),
    "col.footprint": ("封装库", "Footprint"),
    "col.status": ("状态", "Status"),
    # -- detail panel ------------------------------------------------------
    "detail.empty": (
        "选择一个搜索结果查看详情，并设置它的 KiCad 符号与封装。",
        "Select a search result to see details\nand set its KiCad symbol and footprint.",
    ),
    "detail.badge_new": ("未入库", "NOT IN DATABASE"),
    "detail.badge_saved": ("已入库", "IN DATABASE"),
    "detail.overview": ("概览", "OVERVIEW"),
    "detail.mapping": ("KICAD 映射", "KICAD MAPPING"),
    "detail.datasheet": ("数据手册 ↗", "Datasheet ↗"),
    "detail.product_page": ("商品页 ↗", "Product page ↗"),
    "detail.view_all": ("查看全部", "View all"),
    "detail.param_count": ("{count} 个参数", "{count} parameters"),
    "detail.symbol": ("符号", "Symbol"),
    "detail.footprint": ("封装", "Footprint"),
    "detail.mapping_hint": (
        "在映射里用 ? 代替型号，保存时自动替换。",
        "Use ? in place of the MPN; it is replaced when you save.",
    ),
    "detail.add": ("加入数据库", "Add to database"),
    "detail.update": ("更新数据库", "Update database"),
    "detail.enriching": ("正在读取完整参数…", "Loading full details…"),
    "detail.enriched": ("已读取完整参数", "Full details loaded"),
    "detail.enrich_failed": (
        "详细参数读取失败，将保存搜索结果中的数据。",
        "Details unavailable; the search result data will be saved instead.",
    ),
    "field.manufacturer": ("品牌", "Manufacturer"),
    "field.package": ("封装", "Package"),
    "field.category": ("类目", "Category"),
    "field.part_number": ("立创编号", "LCSC PN"),
    "field.stock": ("库存", "Stock"),
    "field.price": ("价格", "Unit price"),
    "field.status": ("状态", "Part status"),
    # -- parameter dialog --------------------------------------------------
    "params.title": ("参数 - {part}", "Parameters - {part}"),
    "params.subtitle": (
        "{count} 个参数（来源：{site}）",
        "{count} parameters reported by {site}",
    ),
    "params.column_name": ("参数", "PARAMETER"),
    "params.column_value": ("值", "VALUE"),
    "params.none": ("没有参数", "No parameters reported"),
    # -- database tab ------------------------------------------------------
    "db.title": ("数据库记录", "Database records"),
    "db.count": ("{count} 条记录", "{count} records"),
    "db.count_one": ("1 条记录", "1 record"),
    "db.duplicates": ("{count} 个重复型号", "{count} duplicate MPNs"),
    "db.filter_placeholder": ("按型号、品牌、描述或符号筛选", "Filter by MPN, maker, description or symbol"),
    "db.empty": ("打开或新建数据库以浏览记录。", "Open or create a database to browse its records."),
    "db.open": ("打开数据库…", "Open database…"),
    "db.create": ("新建数据库…", "Create database…"),
    "db.edit_mapping": ("编辑 KiCad 映射", "Edit KiCad mapping"),
    "db.update_mapping": ("保存映射", "Save mapping"),
    "db.delete": ("删除记录", "Delete record"),
    "db.delete_confirm": ("确定要删除 {mpn} 吗？此操作不可撤销。",
                          "Delete {mpn}? This cannot be undone."),
    "db.deleted": ("已删除 {mpn}。", "Deleted {mpn}."),
    "db.mapping_saved": ("已更新 {mpn} 的映射。", "Updated the mapping for {mpn}."),
    "db.duplicates_body": ("这些型号出现了多次：\n\n{rows}",
                           "These MPNs appear more than once:\n\n{rows}"),
    "db.no_selection": ("请先选择一条记录。", "Select a record first."),
    # -- status bar --------------------------------------------------------
    "status.no_db": ("未打开数据库", "No database open"),
    "status.ready": ("数据库就绪", "Database ready"),
    "status.searching": ("正在搜索 {site}…", "Searching {site}…"),
    "status.failed": ("搜索失败", "Search failed"),
    "status.param_rows": ("{count} 行参数", "{count} parameter rows"),
    "status.param_rows_one": ("1 行参数", "1 parameter row"),
    "status.refreshed": ("已刷新。", "Refreshed."),
    "status.saved": ("已保存 {part}。", "Saved {part}."),
    "status.opened": ("已打开 {name}（{count} 条记录）。", "Opened {name} ({count} records)."),
    "status.wait": ("请等待当前操作完成。", "Wait for the current operation to finish."),
    # -- settings ----------------------------------------------------------
    "settings.title": ("设置", "Settings"),
    "settings.config_folder": ("配置目录：{path}", "Configuration folder: {path}"),
    "settings.language": ("语言 / Language", "Language / 语言"),
    "settings.language_note": (
        "切换语言会同时切换数据来源：中文使用立创商城（人民币），"
        "English 使用 LCSC（美元）。界面会立即重建。",
        "The language also selects the storefront: Chinese searches szlcsc.com "
        "(CNY), English searches LCSC (USD). The window is rebuilt immediately.",
    ),
    "settings.database": ("数据库", "Database"),
    "settings.page_size": ("每页结果数", "Results per page"),
    "settings.timeout": ("HTTP 超时（秒）", "HTTP timeout (seconds)"),
    "settings.interval": ("请求间隔（毫秒）", "Delay between requests (ms)"),
    "settings.batch_delay": ("批量导入间隔（毫秒）", "Batch request delay (ms)"),
    "settings.cache": ("缓存有效期", "Response cache lifetime"),
    "settings.cache_off": ("不缓存", "No cache"),
    "settings.cache_hour": ("1 小时", "1 hour"),
    "settings.cache_6h": ("6 小时", "6 hours"),
    "settings.cache_day": ("1 天", "1 day"),
    "settings.cache_week": ("1 周", "1 week"),
    "settings.log_level": ("日志级别", "Log level"),
    "settings.reveal": ("打开配置目录", "Reveal config folder"),
    "settings.clear_cache": ("清空响应缓存", "Clear response cache"),
    "settings.cache_cleared": ("缓存已清空。", "Response cache cleared."),
    "settings.politeness": (
        "请求间隔用于礼貌访问立创商城；设为 0 会更快但可能被限流。",
        "The request delay keeps the tool polite to the storefront; 0 is faster "
        "but more likely to be rate limited.",
    ),
    "settings.invalid": ("搜索页大小、超时和间隔必须是数字。", "Page size, timeout and delay must be numbers."),
    # -- batch import ------------------------------------------------------
    "batch.title": ("批量导入 CSV", "Batch import CSV"),
    "batch.choose": ("选择 CSV…", "Choose CSV…"),
    "batch.expected_header": (
        "第一列必须是以 C 开头的立创编号；表头为 "
        "lcsc_part_number,kicad_symbol_library,kicad_footprint_library",
        "The first column must be an LCSC part number; header is "
        "lcsc_part_number,kicad_symbol_library,kicad_footprint_library",
    ),
    "batch.preview": ("预览", "Preview"),
    "batch.rows": ("{count} 行有效数据", "{count} valid rows"),
    "batch.rows_one": ("1 行有效数据", "1 valid row"),
    "batch.start": ("开始导入", "Start import"),
    "batch.stop": ("停止", "Stop"),
    "batch.progress": ("{done} / {total}", "{done} / {total}"),
    "batch.summary": (
        "新增 {inserted}，更新 {updated}，跳过 {skipped}，失败 {errors}",
        "Inserted {inserted}, updated {updated}, skipped {skipped}, failed {errors}",
    ),
    "batch.log_written": ("日志：{path}", "Log: {path}"),
    "batch.no_rows": ("请先选择一个有效的 CSV 文件。", "Choose a valid CSV file first."),
    "batch.overwrite": ("覆盖已存在的记录", "Overwrite existing records"),
    "batch.skip_duplicates": ("跳过已存在的记录", "Skip records that already exist"),
    # -- about -------------------------------------------------------------
    "about.title": ("关于 KiCad LibGen LCSC", "About KiCad LibGen LCSC"),
    "about.version": ("版本 {version}", "Version {version}"),
    "about.what": (
        "搜索立创商城（szlcsc.com）或 LCSC（lcsc.com），把元件写入 KiCad 的 "
        "components.db 数据库。数据库结构与 KiCad LibGen 完全一致。",
        "Search szlcsc.com or lcsc.com and save parts into a KiCad components.db "
        "database. The schema is identical to KiCad LibGen's.",
    ),
    "about.prices": (
        "价格与库存来自公开页面，是查询时的快照。",
        "Prices and stock come from the public pages and are a snapshot in time.",
    ),
    # -- errors ------------------------------------------------------------
    "error.no_result_column": (
        "立创商城返回的数据格式与程序预期不同。",
        "LCSC returned data this program does not understand.",
    ),
}

#: Language-neutral key used for duplicate-MPN dialog titles.
_DUPLICATE_TITLES = {"zh_CN": "重复型号", "en_US": "Duplicate MPNs"}

_language = DEFAULT_LANGUAGE


def set_language(language: str) -> str:
    global _language
    _language = normalise_language(language)
    return _language


def language() -> str:
    return _language


def t(key: str, **values: object) -> str:
    """Return *key* in the active language, formatted with *values*."""
    try:
        chinese, english = _STRINGS[key]
    except KeyError as exc:  # pragma: no cover - a typo must fail loudly
        raise KeyError(f"missing translation key: {key!r}") from exc
    template = chinese if _language == "zh_CN" else english
    if not values:
        return template
    try:
        return template.format(**values)
    except (KeyError, IndexError):  # pragma: no cover - defensive
        return template


def tn(key: str, count: int, **values: object) -> str:
    """Translate a counted string, using ``<key>_one`` when *count* is 1."""
    singular = f"{key}_one"
    actual = singular if count == 1 and singular in _STRINGS else key
    return t(actual, count=count, **values)


def duplicate_title() -> str:
    return _DUPLICATE_TITLES.get(_language, _DUPLICATE_TITLES["en_US"])


def all_keys() -> tuple[str, ...]:
    """Every translation key (used by the tests)."""
    return tuple(_STRINGS)


def strings(key: str) -> tuple[str, str]:
    return _STRINGS[key]
