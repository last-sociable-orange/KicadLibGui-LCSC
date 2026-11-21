# KicadLibGui-LCSC — Engineering Plan (v1)

> **Archived:** this is the plan as approved on 2026-11-21, kept for the record.
> For what was actually built — including four deliberate improvements over this
> plan — see [`DEV_PLAN.md`](DEV_PLAN.md) and the code itself.

**Status:** approved and implemented (v1.0.0)
**Date:** 2026-11-21
**Sources studied:** `KicadLibGui/` (the DigiKey front end to clone), `LCSC3D/` (the reference LCSC protocol implementation)
**Deliverable:** a standalone tkinter program in `KicadLibGui-LCSC/` that searches **szlcsc.com** (Chinese UI) or **lcsc.com** (English UI) and writes the same 80-column KiCad `components` SQLite table that KicadLibGui writes.

---

## 1. What I studied, and what I verified live

### 1.1 KicadLibGui (the thing being cloned)

It is a thin, well-factored shell around a KiCad `components.db`:

| Layer | Files | What it does | Fate in the clone |
|---|---|---|---|
| `kicad_core/` | `models.py`, `database.py`, `errors.py` | 80-column `ProductInfo`, fixed upsert (`UPDATE`→`INSERT` in `BEGIN IMMEDIATE`), schema validation, typed errors | **Kept verbatim** (only error default strings re-worded) |
| `kicad_core/parser.py` | 146 lines | DigiKey `ProductSearch` → `ProductInfo` | **Replaced** by LCSC parsers |
| `services/` | `config.py`, `auth_service.py`, `search_service.py`, `database_service.py`, `batch_service.py`, `logging_setup.py` | UI-free logic | `config.py` gains a `language` field; `auth_service.py` **deleted** (no OAuth); `search_service.py` rewritten; rest kept |
| `gui/` | `app.py`, `main_window.py`, `theme.py`, `worker.py`, `database_tab.py`, `widgets/*`, `dialogs/*` | Tk/ttk shell, one-job `TaskRunner` (queue + 50 ms drain), light theme, cards, pills, banner | **Kept**, labels/columns/actions adapted |
| root | `gui_main.py`, `digikey_auth.py`, `digikey_search.py`, `kicad_cip.py`, `colors.py`, `version.py` | entry point + DigiKey client | DigiKey files **deleted**, `gui_main.py` kept, LCSC client added |

Key behaviours worth preserving exactly: identical 80-column schema (so existing KiCad DbLib/dbl configs and existing databases keep working), MPN-keyed upsert that never duplicates, `?` placeholder expansion in the KiCad mapping fields, and the worker-thread/queue discipline (Tk is not thread-safe).

### 1.2 LCSC3D (the protocol reference)

Two completely separate clients behind one language check — this is exactly the routing you asked for:

```python
# LCSC3D/app/lcsc3d/services/international_store.py:14-21
def storefront_url(part='', domestic_url=''):
    if get_preferences().language == 'en_US':
        return HOME + '/product-detail/' + part + '.html' if PART.fullmatch(part) else HOME
    return domestic_url or 'https://so.szlcsc.com/global.html?' + urlencode({'k': part})

def catalog_client():
    return InternationalStoreClient() if get_preferences().language == 'en_US' else StoreClient()
```

`Preferences.language` is `'zh_CN' (default) | 'en_US'`, validated on load, and changing it tears down and rebuilds the store UI.

### 1.3 What I confirmed with live requests today (2026-11-21)

| Check | Result |
|---|---|
| `GET https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C2040` | **HTTP 200, clean JSON.** `{"code":200,"ok":true,"result":{…}}` — the whole part in one call: `productModel`, `brandNameEn`, `encapStandard`, `wmCatalogNameEn`, `stockNumber`, `minBuyNumber`, `productPriceList[{ladder, usdPrice, productPrice}]`, `pdfUrl`, `productImages[3]`, `productWeight`, `eccn`, `currencyType:"USD"`, `isShowForeignPrice`, `paramVOList[{paramName, paramNameEn, paramValue, paramValueEn, isMain}]` (9 params for C2040) |
| `GET https://item.szlcsc.com/26547.html` (domestic detail page for C25804) | **HTTP 200**, server-rendered product: 商品参数表 (贴片电阻 / 电阻类型 厚膜电阻 / 阻值 10kΩ / 精度 ±1% / 功率 100mW / 工作电压 75V / 温度系数 ±100ppm/℃ / 工作温度 -55℃~+155℃), 商品毛重 0.03491 g, datasheet viewer `https://item.szlcsc.com/datasheet/0603WAF1002T5E/26547.html` + signed PDF on `atta.szlcsc.com` |
| `GET https://so.szlcsc.com/query/product/detail?…` | HTTP 200 but `{"code":403,"msg":"非法ACL-URL请求"}` ⇒ **there is no public JSON detail endpoint on the domestic side**; the item HTML page is the route |
| `robots.txt` for `lcsc.com`, `szlcsc.com`, `so.`, `item.`, `list.` | `lcsc.com`: only `/cart|checkout|order|personalCenter` and `/product-detail-v2/` disallowed → **`/product-detail/` is allowed**. `so.szlcsc.com`: only `/member/`. `item.szlcsc.com`: allows all, disallows `/catalog/`, `/brand/`, `/details/` … → **product pages allowed**. `list.szlcsc.com`: allows `/catalog/*.html` |

Not verifiable from this sandbox (pwsh HTTPS is blocked by a credential-store restriction, and my fetch tool is GET-only):
the two **POST search endpoints** and the international **discovery** call. For those I rely on LCSC3D's source, its live-validation records dated 2026-10, and third-party code that still uses the same `wmsc` ladder shape. **Phase 0 closes this gap with a one-shot probe script before any GUI work.**

### 1.4 Also found: an official, documented LCSC API

[`https://www.lcsc.com/docs/openapi/`](https://www.lcsc.com/docs/openapi/index.html) documents an agent API with `key` + `nonce` + `timestamp` + SHA1 `signature`:

- `GET /rest/wmsc2agent/search/product` (max 30/page) · `GET /rest/wmsc2agent/product/info/{product_number}` · `GET /rest/wmsc2agent/category/product/{category_id}` · `GET /rest/wmsc2agent/category` · `GET /rest/wmsc2agent/brand`
- both take `currency=USD|CNY|EUR|HKD`

Access is application-gated (`lcsc.com/agent/apply`, business details required). **You have ruled this out — no key will ever be obtained — so this is recorded for completeness only. No agent-API code, config, credential fields or signature helpers will be written.**

---

## 2. Source strategy

```
                          user types a query
                                 │
                    settings.language == 'en_US' ?
                    ┌────────────┴─────────────┐
                 yes │                          │ no
                    ▼                          ▼
        InternationalBackend            DomesticBackend
        (lcsc.com / wmsc.lcsc.com)      (szlcsc.com / so. / item.)
        English params, USD,            Chinese params, CNY,
        www.lcsc.com/product-detail/    item.szlcsc.com/{id}.html
                    └────────────┬─────────────┘
                                 ▼
                        ProductInfo (80-col)
                                 ▼
                     kicad_core.ProductDb.upsert
```

One `Backend` protocol, two implementations, chosen per search (so a language flip takes effect on the next query without restarting the app):

```python
class Backend(Protocol):
    language: str                      # 'zh_CN' | 'en_US'
    def search(self, query, page, page_size, *, category=None) -> SearchPage: ...
    def detail(self, part) -> ProductInfo: ...        # full params + datasheet
    def categories(self) -> list[Category]: ...       # optional, cached
```

`SearchPage` carries `items: list[ProductInfo]`, `total`, `page`, `page_size`, `pages`, plus `categories` (international) or `facets` (domestic, Phase 4) so the GUI stays backend-agnostic.

---

## 3. Protocol spec to implement

### 3.1 Domestic — `szlcsc.com` (Chinese)

**Search (also used for paging)** — `POST https://so.szlcsc.com/query/product`, JSON body, 24 fixed keys (empty defaults for the filters we do not expose in v1):

```json
{"catalogIdFilter":"","brandIdFilter":"","standardFilter":"","arrangeFilter":"","labelFilter":"",
 "authenticationFilter":"","sortNumber":0,"satisfyStockType":"","startPrice":"","endPrice":"",
 "demandNumber":"","spotFilter":1,"discountFilter":1,"hasDataFile":false,"brandPlaceFilter":"",
 "brandOriginFilter":"","secondKeyword":"","smtLabelFilter":"","queryProductTypeCode":"",
 "lastParamName":"","keyword":"<query>","currentPage":1,"pageSize":30,"queryParameterValue":""}
```

Headers: browser UA, `Content-Type: application/json;charset=UTF-8`, `Origin: https://so.szlcsc.com`, `Referer: https://so.szlcsc.com/`, `Accept: application/json,text/html,*/*`, `Cache-Control: no-cache`. **No login, no cookie, no token.** `pageSize` must be 30 (100 returns null).

Response → `code == 200` and `result.searchResult` with `totalCount`, `pageSize`, `currePage` (sic — the site's own spelling), `countPage`, `productRecordList[]`. Each row: `productVO{…}` + `paramLinkedMap{名称: 值}` + `totalStockNumber` (the number the site displays as 现货).

Per-product fields I will read (from `productVO`): `productCode` (C-number), `productId` (numeric id → item URL), `productModel` (MPN), `productName`, `productGradePlateName` (brand), `encapsulationModel`, `productType` (category), `remark`, `productUnit`, `minBuyNumber`, `theRatio`, `stockNumber`/`validStockNumber`, `isShowPrice`, `productPriceList[{startPurchasedNumber, endPurchasedNumber(-1 = open), productPrice, spNumber, epNumber}]`, `luceneBreviaryImageUrls` (`URL<$>URL`, `/product/breviary/` → `/product/source/` for originals), `productCycle` + `productUnsealVendition` + `productStockStatus` (stop-sale detection).

Price tiers: multiply ladder qty by `theRatio`, floor at `minBuyNumber × step`, drop `end < start`, dedupe by start qty, `format(Decimal,'f')`.

**Detail** — `GET https://item.szlcsc.com/{productId}.html`, then read `<script id="__NEXT_DATA__">` and take `props.pageProps.webData` (a 20-line `HTMLParser` subclass; no BeautifulSoup). Gives `paramList[{parameterName, parameterDetailValue}]`, `productRecord.fileTypeVOList[]` where `fileType == 'pdf_property'` → datasheet (`linkAddress` absolute, else `https://atta.szlcsc.com` + `fileUrl`), then legacy `pdfFileDetailVO`. Guard: parsed `productCode` must equal the requested part, else "details unavailable".

**Categories (Phase 4)** — `GET https://staticdata.szlcsc.com/common/data/resource-catalog-list-new.json`; browse via `POST https://list.szlcsc.com/category/product` with the same body, empty `keyword`, `catalogIdFilter=<id>` (note: that endpoint always echoes `currePage: 1`).

### 3.2 International — `lcsc.com` (English)

Search is **two-step** (there is no single keyword→list call):

1. **Discovery** — `POST https://wmsc.lcsc.com/ftps/wm/search/v3/global` `{"keyword": q}` → `result.isToDetail` (single exact hit), `result.catalogVOS` (category tree with counts), `result.scene` (`FULL_MATCH`/`NO_RESULT`/`REDIRECT_PRODUCT_DETAIL`), `result.productSearchResultVO`.
2. **List** — if categories exist: `POST https://wmsc.lcsc.com/ftps/wm/product/query/list` with `{"keyword":"", "globalKeyword": q, "catalogIdList":[id], "brandIdList":[], "encapValueList":[], "isStock":false, "isOtherSuppliers":false, "isAsianBrand":false, "isDeals":false, "isRohsCert":false, "paramNameValueMap":{}, "currentPage":p, "pageSize":20}` (+`scene` echoed on `FULL_MATCH`); else `POST /ftps/wm/search/v3/global` again with `currentPage`/`pageSize`.
   Response contract: `currPage == page`, `pageRow == 20`, total from `actualTotalRow ?? totalRow`, rows in `dataList`.

Headers: browser UA, `Accept-Language: en-US,en;q=0.9`, `Origin: https://www.lcsc.com`, `Referer: https://www.lcsc.com/`, `Content-Type: application/json`. **No login, no cookie.**

**Detail** — I will use the JSON endpoint I verified live instead of LCSC3D's HTML scrape of `__NEXT_DATA__`:
`GET https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C2040`. Same field vocabulary as the search rows (`productModel`, `brandNameEn`, `encapStandard`, `pdfUrl`, `paramVOList`, `productPriceList`, `stockNumber`, `productWeight`, `eccn`, `parentCatalogList`), plus English *and* Chinese param names — much more robust than parsing a Next.js blob. HTML scrape is kept as an automatic fallback if that endpoint ever disappears.

Prices: `usdPrice` only, gated by `isShowForeignPrice !== false`; an empty ladder is a valid answer (no silent CNY fallback).

### 3.3 What we deliberately do **not** implement

Login/CAS/QR, favourites, cart, orders, 3D models, symbol/footprint export (that is LCSC3D's job), PDF downloading beyond storing the URL, and the 20-from-30 paging stitch.

### 3.4 What we deliberately do **not** implement

Login/CAS/QR, favourites, cart, orders, 3D models, symbol/footprint export (that is LCSC3D's job), PDF downloading beyond storing the URL, the 20-from-30 paging stitch, and any agent-API/key handling.

---

## 4. Architecture of `KicadLibGui-LCSC/`

```
KicadLibGui-LCSC/
├── gui_main.py                  # --version / --self-test / --smoke-test / --portable / --db / --lang
├── version.py                   # APP_NAME="KiCad LibGen LCSC", 1.0.0
├── pyproject.toml               # deps: requests>=2.32 only
├── requirements*.txt
├── kicad_core/                  # ← copied from KicadLibGui (MIT), DB layer untouched
│   ├── models.py                # 80-column ProductInfo, ?-expansion, validate_mapping
│   ├── database.py              # create/validate/upsert/query, BEGIN IMMEDIATE
│   ├── errors.py                # AppError tree, LCSC wording
│   └── __init__.py
├── lcsc_core/
│   ├── session.py               # HttpSession: headers, timeout, gzip, size caps, retries-once,
│   │                            #   min-interval pacing, typed error mapping, LRU response cache
│   ├── routing.py               # language → backend, URL builders (item/lcsc/so/datasheet)
│   ├── domestic.py              # DomesticBackend: search, detail, categories
│   ├── international.py         # InternationalBackend: discovery + list + json detail (+HTML fallback)
│   ├── parsers.py               # raw JSON → ProductInfo: price ladder, params→32 slots,
│   │                            #   Value derivation, category→ID, status mapping
│   ├── texts.py                 # bilingual UI strings (zh_CN / en_US) + t(key)
│   └── fixtures_note.md         # provenance of recorded responses (no cookies, no account data)
├── services/
│   ├── config.py                # Settings (+ language, source="auto", cache TTL, min request interval)
│   ├── search_service.py        # backend dispatch, paging, detail enrichment, in-memory LRU
│   ├── database_service.py      # ← unchanged
│   ├── batch_service.py         # CSV import; C-number only (see §6)
│   └── logging_setup.py         # ← unchanged
├── gui/
│   ├── app.py                   # composition root, live language rebuild
│   ├── main_window.py           # toolbar, tabs, search card, results/detail panes, status bar
│   ├── database_tab.py          # browse/filter/edit mapping/delete/duplicate report
│   ├── theme.py                 # ← unchanged light theme
│   ├── worker.py                # ← unchanged TaskRunner
│   ├── widgets/{results_table,detail_panel,param_table,banner,__init__}.py
│   └── dialogs/{settings_dialog,batch_dialog,about_dialog}.py     # auth_dialog deleted
├── tests/
│   ├── fixtures/{domestic_search.json, domestic_item.html, international_search.json,
│   │             international_detail.json, categories.json}
│   ├── test_parsers.py test_database.py test_config.py test_search.py
│   ├── test_batch.py test_routing.py test_gui_smoke.py
├── build/                       # PyInstaller spec + windows/linux scripts (Phase 5)
└── docs/DEV_PLAN.md, README.md
```

Threading, error-banner, toast, worker and DB-connection patterns stay byte-for-byte as in KicadLibGui — they are already correct (short-lived SQLite connections per operation, no widget access off-thread).

---

## 5. Data mapping: LCSC → the 80-column `components` table

The schema is fixed (KiCad compatibility), so every LCSC field must land in an existing column.

| Column | Domestic (zh_CN) | International (en_US) |
|---|---|---|
| `ID` | `{productType}/{productModel}` e.g. `贴片电阻/0603WAF1002T5E` | `{wmCatalogNameEn}/{productModel}` e.g. `Microcontrollers/RP2040` |
| `Description` | `productName` (e.g. `厚膜电阻 10kΩ ±1% 100mW`) | `productIntroEn` ‖ `productNameEn` |
| `Keywords` | `productIntro` / `remark` (deduped, newline-joined) | same idea from `productIntroEn` |
| `Value` | rule below (MPN fallback) | rule below |
| `Manufacturer` | `productGradePlateName` (`UNI-ROYAL(厚声)`) | `brandNameEn` (`Raspberry Pi`) |
| `ManufacturerProductNumber` | `productModel` | `productModel` |
| `Package` | `encapsulationModel` (`0603`) | `encapStandard` (`LQFN-56(7x7)`) |
| `KicadSymbolLibrary` / `KicadFootprintLibrary` | user entry, `?` → MPN at save | same |
| `PartStatus` | `productCycle`/`productUnsealVendition` → `Active` / `Not recommended` / `Obsolete` | `isPreSale`/`isNotOverstock` → `Active` / `Pre-order` |
| `QtyAvailable` | row `totalStockNumber` (falls back to `stockNumber`) | `stockNumber` |
| `Distributor` | `LCSC` | `LCSC International` |
| `DistributorProductNumber` | `productCode` (`C25804`) | `productCode` (`C2040`) |
| `UnitPrice` | see §5.2 | see §5.2 |
| `ProductUrl` | `https://item.szlcsc.com/{productId}.html` | `https://www.lcsc.com/product-detail/{C}.html` |
| `DatasheetUrl` | `pdf_property` `linkAddress`, else `https://atta.szlcsc.com` + `fileUrl`; fallback `https://item.szlcsc.com/datasheet/{model}/{id}.html` | `pdfUrl` |
| `Param01..32 / Value01..32` | see §5.1 | see §5.1 |

### 5.1 The 32 parameter slots

LCSC returns 4–30+ params (domestic search rows give ~4–6 via `paramLinkedMap`; the detail page gives the full `paramList`). **Locked policy:**

1. Start from the detail-page params (domestic) / `paramVOList` (international), falling back to the search row when the detail call fails.
2. Float "key spec" names to the front so they are never truncated: 阻值/容值/感值/精度/功率/耐压/工作电压/工作温度/温度系数/封装 (+ their English equivalents: Resistance, Capacitance, Inductance, Tolerance, Power, Voltage - Supply, Operating Temperature, Temperature Coefficient, Package).
3. Fill remaining slots in the source order.
4. Truncate to 32; unused slots stay `-`/`-` (the existing `DEFAULT_PARAM`).
5. Names are stored in the source language (Chinese for zh_CN, English for en_US) since that is what the user sees and searches.

### 5.2 `Value` and `UnitPrice`

**Value** — DigiKey mode derived it from specific parameter IDs (`10kOhms` → `10K`). The LCSC analogue: if a value-type parameter exists (阻值/容值/感值/Resistance/Capacitance/Inductance/Impedance), strip the unit symbol (`Ω`, `Ohm(s)`, `F`, `H`) and upper-case (`10kΩ` → `10K`, `100nF` → `100NF`); otherwise `Value = MPN`. This keeps `Value` useful for schematic-to-database matching, which is why the column exists.

**UnitPrice** — **locked format**: same `price@qty` grammar KicadLibGui already writes, chained with `/`, with the currency symbol in front so a row is self-describing:

```
domestic:      ¥20.17@1/¥17.26@10/¥15.44@30/¥12.32@100
international: US$1.0968@1/US$1.0092@10/US$0.9266@30
```

Symbols are `¥` (U+00A5) for CNY and `US$` for USD; the ladder is capped at 6 tiers to keep the cell readable, and no currency goes into the 32 parameter slots.

### 5.3 Batch import CSV (locked: C-number only)

Narrowing the key to the C-number makes each row exactly one cheap request (`product/detail?productCode=` internationally; search-then-item-page domestically) and removes the "multiple MPN hits" ambiguity class entirely.

```csv
lcsc_part_number,kicad_symbol_library,kicad_footprint_library
C25804,Symbol:?,Footprint:R_0603_1608Metric
C2040,Symbol:MCU_RaspberryPi,Footprint:QFN-56-1EP_7x7mm_P0.4mm_EP3.4x3.4mm
```

- Header must be exactly `lcsc_part_number,kicad_symbol_library,kicad_footprint_library`. The legacy header `manufacturer_product_number` is still *accepted* as an alias so old KicadLibGui BOM CSVs open, but every first-column value must match `^C[0-9]{1,18}$` or that row is reported as an error instead of silently searching for an MPN.
- UTF-8 (with or without BOM), same preview/validation dialog, same `<name>-<yy-mm-dd-HH-MM-SS>.log` written next to the CSV with `<C-number>: <record> ==> <status>`.
- If a C-number cannot be resolved on the *current* language's site (a domestic-only MRO item, for instance), the row is logged as `skipped-not-found` with a hint to switch language — no silent cross-site fallback.

---

## 6. UI changes vs KicadLibGui

Same skeleton, different content. Concretely:

- **Toolbar**: `Open…`/`New…`/`Batch import`/`Settings` unchanged. `Authenticate` **removed**; replaced by a **language/source selector** (中文 · 立创商城 / EN · LCSC) showing the active host so the user always knows which site is being queried.
- **Tabs**: `Search 立创商城` / `Search LCSC` (label follows language) + `Database`.
- **Results table** columns: `LCSC#` (`C25804`), `MPN`, `Manufacturer`, `Package`, `Stock`, `Price (¥/US$)`, `Description`. Sorting by clicking headers (client-side, since the API ordering is opaque).
- **Paging row** under the table: `Prev` / `Page x of y` / `Next` / `Load 30 more`. **Locked:** 30 rows per page (the store's native page size), one request per page, no 20-from-30 stitching. "Load 30 more" appends the next page to the table; `Prev`/`Next` replace it.
- **Detail panel**: same two-column layout (OVERVIEW | KICAD MAPPING). Overview rows become Manufacturer / Package / Category / LCSC part / Stock / Price ladder / Datasheet link / Product-page link, plus a "参数 (n)" link opening the existing `param_table` dialog. Save button text unchanged (`Add to database` / `Update database`), with the same "already in database" detection by MPN.
- **Detail enrichment**: on row selection the app fetches the detail page once (background thread, spinner in the status bar), fills the real 32 params + datasheet, and caches by C-number for the session — replacing the current instant-from-search-row behaviour. If enrichment fails, the row stays usable with search-row data and the banner explains why.
- **Settings dialog**: database path, language, result page size, HTTP timeout, request pacing (ms), cache TTL, log level, "clear response cache". Token/token-path rows deleted.
- **All strings** go through `lcsc_core.texts.t()`; flipping language in Settings rebuilds the window in place (same technique as LCSC3D) — if that proves fragile I fall back to "restart to apply", which I will confirm during Phase 3.
- **About dialog**: states that data comes from the public storefront pages, that the tool is unofficial, and that prices/stock are snapshots.

---

## 7. Politeness, robustness, compliance

- **One request at a time** per backend (LCSC3D-style session lock), minimum interval between requests (default 400 ms), exponential backoff **once** on 429/5xx honouring `Retry-After`, no retry of POST bodies beyond that single deliberate retry.
- **Session caches**: search pages (LRU 32, TTL 10 min), detail objects (LRU 200, TTL 1 h), categories (TTL 24 h) — persisted to `%APPDATA%\KiCadLibGenLCSC\cache\*.json` so re-opening the app does not re-hit the site, and flushed by a Settings button.
- **Size/time caps**: 8 MiB JSON, 16 MiB image, 12–30 s timeout, gzip handled defensively (magic-byte sniff + bounded streaming inflate), TLS verified via certifi, no `verify=False` path.
- **robots/ToS**: I checked all five `robots.txt` files — the paths we use (`/product-detail/`, item pages, `so`/`list` search) are not disallowed, and no account data is touched. The app will nevertheless ship a README section stating: unofficial, unofficial endpoints may change, honour the store's terms, keep request volume human-scale, prices/stock are snapshots. The batch importer defaults to the same pacing and refuses to run faster than 1 req/400 ms.
- **Failure messages** name the operation and site but never echo query strings, cookies or signed URLs (the `atta.szlcsc.com` PDF links carry an OSS signature; only the sanitised datasheet URL is stored/logged).
- **No login, ever** — so no credential storage, and no risk of a stale session file.

---

## 8. Licensing

- `KicadLibGui` is **MIT** → the copied DB layer, theme, worker and GUI scaffolding carry over with its `LICENSE` and `THIRD-PARTY-NOTICES.md`.
- `LCSC3D` is **AGPL-3.0-or-later**. I will **not copy its code**. What I take is *protocol knowledge* (URLs, JSON field names, header sets, validation rules), which is not copyrightable expression, and every parser will be written fresh against my own recorded fixtures. I will note this explicitly in `docs/DEV_PLAN.md` and `THIRD-PARTY-NOTICES.md` so the provenance is auditable. If you would rather I copy LCSC3D code directly for speed, the whole project becomes AGPL — tell me and I will plan accordingly.
- Third-party runtime deps stay minimal: `requests` (+ `certifi`), stdlib `tkinter`.

---

## 9. Implementation phases

Each phase ends with something you can run and judge, and a git commit.

**Phase 0 — protocol lock-down (half a day)**
`tools/probe_endpoints.py` (run in the project `.venv` with the real network): one request per endpoint, prints HTTP status + the field names actually present, and saves sanitised JSON into `tests/fixtures/`. Deliverable: a short `docs/PROTOCOL-VERIFIED.md` recording exactly what works today. **If the domestic POST or the international discovery endpoint has drifted, we learn it here, before any GUI work.**

**Phase 1 — core + backends (1.5 days)**
`kicad_core/*` copied; `lcsc_core/session.py`, `routing.py`, `domestic.py`, `international.py`, `parsers.py`; `services/config.py` + `search_service.py`. Deliverable: `python -m lcsc_core.cli C25804` prints the 80-column dict for both backends; fixture-driven `pytest` green.

**Phase 2 — GUI search + save (2 days)**
`gui_main.py`, `app.py`, `main_window.py`, results table, detail panel, worker wiring, banner/toast, language switch. Deliverable: search → select → enter `Symbol:?`/`Footprint:?` → `Add to database` writes a correct row into a fresh `components.db` that KiCad can open.

**Phase 3 — database tab, detail enrichment, paging (1.5 days)**
Browse/filter/edit/delete/duplicates; background detail enrichment with caching; paging controls; international category combo.

**Phase 4 — batch import + settings polish (1 day)**
CSV import (**C-number only**, §5.3), preview/validation, progress, cancel, backoff, upstream-format log file; full settings dialog; cache management.

**Phase 5 — packaging + docs (1 day)**
PyInstaller spec + `build_windows.ps1` / `build_linux.sh` (mirroring KicadLibGui's), README, `--self-test`, GUI smoke test, `ruff` clean.

Total ≈ 7.5 working days. Phases 0–2 give a usable tool; 3–5 make it a peer of KicadLibGui.

---

## 10. Test strategy

- **Offline only in CI**: every test runs against recorded fixtures; no test touches the network. `--self-test` exercises DB upsert, parser, and CSV validation like KicadLibGui's.
- `test_parsers.py`: domestic row → `ProductInfo`, price ladder normalisation (`theRatio` step, `-1` open end, `isShowPrice:false`, NaN/negative rejection), `paramLinkedMap` → 32 slots, unit stripping for `Value`, C-number validation, `$`/`<$>` splitting, `/breviary/`→`/source/`.
- `test_parsers.py` (international): discovery → list two-step, `isToDetail` single hit, empty-scene handling, `pageRow`/`currPage` contract violations raising the right error, `isShowForeignPrice:false` ⇒ no tiers, `paramVOList` → slots.
- `test_search.py`: backend dispatch by language, paging arithmetic, in-memory/LRU cache hits, 429 → single retry with backoff, error-taxonomy mapping (mirrors KicadLibGui's `test_search.py`).
- `test_database.py`: unchanged from KicadLibGui — the upsert contract must stay identical (insert once, update on re-save, no duplicates, `?` expansion).
- `test_batch.py`: CSV validation (C-number only, per-row errors, duplicate warnings), batch paging/abort/cancel, log format `<part>: <record> ==> <status>`.
- `test_routing.py`: `zh_CN`→domestic URLs, `en_US`→lcsc.com URLs, URL builders for both item pages and datasheet fallbacks.
- `test_gui_smoke.py`: build the real window, search off a fake backend, save a row, close (same as KicadLibGui's smoke test).

---

## 11. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Undocumented endpoints drift/break | medium-high | Phase 0 verification; every parser defensive with typed errors; JSON detail endpoint instead of HTML scrape where possible; HTML scrape kept only as fallback; one place (`session.py`) to patch headers/UA |
| Site adds bot protection / captcha | medium | browser-UA + correct Origin/Referer, human-scale pacing, single-flight, aggressive caching; fail with a clear "site refused the request" message rather than retry storms |
| Domestic detail needed for datasheet/params = 2 requests per part | high (by design) | enrichment only on selection/save, cached 1 h, LRU 200; search-row params are enough to display a usable list immediately |
| 32-slot truncation loses a spec the user wants | medium | key-spec prioritisation (§5.1) + "View all" dialog showing every param from the last response |
| Price/stock policy confusion (CNY vs USD, snapshot vs live) | medium | currency symbol embedded in `UnitPrice`, `Distributor` distinguishes the two sites, About/README state that values are snapshots |
| Language flip mid-session desyncs UI | low-medium | backend chosen per query; window rebuild on language change; config change persists immediately |
| TLS/cert issues behind a corporate proxy | low | certifi bundle, clear certificate error message, timeout configurable, no proxy override beyond system default |
| Trademark/ToS optics | low | README: unofficial, not affiliated, no scraping beyond human-equivalent use, no data redistribution |

---

## 12. Decisions (locked 2026-11-21)

| # | Decision | Effect on the build |
|---|---|---|
| 1 | **Public site endpoints, no key** | `lcsc_core/domestic.py` + `international.py` only. No credential UI, no signature code, no agent-API module at all (ruled out: no key will ever be obtained). |
| 2 | **Bilingual GUI + data source** | `lcsc_core/texts.py` covers every visible string; Settings→Language rebuilds the window and switches the backend; `zh_CN` = szlcsc.com/CNY/Chinese params, `en_US` = lcsc.com/USD/English params. Default `zh_CN`, matching LCSC3D. |
| 3 | **`UnitPrice` = `¥20.17@1/¥17.26@10/…`** | Currency symbol baked into the ladder string, max 6 tiers, `US$` for the international site. |
| 4 | **Key specs first, then source order, truncate at 32** | Prioritised name list for both languages in `parsers.py`; the "View all" dialog still shows every parameter from the last response. |
| 5 | **30 per page with Prev/Next + Load more** | One backend request per page; no 20-from-30 stitching, no page-consistency contract checks beyond `totalCount` sanity. |
| 6 | **Batch CSV: C-number only** | Header `lcsc_part_number,…` (legacy `manufacturer_product_number` accepted as an alias); non-`C\d+` rows are per-row errors; see §5.3. |

Residual judgement calls I will make myself unless you object — all reversible, none affects the schema:

- `Distributor` reads `LCSC` for the domestic site and `LCSC International` for lcsc.com, so a shared database tells you which price culture a row came from.
- Detail enrichment is fetched on row selection (background thread, ~1 extra request per part) so the datasheet and the full parameter set are correct before you press **Add to database**; if the call fails the row is still saveable from search-row data, with a warning.
- Default request pacing 400 ms with a single 429/5xx retry, and a response cache under `%APPDATA%\KiCadLibGenLCSC\cache\`.
- App name in the title/About: **KiCad LibGen LCSC 1.0.0**, noting it is unofficial and unaffiliated with LCSC/JLC.
