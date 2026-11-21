"""SearchService: language switching, backend reuse and the detail cache."""

from __future__ import annotations

import pytest
from conftest import json_response, load_fixture, make_session

from kicad_core.errors import DetailError, SearchError
from lcsc_core.domestic import DomesticBackend
from lcsc_core.international import InternationalBackend
from services.search_service import SearchService


def _service(routes, language="zh_CN"):
    session, transport = make_session(routes)
    return SearchService(language, session=session), transport


class TestLanguageSwitching:
    def test_starts_on_the_requested_storefront(self):
        service, _ = _service({"so.szlcsc.com": json_response(load_fixture("domestic_search"))})
        try:
            assert service.language == "zh_CN"
            assert service.site == "szlcsc.com"
            assert service.currency == "¥"
        finally:
            service.close()

    def test_switching_rebuilds_the_backend_and_reports_the_change(self):
        service, _ = _service({"so.szlcsc.com": json_response(load_fixture("domestic_search"))})
        try:
            assert service.set_language("en_US") is True
            assert isinstance(service._backend, InternationalBackend)
            assert service.site == "lcsc.com"
            assert service.currency == "US$"
            assert service.set_language("en_US") is False
            assert service.set_language("zh_CN") is True
            assert isinstance(service._backend, DomesticBackend)
        finally:
            service.close()

    def test_unknown_language_falls_back_to_chinese(self):
        service, _ = _service({"so.szlcsc.com": json_response(load_fixture("domestic_search"))})
        try:
            service.set_language("ja_JP")
            assert service.language == "zh_CN"
        finally:
            service.close()


class TestSearch:
    def test_passes_through_the_backend_page(self):
        service, transport = _service(
            {"so.szlcsc.com": json_response(load_fixture("domestic_search"))})
        try:
            page = service.search("C25804")
            assert page.items[0].base.distributor_product_number == "C25804"
            assert len(transport.calls) == 1
        finally:
            service.close()

    def test_errors_propagate_as_app_errors(self):
        service, _ = _service(
            {"so.szlcsc.com": json_response({"code": 500, "msg": "busy"})})
        try:
            with pytest.raises(SearchError):
                service.search("C25804")
        finally:
            service.close()


class TestDetailCache:
    def _service(self):
        return _service({
            "item.szlcsc.com": __import__("conftest").FakeResponse(
                body=__import__("conftest").next_data_page(load_fixture("domestic_item"))),
            "so.szlcsc.com": json_response(load_fixture("domestic_search")),
        })

    def test_detail_is_fetched_once_and_reused(self):
        service, transport = self._service()
        try:
            product = service.search("C25804").items[0]
            first = service.detail(product)
            assert first.detail_state == "enriched"
            assert len(transport.calls) == 2  # search + item page
            second = service.detail(product)
            assert second.detail_state == "enriched"
            assert len(transport.calls) == 2, "the cached detail must not refetch"
            assert [p["param"] for p in second.params][:3] == [p["param"] for p in first.params][:3]
        finally:
            service.close()

    def test_cache_is_dropped_when_the_language_changes(self):
        service, _transport = self._service()
        try:
            product = service.search("C25804").items[0]
            service.detail(product)
            service.set_language("en_US")
            assert service._details == {}
        finally:
            service.close()

    def test_enrich_safely_degrades_instead_of_raising(self):
        service, _ = _service({
            "item.szlcsc.com": json_response({"code": 500}),
            "so.szlcsc.com": json_response(load_fixture("domestic_search")),
        })
        try:
            product = service.search("C25804").items[0]
            result, warning = service.enrich_safely(product)
            assert result.base.distributor_product_number == "C25804"
            assert warning
        finally:
            service.close()

    def test_detail_failure_type(self):
        service, _ = _service({
            "item.szlcsc.com": json_response({"code": 500}),
            "so.szlcsc.com": json_response(load_fixture("domestic_search")),
        })
        try:
            product = service.search("C25804").items[0]
            with pytest.raises(DetailError):
                service.detail(product)
        finally:
            service.close()


class TestConfigure:
    def test_transport_settings_are_applied_to_the_live_session(self):
        service, _ = _service(
            {"so.szlcsc.com": json_response(load_fixture("domestic_search"))})
        try:
            service.configure(timeout=45, min_interval=1.5)
            assert service._session.timeout == 45
            assert service._session.min_interval == 1.5
        finally:
            service.close()
