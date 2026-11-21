# LCSC storefront protocol — verified record

Everything the program talks to, and the behaviour that was confirmed against the
live sites on **2026-11-21** by `tools/probe_endpoints.py` (52/52 checks passed).

Re-run that tool whenever the store changes; it is deliberately independent of
`lcsc_core` so it cannot inherit a wrong assumption from the code it validates.

```
python tools/probe_endpoints.py            # verify + rewrite tests/fixtures
python tools/probe_endpoints.py --check    # verify only
```

Both sites are anonymous: **no login, no cookie, no token, no API key** is
involved anywhere in this program.

---

## 1. Endpoints

| Purpose | Method | URL | Language |
|---|---|---|---|
| Keyword search / paging | POST | `https://so.szlcsc.com/query/product` | zh_CN |
| Category browse (not used in v1) | POST | `https://list.szlcsc.com/category/product` | zh_CN |
| Category tree | GET | `https://staticdata.szlcsc.com/common/data/resource-catalog-list-new.json` | zh_CN |
| Product detail | GET | `https://item.szlcsc.com/{productId}.html` | zh_CN |
| Search discovery | POST | `https://wmsc.lcsc.com/ftps/wm/search/v3/global` | en_US |
| Paged result list | POST | `https://wmsc.lcsc.com/ftps/wm/product/query/list` | en_US |
| Product detail | GET | `https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C…` | en_US |

Request headers (both sites): a normal desktop browser `User-Agent`, plus
`Accept: application/json,text/html,*/*`; for the JSON POSTs a `Content-Type`
(`application/json;charset=UTF-8` domestic, `application/json` international),
and an `Origin`/`Referer` matching the host being called
(`https://so.szlcsc.com/`, `https://www.lcsc.com/`); internationally also
`Accept-Language: en-US,en;q=0.9`. `Cache-Control: no-cache` is sent.
No `X-Requested-With`, no CSRF header, no signature.

---

## 2. Domestic — `szlcsc.com`

### 2.1 Search request

`POST https://so.szlcsc.com/query/product` with a JSON body of **24 fixed keys**
(an empty string means "no filter"; there is no way to omit them):

```json
{"catalogIdFilter":"","brandIdFilter":"","standardFilter":"","arrangeFilter":"","labelFilter":"",
 "authenticationFilter":"","sortNumber":0,"satisfyStockType":"","startPrice":"","endPrice":"",
 "demandNumber":"","spotFilter":1,"discountFilter":1,"hasDataFile":false,"brandPlaceFilter":"",
 "brandOriginFilter":"","secondKeyword":"","smtLabelFilter":"","queryProductTypeCode":"",
 "lastParamName":"","keyword":"C25804","currentPage":1,"pageSize":30,"queryParameterValue":""}
```

**Page size ceiling is 30.** `pageSize: 50` or `100` is *not* an error: the site
answers `code: 200` with `pageSize: null` and an empty `productRecordList`.
Verified. Requesting 10 or 30 works and is echoed back.

`currePage` **does** echo the requested page on this endpoint (verified pages
1/2/3, no overlapping rows), so no page-stitching or consistency guessing is
needed.

### 2.2 Search response

```
{"code": 200, "msg": null, "ok": true, "result": {"searchResult": {
    "totalCount": 1, "pageSize": 30, "currePage": 1, "countPage": 1,
    "productRecordList": [ { ...63 keys... } ] }}}
```

A row carries `productVO` (74 keys), `paramLinkedMap`, and `totalStockNumber`
(what the site shows as 现货). Fields read by the program:

| Field | Meaning |
|---|---|
| `productVO.productCode` | LCSC part number, `C25804` |
| `productVO.productId` | numeric id used to build the item URL (`26547`) |
| `productVO.productModel` | manufacturer part number (`0603WAF1002T5E`) |
| `productVO.productName` | short description (`厚膜电阻 10kΩ ±1% 100mW`) |
| `productVO.productGradePlateName` | brand incl. Chinese name (`UNI-ROYAL(厚声)`) |
| `productVO.encapsulationModel` | package (`0603`) |
| `productVO.productType` | category (`贴片电阻`) |
| `productVO.remark` | marketing blurb, used for `Keywords` |
| `productVO.productUnit` | unit of sale (`个`) |
| `productVO.minBuyNumber`, `theRatio` | minimum order / reel ratio — see §5 |
| `productVO.isShowPrice`, `productPriceList[]` | price ladder, see §2.3 |
| `productVO.luceneBreviaryImageUrls` | `URL<$>URL<$>…` thumbnails |
| `productVO.productCycle`, `productUnsealVendition`, `productStockStatus` | stop-sale flags |
| `row.paramLinkedMap` | `{名称: 值}` — only 4–6 headline parameters |
| `row.totalStockNumber` | stock shown in the search list |

**Highlight markup:** when the keyword matched a parameter, its value arrives
wrapped, e.g. `"<SPAN CLASS='LUCENE_HIGHLIGHT_CLASS'>10kΩ</SPAN>"`. Every
string from a search row must be tag-stripped and entity-unescaped before use.

`isShowPrice: false` means the ladder must be ignored (not shown as zero).

### 2.3 Price ladder

```
[{startPurchasedNumber: 1,   endPurchasedNumber: 9,   productPrice: 0.0101},
 {startPurchasedNumber: 10,  endPurchasedNumber: 49,  productPrice: 0.0079},
 {startPurchasedNumber: 50,  endPurchasedNumber: 99,  productPrice: 0.0069},
 {startPurchasedNumber: 100, endPurchasedNumber: 499, productPrice: 0.0063},
 {startPurchasedNumber: 500, endPurchasedNumber: -1,  productPrice: 0.0058}]
```

`endPurchasedNumber: -1` marks the open-ended top tier. Quantities are quoted
**as the site quotes them** and are *not* multiplied by `theRatio` (§5).

### 2.4 Item page

`GET https://item.szlcsc.com/{productId}.html` (HTML, ~150 KB). The product is
server-rendered into `<script id="__NEXT_DATA__">`; parse with `html.parser` and
`json.loads`, then read `props.pageProps.webData`:

| Path | Content |
|---|---|
| `productRecord.productCode` | must equal the part that was asked for |
| `productRecord.productName` / `remark` / `productGradePlateName` / `encapsulationModel` / `productType` / `productUnit` / `theRatio` / `minBuyNumber` | as in the search row |
| `productRecord.luceneBreviaryImageUrls` | `<$>`-joined images — **includes brand certificates**, see §6 |
| `productRecord.fileTypeVOList[]` | document groups; only `fileType == "pdf_property"` are datasheets |
| `paramList[]` | **the full parameter set** (`parameterName`, `parameterDetailValue`) — 7 for C25804 where the search row had 4 |
| `pdfFileDetailVO` | legacy single datasheet (`fileUrl`, `urlSign`) |
| `totalStockNumber`, `smtStockNumber`, `gdWarehouseStockNumber`, `jsWarehouseStockNumber` | stock breakdowns |

`productRecord.productPriceList` is **null** on the item page — price only exists
in the search response, so the two sources must be merged, never replaced.

`productRecord.productId` is a *string* here (`"26547"`) while the search row
returns an *int*.

### 2.5 Datasheet URL

From a `pdf_property` group's `detailVOList[]`:

1. `linkAddress` if it is an absolute `https` URL, else
2. `https://atta.szlcsc.com` + `fileUrl` when `fileUrl` starts `/upload/public/pdf/`.

Other groups (`certification_data_property`, `industry_information`, ISO
certificates) must never be mistaken for the datasheet. `pdfFileDetailVO.urlSign`
is an OSS signature — it is appended only for a download, never stored.

---

## 3. International — `lcsc.com`

### 3.1 Search is two calls

**Discovery** — `POST https://wmsc.lcsc.com/ftps/wm/search/v3/global`, body
`{"keyword": "…"}` (≤160 chars). `result` carries `scene`, `totalCount`,
`isToDetail`, `tipProductDetailUrlVO`, `catalogVOS`, `productSearchResultVO`.

| `scene` | Meaning | Program's action |
|---|---|---|
| `REDIRECT_PRODUCT_DETAIL` / `isToDetail: true` | the query *is* one part (verified with `C2040`) | fetch that product from the detail endpoint; one-row page |
| `FULL_MATCH` + `catalogVOS` | parts exist, grouped by category | pick a category, then the list endpoint |
| `PARTIAL_MATCH` + `catalogVOS` | fuzzy match; still grouped (a nonsense token can match ~17 500 products) | same as FULL_MATCH, but flag a fuzzy match to the UI |
| `NO_RESULT` | nothing | empty page |

**List** — `POST https://wmsc.lcsc.com/ftps/wm/product/query/list`:

```json
{"keyword":"", "globalKeyword":"STM32F103C8T6", "catalogIdList":[941], "brandIdList":[],
 "encapValueList":[], "isStock":false, "isOtherSuppliers":false, "isAsianBrand":false,
 "isDeals":false, "isRohsCert":false, "paramNameValueMap":{}, "currentPage":1, "pageSize":30}
```

**`catalogIdList` is mandatory** — an empty list is rejected with `code: 405`.
Several ids are accepted but are *not* additive: `[941, 848]` returned only 941's
rows. The program therefore queries one category at a time and offers the
category leaves as a selector.

`pageSize` may be 20/30/50/100; `pageRow` echoes it, `currPage` echoes the page.
`totalRow` is **capped at 5000** and `totalPage` is computed from a page size of
20 regardless of what was asked, so page counts must be computed locally as
`ceil(totalRow / pageSize)`.

Response: `result.{currPage, pageRow, totalPage, totalRow, dataList[]}`.

### 3.2 Search rows are complete

Each `dataList` entry already contains everything needed — no second request:

`productCode`, `productId`, `productModel`, `productNameEn`, `productIntroEn`,
`productDescEn`, `title`, `brandNameEn`, `encapStandard`, `wmCatalogId`,
`wmCatalogNameEn`, `catalogName`, `productUnit`, `minBuyNumber`, `stockNumber`,
`stockSz`, `productWeight`, `isRohsCert`, `eccn`, `isPreSale`, `isNotOverstock`,
`productArrange`, `productCycle`, `pdfUrl`, `productImages[]`,
`productPriceList[]{ladder, usdPrice, productPrice, currencySymbol}`,
`paramVOList[]{paramNameEn, paramValueEn, paramName, paramValue, isMain}`.

`usdPrice` is the price; `productPrice` is the CNY figure and must be ignored, or
the same part would show two currencies. `isShowForeignPrice: false` ⇒ no price
at all (never fall back to CNY).

### 3.3 Detail endpoint

`GET https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C2040` → same field
vocabulary as a search row, plus `currencyType: "USD"`, `parentCatalogList`,
`productWeight`, `edaSvgInfo`.

`productCode` is **case-sensitive**: `c2040` and `C0` both answer `code: 200`
with an empty `result` (no `productModel`, no params). A `code: 200` with an
empty result means *not found*; uppercase the code before asking and treat an
empty result as a miss.

---

## 4. Error and edge-case behaviour

| Situation | Observed answer | Program's response |
|---|---|---|
| unknown keyword, domestic | `code: 200`, `totalCount: 0`, empty list | empty page, not an error |
| unknown keyword, international | `scene: NO_RESULT`, `totalCount: 0` | empty page, not an error |
| oversized domestic `pageSize` | `code: 200`, `pageSize: null`, no rows | never request > 30 |
| empty international `catalogIdList` | `code: 405` | never send it; pick a category |
| lowercase `productCode` | `code: 200`, empty `result` | uppercase first; empty result = miss |
| item page for a stale `productId` | HTML without the expected product | "details unavailable", keep the search row |

Both sites answer HTTP 200 with a semantic code inside the body, so the HTTP
status alone is not a success signal.

---

## 5. Deliberate deviations from LCSC3D

LCSC3D (`AGPL-3.0`) was read as a protocol reference only; no code was copied.
Where this program differs, and why:

| Topic | LCSC3D | This program | Reason |
|---|---|---|---|
| Ladder quantities | multiplied by `theRatio`/`convesionRatio`, floored at `minBuyNumber × step` | used exactly as the site reports them | For `0603WAF1002T5E` the site reports `theRatio: 100` with `minBuyNumber: 1` and a `1–9` tier; multiplying would claim a minimum order of 100 pieces, contradicting `minBuyNumber`. The raw ladder matches what the storefront displays. |
| International paging | 20 rows stitched out of native 30-row pages | one request per page (`pageSize` 30) | The list endpoint accepts 20/30/50/100 and echoes `pageRow`; stitching is unnecessary. |
| International detail | scrape `__NEXT_DATA__` from the product page | JSON `product/detail` endpoint, HTML kept as fallback | Fewer bytes, stable field names, verified live. |
| Parameter markup | not encountered | tag-stripped | Domestic search rows embed `<SPAN …>` highlight markup in matched values. |

---

## 6. Known traps

1. **Highlight markup** in domestic search strings — strip tags, unescape entities.
2. **Certificate images** in `luceneBreviaryImageUrls` — entries under
   `/upload/public/brand/product/certificate/` are brand certificates, not the
   product. Keep only `/upload/public/product/` paths, then map
   `/product/breviary/` → `/product/source/` for the full-size image.
3. **`currePage`** is spelled that way by the site; do not "fix" it.
4. **`totalRow` cap of 5000** on the international list — a broad keyword claims
   more matches than can be paged through.
5. **`-1`** as `endPurchasedNumber` means "and up".
6. **Signatured PDF URLs** (`atta.szlcsc.com`) must not be persisted or logged;
   store the stable `/datasheet/{model}/{id}.html` viewer link or the unsigned
   `fileUrl`-derived URL instead.
7. `robots.txt` checked 2026-11-21: `lcsc.com` allows `/product-detail/` (only
   `/product-detail-v2/` is disallowed), `so.szlcsc.com` disallows only
   `/member/`, `item.szlcsc.com` allows product pages, `list.szlcsc.com` allows
   `/catalog/*.html`. The program stays on those paths and paces itself to
   human speed.
