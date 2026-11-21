"""Language routing: which storefront, which currency, which product URL."""

from __future__ import annotations

import pytest

from lcsc_core import routing
from lcsc_core.domestic import DomesticBackend
from lcsc_core.international import InternationalBackend


class TestLanguage:
    @pytest.mark.parametrize(
        "value, expected",
        [("zh_CN", "zh_CN"), ("en_US", "en_US"), ("", "zh_CN"), (None, "zh_CN"),
         ("de_DE", "zh_CN"), ("EN_us", "zh_CN")],
    )
    def test_normalise_language(self, value, expected):
        assert routing.normalise_language(value) == expected

    def test_default_is_chinese(self):
        assert routing.DEFAULT_LANGUAGE == "zh_CN"

    def test_every_language_has_a_label(self):
        for code, _label in routing.LANGUAGES:
            assert routing.normalise_language(code) == code


class TestBackendSelection:
    def test_chinese_uses_the_domestic_storefront(self):
        backend = routing.create_backend("zh_CN")
        try:
            assert isinstance(backend, DomesticBackend)
            assert backend.site == "szlcsc.com"
            assert backend.currency == "¥"
            assert backend.language == "zh_CN"
        finally:
            backend.close()

    def test_english_uses_the_international_storefront(self):
        backend = routing.create_backend("en_US")
        try:
            assert isinstance(backend, InternationalBackend)
            assert backend.site == "lcsc.com"
            assert backend.currency == "US$"
            assert backend.language == "en_US"
        finally:
            backend.close()

    def test_unknown_language_falls_back_to_chinese(self):
        backend = routing.create_backend("fr_FR")
        try:
            assert isinstance(backend, DomesticBackend)
        finally:
            backend.close()

    def test_helpers_follow_the_language(self):
        assert routing.site_for("en_US") == "lcsc.com"
        assert routing.site_for("zh_CN") == "szlcsc.com"
        assert routing.currency_for("en_US") == "US$"
        assert routing.currency_for("zh_CN") == "¥"


class TestStorefrontUrl:
    def test_international_product_page(self):
        assert routing.storefront_url("en_US", "C2040") == (
            "https://www.lcsc.com/product-detail/C2040.html")

    def test_domestic_search_page(self):
        assert routing.storefront_url("zh_CN", "C25804") == (
            "https://so.szlcsc.com/global.html?k=C25804")

    def test_non_part_falls_back_to_the_home_page(self):
        assert routing.storefront_url("en_US", "LM324N") == "https://www.lcsc.com"
        assert routing.storefront_url("zh_CN", "") == "https://www.szlcsc.com"

    def test_part_number_is_normalised(self):
        assert routing.storefront_url("en_US", " c2040 ") == (
            "https://www.lcsc.com/product-detail/C2040.html")
