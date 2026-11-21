"""Both backends against recorded storefront responses (no network)."""

from __future__ import annotations

import pytest
from conftest import (
    FakeResponse,
    FakeTransport,
    json_response,
    load_fixture,
    make_session,
    next_data_page,
)

from kicad_core.errors import DetailError, ParseError, RateLimitError, SearchError
from lcsc_core.domestic import DomesticBackend
from lcsc_core.international import InternationalBackend

DOM = "so.szlcsc.com"
ITEM = "item.szlcsc.com"
DISCOVERY = "search/v3/global"
LIST = "product/query/list"
DETAIL = "product/detail"


class TestDomesticSearch:
    def _backend(self, response=None, **routes):
        payload = response or load_fixture("domestic_search")
        session, transport = make_session({DOM: json_response(payload), **routes})
        return DomesticBackend(session), transport

    def test_one_post_with_the_fixed_body(self):
        backend, transport = self._backend()
        page = backend.search("C25804")
        assert len(transport.calls) == 1
        call = transport.calls[0]
        assert call["method"] == "POST"
        assert call["url"] == "https://so.szlcsc.com/query/product"
        body = call["kwargs"]["json"]
        assert len(body) == 24
        assert body["keyword"] == "C25804"
        assert body["currentPage"] == 1
        assert body["pageSize"] == 30
        assert body["catalogIdFilter"] == ""
        assert page.items[0].base.distributor_product_number == "C25804"
        assert page.total == 1 and page.pages == 1 and page.page == 1
        assert page.exact is True

    def test_category_filter_is_sent(self):
        backend, transport = self._backend()
        backend.search("10k 0603", category_id="439")
        assert transport.calls[0]["kwargs"]["json"]["catalogIdFilter"] == "439"

    def test_category_facets_are_available_to_the_ui(self):
        payload = load_fixture("domestic_search")
        payload["result"]["searchResult"]["catalogGroup"] = [
            {"label": "贴片电阻", "value": "439", "count": 1200},
            {"label": "插件电阻", "value": "440", "count": 30},
        ]
        backend, _ = self._backend(response=payload)
        page = backend.search("10k")
        assert [item.name for item in page.categories] == ["贴片电阻", "插件电阻"]
        assert page.categories[0].id == "439"

    def test_keyword_without_a_result_is_an_empty_page(self):
        payload = {"code": 200, "ok": True,
                   "result": {"searchResult": {"totalCount": 0, "pageSize": 30,
                                               "currePage": 1, "countPage": 1,
                                               "productRecordList": []}}}
        backend, _ = self._backend(response=payload)
        page = backend.search("nothing here")
        assert page.items == [] and page.total == 0 and page.empty

    def test_error_code_is_surfaced(self):
        backend, _ = self._backend(response={"code": 500, "msg": "商城繁忙"})
        with pytest.raises(SearchError) as excinfo:
            backend.search("C25804")
        assert "商城繁忙" in str(excinfo.value)

    def test_wrong_page_echo_is_rejected(self):
        payload = load_fixture("domestic_search")
        payload["result"]["searchResult"]["currePage"] = 2
        backend, _ = self._backend(response=payload)
        with pytest.raises(SearchError):
            backend.search("C25804", 1)

    def test_changed_page_size_is_rejected(self):
        payload = load_fixture("domestic_search")
        payload["result"]["searchResult"]["pageSize"] = 10
        backend, _ = self._backend(response=payload)
        with pytest.raises(SearchError):
            backend.search("C25804")

    def test_empty_page_that_claims_results_is_an_error(self):
        payload = load_fixture("domestic_search")
        payload["result"]["searchResult"]["productRecordList"] = []
        backend, _ = self._backend(response=payload)
        with pytest.raises(SearchError):
            backend.search("C25804")

    def test_blank_query_is_rejected_without_a_request(self):
        backend, transport = self._backend()
        with pytest.raises(SearchError):
            backend.search("   ")
        assert transport.calls == []


class TestDomesticDetail:
    def _backend(self, webdata=None, **routes):
        payload = load_fixture("domestic_search")
        item = next_data_page(load_fixture("domestic_item") if webdata is None else webdata)
        session, transport = make_session({
            ITEM: FakeResponse(body=item),
            DOM: json_response(payload),
            **routes,
        })
        backend = DomesticBackend(session)
        page = backend.search("C25804")
        transport.calls.clear()
        return backend, transport, page.items[0]

    def test_detail_fetches_the_item_page_by_numeric_id(self):
        backend, transport, product = self._backend()
        enriched = backend.detail(product)
        assert transport.urls() == ["https://item.szlcsc.com/26547.html"]
        assert enriched.detail_state == "enriched"
        assert len([item for item in enriched.params if item["param"] != "-"]) == 7

    def test_fetch_false_never_touches_the_network(self):
        backend, transport, product = self._backend()
        unchanged = backend.detail(product, fetch=False)
        assert transport.calls == []
        assert unchanged.detail_state == "search"
        assert unchanged.base.datasheet_url  # the search row already had it

    def test_missing_item_page_raises_detail_error(self):
        backend, _transport, product = self._backend(webdata={})
        with pytest.raises(DetailError):
            backend.detail(product)


class TestInternationalSearch:
    def _backend(self, discovery=None, listing=None):
        session, transport = make_session({
            DISCOVERY: json_response(discovery or load_fixture("international_discovery_list")),
            LIST: json_response(listing or load_fixture("international_list")),
            DETAIL: json_response(load_fixture("international_detail")),
        })
        return InternationalBackend(session), transport

    def test_keyword_search_is_discovery_then_list(self):
        backend, transport = self._backend()
        page = backend.search("STM32F103C8T6")
        assert len(transport.calls) == 2
        assert DISCOVERY in transport.urls()[0]
        assert LIST in transport.urls()[1]
        body = transport.post_bodies()[1]
        assert body["catalogIdList"] == [941]
        assert body["globalKeyword"] == "STM32F103C8T6"
        assert body["keyword"] == ""
        assert body["pageSize"] == 30
        assert page.items[0].base.distributor_product_number == "C8734"
        assert page.category_id == "941"
        assert page.categories and page.categories[0].count >= page.categories[-1].count

    def test_catalog_id_list_is_never_empty(self):
        backend, transport = self._backend()
        backend.search("STM32F103C8T6")
        for body in transport.post_bodies():
            for key, value in body.items():
                if key == "catalogIdList":
                    assert value, "the store rejects an empty catalogIdList with code 405"

    def test_page_is_forwarded(self):
        listing = load_fixture("international_list")
        listing["result"]["currPage"] = 2
        backend, transport = self._backend(listing=listing)
        page = backend.search("STM32F103C8T6", 2)
        assert transport.post_bodies()[1]["currentPage"] == 2
        assert page.page == 2

    def test_part_number_shortcut_spends_one_request(self):
        backend, transport = self._backend()
        page = backend.search("c2040")
        assert transport.urls() == ["https://wmsc.lcsc.com/ftps/wm/product/detail"]
        assert transport.calls[0]["kwargs"]["params"] == {"productCode": "C2040"}
        assert page.exact is True
        assert page.items[0].base.manufacturer_product_number == "RP2040"

    def test_unknown_part_number_falls_back_to_a_keyword_search(self):
        empty = json_response(load_fixture("international_detail_empty"))
        session, transport = make_session({
            DETAIL: empty,
            DISCOVERY: json_response(load_fixture("international_discovery_list")),
            LIST: json_response(load_fixture("international_list")),
        })
        backend = InternationalBackend(session)
        page = backend.search("C8734")
        assert page.items and page.items[0].base.distributor_product_number == "C8734"
        assert len(transport.calls) == 3  # detail, discovery, list

    def test_no_result_scene_is_an_empty_page(self):
        backend, transport = self._backend(
            discovery=load_fixture("international_discovery_empty"))
        page = backend.search("qqqzzzxxyy")
        assert page.items == [] and page.total == 0
        assert len(transport.calls) == 1, "an empty scene must not trigger a list call"

    def test_fuzzy_scene_is_reported(self):
        discovery = load_fixture("international_discovery_list")
        discovery["result"]["scene"] = "PARTIAL_MATCH"
        backend, _ = self._backend(discovery=discovery)
        page = backend.search("STM32")
        assert page.scene == "PARTIAL_MATCH"

    def test_capped_total_is_explained(self):
        listing = load_fixture("international_list")
        listing["result"]["totalRow"] = 17599
        backend, _ = self._backend(listing=listing)
        page = backend.search("STM32")
        assert page.total == 5000
        assert "5000" in page.note

    def test_wrong_page_echo_is_rejected(self):
        listing = load_fixture("international_list")
        listing["result"]["currPage"] = 7
        backend, _ = self._backend(listing=listing)
        with pytest.raises(SearchError):
            backend.search("STM32F103C8T6", 1)

    def test_category_choice_is_honoured(self):
        discovery = load_fixture("international_discovery_list")
        discovery["result"]["scene"] = "FULL_MATCH"
        result = discovery["result"]
        result["catalogVOS"] = [
            {"catalogId": 941, "catalogNameEn": "Microcontrollers", "productNum": 3},
            {"catalogId": 848, "catalogNameEn": "Evaluation Boards", "productNum": 1},
        ]
        backend, transport = self._backend(discovery=discovery)
        backend.search("STM32F103C8T6", category_id="848")
        assert transport.post_bodies()[1]["catalogIdList"] == [848]


class TestInternationalDetail:
    def test_detail_merge_keeps_identity_and_price(self):
        # The detail payload is the same part the search row came from, so the
        # merge must not swap identity or the price ladder.
        detail = load_fixture("international_detail")["result"]
        session, transport = make_session({DETAIL: json_response({"code": 200, "result": detail})})
        backend = InternationalBackend(session)
        from lcsc_core import parsers

        search = parsers.international_product(detail)
        search.base.unit_price = "US$9.99@1"
        search.detail_state = "search"
        enriched = backend.detail(search)
        assert transport.urls() == ["https://wmsc.lcsc.com/ftps/wm/product/detail"]
        assert enriched.detail_state == "enriched"
        assert enriched.base.distributor_product_number == "C2040"
        assert enriched.base.unit_price == "US$9.99@1"
        assert enriched.base.datasheet_url

    def test_detail_for_a_different_part_is_rejected(self):
        # A stale or redirected page must never be merged into another record.
        session, _transport = make_session({
            DETAIL: json_response(load_fixture("international_detail")),
        })
        backend = InternationalBackend(session)
        from lcsc_core import parsers

        row = load_fixture("international_list")["result"]["dataList"][0]  # C8734
        with pytest.raises(DetailError):
            backend.detail(parsers.international_product(row))

    def test_enriched_product_is_not_refetched(self):
        session, transport = make_session({
            DETAIL: json_response(load_fixture("international_detail")),
        })
        backend = InternationalBackend(session)
        from lcsc_core import parsers

        product = parsers.international_product(load_fixture("international_detail")["result"])
        product.detail_state = "enriched"
        again = backend.detail(product)
        assert transport.calls == []
        assert again.detail_state == "enriched"

    def test_empty_detail_result_is_a_miss(self):
        session, _ = make_session({
            DETAIL: json_response(load_fixture("international_detail_empty")),
        })
        backend = InternationalBackend(session)
        from lcsc_core import parsers

        product = parsers.international_product(
            load_fixture("international_list")["result"]["dataList"][0])
        product.detail_state = "search"
        with pytest.raises(DetailError):
            backend.detail(product)


class TestTransportBehaviour:
    def test_429_is_retried_once_then_reported(self):
        from lcsc_core.session import HttpSession

        attempts = []

        def responder(method, url, kwargs):
            attempts.append(url)
            return FakeResponse(status_code=429, headers={"Retry-After": "0"})

        transport = FakeTransport({DOM: responder})
        session = HttpSession(session=transport, min_interval=0)
        # shorten the retry wait so the test stays fast
        session._backoff = lambda seconds: None  # type: ignore[assignment]
        with pytest.raises(RateLimitError):
            session.post_json("https://so.szlcsc.com/query/product", {})
        assert len(attempts) == 2

    def test_retry_succeeds_after_one_429(self):
        from lcsc_core.session import HttpSession

        responses = [FakeResponse(status_code=503), json_response(load_fixture("domestic_search"))]
        transport = FakeTransport({DOM: responses})
        session = HttpSession(session=transport, min_interval=0)
        session._backoff = lambda seconds: None  # type: ignore[assignment]
        payload = session.post_json("https://so.szlcsc.com/query/product", {})
        assert payload["code"] == 200
        assert len(transport.calls) == 2

    def test_error_bodies_never_leak_the_url(self):
        from lcsc_core.session import HttpSession

        transport = FakeTransport({DOM: FakeResponse(status_code=403)})
        session = HttpSession(session=transport, min_interval=0)
        with pytest.raises(SearchError) as excinfo:
            session.post_json("https://so.szlcsc.com/query/product?secret=1", {})
        assert "secret" not in str(excinfo.value)
        assert "secret" not in (excinfo.value.details or "")

    def test_oversized_body_is_refused(self):
        from lcsc_core.session import HttpSession

        transport = FakeTransport({DOM: FakeResponse(body=b"x" * 4096)})
        session = HttpSession(session=transport, min_interval=0)
        with pytest.raises(SearchError):
            session.get_bytes("https://so.szlcsc.com/x", max_bytes=1024)

    def test_invalid_json_is_a_parse_error(self):
        from lcsc_core.session import HttpSession

        transport = FakeTransport({DOM: FakeResponse(body=b"<html>not json</html>")})
        session = HttpSession(session=transport, min_interval=0)
        with pytest.raises(ParseError):
            session.get_json("https://so.szlcsc.com/x")
