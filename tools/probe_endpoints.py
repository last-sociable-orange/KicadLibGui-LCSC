"""Phase 0 protocol probe for the LCSC storefront endpoints.

Independent of :mod:`lcsc_core` on purpose: this script is the evidence that the
protocol described in ``docs/PROTOCOL.md`` still holds, so it must not share code
with the implementation it is meant to validate.

It performs one request per endpoint, prints a PASS/FAIL report, and writes
trimmed, sanitised response fixtures into ``tests/fixtures/`` for the offline
test suite.

Usage (from the project root, inside the workspace virtual environment)::

    python tools/probe_endpoints.py                # verify + write fixtures
    python tools/probe_endpoints.py --check        # verify only, no writes
    python tools/probe_endpoints.py --verbose      # print response key dumps

Nothing here authenticates, and no account data is read: every endpoint used by
the program is the anonymous public catalogue.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
TIMEOUT = 30

DOMESTIC_SEARCH_URL = "https://so.szlcsc.com/query/product"
DOMESTIC_ITEM_URL = "https://item.szlcsc.com/{product_id}.html"
DOMESTIC_CATEGORIES_URL = (
    "https://staticdata.szlcsc.com/common/data/resource-catalog-list-new.json"
)
INTL_DISCOVERY_URL = "https://wmsc.lcsc.com/ftps/wm/search/v3/global"
INTL_LIST_URL = "https://wmsc.lcsc.com/ftps/wm/product/query/list"
INTL_DETAIL_URL = "https://wmsc.lcsc.com/ftps/wm/product/detail"
INTL_HOME = "https://www.lcsc.com"

DOMESTIC_PAGE_SIZE = 30
INTL_PAGE_SIZE = 30

#: The storefront rejects other page sizes by answering ``code: 200`` with a null
#: ``pageSize`` and an empty list, so the limit is asserted, not assumed.
DOMESTIC_MAX_PAGE_SIZE = 30

DOMESTIC_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json,text/html,*/*",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://so.szlcsc.com",
    "Referer": "https://so.szlcsc.com/",
}
INTL_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json,text/html,*/*",
    "Content-Type": "application/json",
    "Origin": INTL_HOME,
    "Referer": INTL_HOME + "/",
    "Accept-Language": "en-US,en;q=0.9",
}


def domestic_body(keyword: str, page: int, size: int) -> dict[str, Any]:
    """The storefront's fixed 24-key search body (empty = no filter)."""
    return {
        "catalogIdFilter": "",
        "brandIdFilter": "",
        "standardFilter": "",
        "arrangeFilter": "",
        "labelFilter": "",
        "authenticationFilter": "",
        "sortNumber": 0,
        "satisfyStockType": "",
        "startPrice": "",
        "endPrice": "",
        "demandNumber": "",
        "spotFilter": 1,
        "discountFilter": 1,
        "hasDataFile": False,
        "brandPlaceFilter": "",
        "brandOriginFilter": "",
        "secondKeyword": "",
        "smtLabelFilter": "",
        "queryProductTypeCode": "",
        "lastParamName": "",
        "keyword": keyword,
        "currentPage": page,
        "pageSize": size,
        "queryParameterValue": "",
    }


class _NextData(HTMLParser):
    """Collect the text of ``<script id="__NEXT_DATA__">``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.inside = False
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.inside = True

    def handle_data(self, data):
        if self.inside:
            self.chunks.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False


class Report:
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, ok, detail))
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f" - {detail}" if detail and not ok else ""))
        if ok and detail and self.verbose:
            print(f"       {detail}")
        return ok

    def note(self, text: str) -> None:
        if self.verbose:
            print(f"       {text}")

    def summary(self) -> int:
        failed = [name for name, ok, _ in self.results if not ok]
        print()
        print(f"{len(self.results) - len(failed)}/{len(self.results)} checks passed")
        if failed:
            print("failed: " + ", ".join(failed))
            return 1
        return 0


def _json(response: requests.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def flatten_catalogs(rows: Any, out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Leaves of the international ``catalogVOS`` tree, with their product counts."""
    out = [] if out is None else out
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        children = row.get("childCatelogs") or row.get("childCatalogs")
        if children:
            flatten_catalogs(children, out)
        elif isinstance(row.get("catalogId"), int):
            out.append(
                {
                    "id": row["catalogId"],
                    "name": row.get("catalogNameEn") or row.get("catalogName"),
                    "count": row.get("productNum") or 0,
                }
            )
    return out


# ---------------------------------------------------------------------------
# fixture trimming
# ---------------------------------------------------------------------------


def _search_envelope(payload: dict[str, Any], keep_rows: int) -> dict[str, Any]:
    result = payload.get("result") or {}
    page = result.get("searchResult") or {}
    rows = (page.get("productRecordList") or [])[:keep_rows]
    keep_page = {
        key: page.get(key)
        for key in ("totalCount", "pageSize", "currePage", "countPage", "productRecordList")
    }
    keep_page["productRecordList"] = rows
    return {"code": payload.get("code"), "ok": payload.get("ok"), "result": {"searchResult": keep_page}}


def _item_webdata(webdata: dict[str, Any]) -> dict[str, Any]:
    record = dict(webdata.get("productRecord") or {})
    groups = []
    for group in record.get("fileTypeVOList") or []:
        if isinstance(group, dict) and group.get("fileType") == "pdf_property" and not groups:
            groups.append(group)
    record["fileTypeVOList"] = groups
    return {
        "productRecord": record,
        "paramList": webdata.get("paramList"),
        "pdfFileDetailVO": webdata.get("pdfFileDetailVO"),
        "totalStockNumber": webdata.get("totalStockNumber"),
        "smtStockNumber": webdata.get("smtStockNumber"),
    }


def _intl_row(row: dict[str, Any]) -> dict[str, Any]:
    """Keep the fields the program reads, drop per-request highlighting noise."""
    keep = (
        "productCode", "productId", "productModel", "productNameEn", "productIntroEn",
        "productDescEn", "title", "brandNameEn", "encapStandard", "wmCatalogId",
        "wmCatalogNameEn", "catalogName", "productUnit", "minBuyNumber", "maxBuyNumber",
        "stockNumber", "stockSz", "isShowForeignPrice", "currencyType", "productWeight",
        "isRohsCert", "eccn", "isPreSale", "isNotOverstock", "productArrange", "productCycle",
        "smtLabel", "pdfUrl", "paramVOList", "productPriceList", "productImages",
        "productImageUrl", "productImageUrlBig", "matchType", "url",
    )
    return {key: row.get(key) for key in keep}


def _trim_categories(payload: dict[str, Any], max_children: int = 2) -> dict[str, Any]:
    result = payload.get("result") or {}

    def node(raw: Any, depth: int) -> Any:
        if not isinstance(raw, dict):
            return None
        if depth >= max_children:
            return {"catalogId": raw.get("catalogId"), "catalogName": raw.get("catalogName")}
        return {
            "catalogId": raw.get("catalogId"),
            "catalogName": raw.get("catalogName"),
            "sonCatalogList": [node(child, depth + 1) for child in (raw.get("sonCatalogList") or [])[:max_children]],
        }

    buckets = {}
    for index, (name, value) in enumerate(result.items()):
        if index >= 3:
            break
        buckets[name] = node(value, 0)
    return {"code": payload.get("code"), "result": buckets}


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


def probe_domestic_search(session: requests.Session, report: Report, fixtures: Path) -> None:
    print("\n-- domestic keyword search --")
    started = time.monotonic()
    response = session.post(
        DOMESTIC_SEARCH_URL, json=domestic_body("C25804", 1, DOMESTIC_PAGE_SIZE), timeout=TIMEOUT
    )
    payload = _json(response)
    page = (payload.get("result") or {}).get("searchResult") or {}
    rows = page.get("productRecordList") or []
    report.check("POST so.szlcsc.com/query/product -> HTTP 200", response.status_code == 200,
                 f"HTTP {response.status_code}")
    report.check("envelope code == 200", payload.get("code") == 200, f"code={payload.get('code')}")
    report.check("searchResult.productRecordList is a list", isinstance(rows, list))
    ok = report.check("exact C-number returns at least one row", bool(rows), f"{len(rows)} rows")
    if ok:
        row = rows[0]
        vo = row.get("productVO") or {}
        report.check("row has productVO dict", bool(vo))
        report.check("productVO.productCode matches the query",
                     str(vo.get("productCode", "")).upper() == "C25804", str(vo.get("productCode")))
        for field in ("productId", "productModel", "productGradePlateName", "encapsulationModel",
                      "productType", "productPriceList", "minBuyNumber", "theRatio", "productUnit"):
            report.check(f"productVO.{field} present", field in vo)
        report.check("row.paramLinkedMap present", isinstance(row.get("paramLinkedMap"), dict),
                     f"{len(row.get('paramLinkedMap') or {})} params")
        report.check("row.totalStockNumber present", row.get("totalStockNumber") is not None)
        tiers = vo.get("productPriceList") or []
        report.check("price ladder has break quantities",
                     bool(tiers) and tiers[0].get("startPurchasedNumber") is not None,
                     json.dumps(tiers[:2], ensure_ascii=False))
    report.note(f"elapsed {time.monotonic() - started:.2f}s")
    if fixtures is not None and rows:
        write_json(fixtures / "domestic_search.json", _search_envelope(payload, keep_rows=1))

    # paging
    second = _json(session.post(
        DOMESTIC_SEARCH_URL, json=domestic_body("10k 0603 resistor", 2, DOMESTIC_PAGE_SIZE), timeout=TIMEOUT
    ))
    page2 = (second.get("result") or {}).get("searchResult") or {}
    report.check("currePage echoes the requested page", page2.get("currePage") == 2,
                 f"currePage={page2.get('currePage')}")
    report.check("page 2 returns pageSize rows",
                 len(page2.get("productRecordList") or []) == DOMESTIC_PAGE_SIZE,
                 f"{len(page2.get('productRecordList') or [])} rows")
    report.check("countPage present", isinstance(page2.get("countPage"), int),
                 f"countPage={page2.get('countPage')}")

    # the page-size ceiling
    over = _json(session.post(
        DOMESTIC_SEARCH_URL, json=domestic_body("10k 0603 resistor", 1, 100), timeout=TIMEOUT
    ))
    over_page = (over.get("result") or {}).get("searchResult") or {}
    report.check(f"pageSize {DOMESTIC_MAX_PAGE_SIZE} is the ceiling (100 yields no rows)",
                 not (over_page.get("productRecordList") or []),
                 f"pageSize={over_page.get('pageSize')} rows={len(over_page.get('productRecordList') or [])}")

    if fixtures is not None:
        first_page = _json(session.post(
            DOMESTIC_SEARCH_URL, json=domestic_body("10k 0603 resistor", 1, DOMESTIC_PAGE_SIZE), timeout=TIMEOUT
        ))
        write_json(fixtures / "domestic_search_page.json", _search_envelope(first_page, keep_rows=3))

    # no-result keyword
    empty = _json(session.post(
        DOMESTIC_SEARCH_URL, json=domestic_body("qqqzzzxxyy-no-such-part", 1, DOMESTIC_PAGE_SIZE), timeout=TIMEOUT
    ))
    empty_page = (empty.get("result") or {}).get("searchResult") or {}
    report.check("no-result keyword returns code 200 with an empty list",
                 empty.get("code") == 200 and not (empty_page.get("productRecordList") or []),
                 f"code={empty.get('code')} total={empty_page.get('totalCount')}")


def probe_domestic_item(session: requests.Session, report: Report, fixtures: Path) -> None:
    print("\n-- domestic item page --")
    url = DOMESTIC_ITEM_URL.format(product_id=26547)
    response = session.get(url, headers=DOMESTIC_HEADERS, timeout=TIMEOUT)
    report.check(f"GET {url} -> HTTP 200", response.status_code == 200, f"HTTP {response.status_code}")
    response.encoding = "utf-8"
    parser = _NextData()
    parser.feed(response.text)
    ok = report.check("<script id=\"__NEXT_DATA__\"> present", bool(parser.chunks))
    if not ok:
        return
    try:
        data = json.loads("".join(parser.chunks))
    except ValueError as exc:
        report.check("__NEXT_DATA__ is valid JSON", False, str(exc))
        return
    webdata = ((data.get("props") or {}).get("pageProps") or {}).get("webData") or {}
    report.check("props.pageProps.webData present", bool(webdata), ", ".join(list(webdata)[:6]))
    record = webdata.get("productRecord") or {}
    report.check("webData.productRecord present", bool(record))
    report.check("productRecord.productCode present", bool(record.get("productCode")))
    params = webdata.get("paramList") or []
    report.check("webData.paramList carries the full parameter set",
                 isinstance(params, list) and len(params) >= 2, f"{len(params)} params")
    groups = [g for g in (record.get("fileTypeVOList") or [])
              if isinstance(g, dict) and g.get("fileType") == "pdf_property"]
    report.check("a pdf_property datasheet group exists", bool(groups),
                 f"{len(record.get('fileTypeVOList') or [])} groups")
    if groups:
        files = groups[0].get("detailVOList") or []
        report.check("datasheet group has files", bool(files), json.dumps(files[:1], ensure_ascii=False))
    report.check("productPriceList is absent on the item page (price comes from the search row)",
                 record.get("productPriceList") is None)
    if fixtures is not None:
        write_json(fixtures / "domestic_item.json", _item_webdata(webdata))


def probe_domestic_categories(session: requests.Session, report: Report, fixtures: Path) -> None:
    print("\n-- domestic category tree --")
    response = session.get(DOMESTIC_CATEGORIES_URL, headers=DOMESTIC_HEADERS, timeout=TIMEOUT)
    payload = _json(response)
    result = payload.get("result")
    report.check("GET resource-catalog-list-new.json -> code 200", payload.get("code") == 200,
                 f"code={payload.get('code')} HTTP {response.status_code}")
    report.check("category payload is a dict of buckets", isinstance(result, dict),
                 f"{len(result) if isinstance(result, dict) else 0} buckets")
    if fixtures is not None and isinstance(result, dict):
        write_json(fixtures / "domestic_categories.json", _trim_categories(payload))


def probe_international(session: requests.Session, report: Report, fixtures: Path) -> None:
    print("\n-- international discovery / list / detail --")
    exact = _json(session.post(INTL_DISCOVERY_URL, json={"keyword": "C2040"},
                               headers=INTL_HEADERS, timeout=TIMEOUT))
    exact_result = exact.get("result") or {}
    report.check("discovery POST /ftps/wm/search/v3/global -> code 200", exact.get("code") == 200,
                 f"code={exact.get('code')}")
    report.check("a C-number query resolves straight to one product",
                 exact_result.get("isToDetail") is True
                 and (exact_result.get("tipProductDetailUrlVO") or {}).get("productCode") == "C2040",
                 json.dumps(exact_result.get("tipProductDetailUrlVO"), ensure_ascii=False))
    if fixtures is not None:
        write_json(fixtures / "international_discovery_detail.json", exact)

    keyword = "STM32F103C8T6"
    discovery = _json(session.post(INTL_DISCOVERY_URL, json={"keyword": keyword},
                                   headers=INTL_HEADERS, timeout=TIMEOUT))
    found = discovery.get("result") or {}
    leaves = sorted(flatten_catalogs(found.get("catalogVOS")), key=lambda item: -item["count"])
    report.check("a keyword query returns a catalog tree", bool(leaves), json.dumps(leaves[:3]))
    report.check("discovery reports a scene", isinstance(found.get("scene"), str), str(found.get("scene")))
    if fixtures is not None:
        write_json(fixtures / "international_discovery_list.json", discovery)

    # A short nonsense token has no catalogue path, so the store answers with the
    # explicit empty scene. Longer hyphenated strings fuzzy-match into PARTIAL_MATCH
    # with thousands of rows, which is worth knowing but useless as a fixture.
    none = _json(session.post(INTL_DISCOVERY_URL, json={"keyword": "qqqzzzxxyy"},
                              headers=INTL_HEADERS, timeout=TIMEOUT))
    none_result = none.get("result") or {}
    report.check("an impossible keyword reports an empty scene",
                 none_result.get("scene") == "NO_RESULT"
                 and none_result.get("totalCount") in (0, None)
                 and not flatten_catalogs(none_result.get("catalogVOS")),
                 f"scene={none_result.get('scene')} total={none_result.get('totalCount')}")
    if fixtures is not None:
        write_json(fixtures / "international_discovery_empty.json", none)

    if not leaves:
        report.check("catalog list query", False, "no catalog leaves to test with")
        return
    chosen = leaves[0]
    listing = _json(session.post(
        INTL_LIST_URL,
        json={
            "keyword": "", "globalKeyword": keyword, "catalogIdList": [chosen["id"]],
            "brandIdList": [], "encapValueList": [], "isStock": False, "isOtherSuppliers": False,
            "isAsianBrand": False, "isDeals": False, "isRohsCert": False, "paramNameValueMap": {},
            "currentPage": 1, "pageSize": INTL_PAGE_SIZE,
        },
        headers=INTL_HEADERS, timeout=TIMEOUT,
    ))
    listing_result = listing.get("result") or {}
    rows = listing_result.get("dataList") or []
    report.check("POST /ftps/wm/product/query/list -> code 200 and rows",
                 listing.get("code") == 200 and bool(rows),
                 f"code={listing.get('code')} rows={len(rows)}")
    report.check("pageRow echoes pageSize", listing_result.get("pageRow") == INTL_PAGE_SIZE,
                 f"pageRow={listing_result.get('pageRow')}")
    report.check("currPage echoes the request", listing_result.get("currPage") == 1,
                 f"currPage={listing_result.get('currPage')}")
    report.check("totalRow present", listing_result.get("totalRow") is not None,
                 f"totalRow={listing_result.get('totalRow')}")
    if rows:
        row = rows[0]
        report.check("search rows already carry paramVOList",
                     isinstance(row.get("paramVOList"), list) and bool(row.get("paramVOList")),
                     f"{len(row.get('paramVOList') or [])} params")
        report.check("search rows already carry pdfUrl", bool(row.get("pdfUrl")), str(row.get("pdfUrl"))[:60])
        report.check("search rows already carry a USD ladder",
                     any(isinstance(price, dict) and price.get("usdPrice") is not None
                         for price in (row.get("productPriceList") or [])))
    if fixtures is not None and rows:
        write_json(
            fixtures / "international_list.json",
            {
                "code": listing.get("code"),
                "request": {"keyword": keyword, "catalog_id": chosen["id"], "page": 1,
                            "page_size": INTL_PAGE_SIZE},
                "result": {
                    "currPage": listing_result.get("currPage"),
                    "pageRow": listing_result.get("pageRow"),
                    "totalRow": listing_result.get("totalRow"),
                    "totalPage": listing_result.get("totalPage"),
                    "dataList": [_intl_row(item) for item in rows[:3]],
                },
            },
        )

    unsigned = _json(session.post(
        INTL_LIST_URL,
        json={
            "keyword": "", "globalKeyword": keyword, "catalogIdList": [], "brandIdList": [],
            "encapValueList": [], "isStock": False, "isOtherSuppliers": False, "isAsianBrand": False,
            "isDeals": False, "isRohsCert": False, "paramNameValueMap": {}, "currentPage": 1,
            "pageSize": INTL_PAGE_SIZE,
        },
        headers=INTL_HEADERS, timeout=TIMEOUT,
    ))
    report.check("an empty catalogIdList is rejected (catalog scoping is mandatory)",
                 unsigned.get("code") != 200, f"code={unsigned.get('code')}")

    detail = _json(session.get(INTL_DETAIL_URL, params={"productCode": "C2040"},
                               headers=INTL_HEADERS, timeout=TIMEOUT))
    product = detail.get("result") or {}
    report.check("GET /ftps/wm/product/detail -> code 200 with a product", detail.get("code") == 200
                 and product.get("productCode") == "C2040", f"code={detail.get('code')}")
    report.check("detail carries paramVOList", bool(product.get("paramVOList")),
                 f"{len(product.get('paramVOList') or [])} params")
    report.check("detail carries pdfUrl", bool(product.get("pdfUrl")))
    report.check("detail is priced in USD", product.get("currencyType") == "USD",
                 str(product.get("currencyType")))
    if fixtures is not None:
        write_json(fixtures / "international_detail.json", detail)

    lower = _json(session.get(INTL_DETAIL_URL, params={"productCode": "c2040"},
                              headers=INTL_HEADERS, timeout=TIMEOUT))
    lower_product = lower.get("result") or {}
    report.check("a lowercase C-number yields an empty result (uppercase before asking)",
                 lower.get("code") == 200 and not lower_product.get("productModel"),
                 f"model={lower_product.get('productModel')!r}")
    if fixtures is not None:
        write_json(fixtures / "international_detail_empty.json", lower)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"       wrote {path.relative_to(path.parents[2])} ({path.stat().st_size} bytes)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the LCSC storefront protocol")
    parser.add_argument("--check", action="store_true", help="verify only, do not write fixtures")
    parser.add_argument("--verbose", action="store_true", help="print response key dumps")
    parser.add_argument("--out-dir", default="tests/fixtures", help="fixture directory")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    fixtures = None if args.check else (root / args.out_dir).resolve()
    report = Report(args.verbose)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    print(f"probing LCSC storefront endpoints ({time.strftime('%Y-%m-%d %H:%M:%S')})")
    try:
        probe_domestic_search(session, report, fixtures)
        probe_domestic_item(session, report, fixtures)
        probe_domestic_categories(session, report, fixtures)
        probe_international(session, report, fixtures)
    except requests.RequestException as exc:
        report.check("network", False, str(exc))
    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
