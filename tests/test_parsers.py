"""Parsing rules: markup, prices, parameter slots, value derivation, mapping."""

from __future__ import annotations

import pytest
from conftest import load_fixture

from kicad_core.errors import DetailError, ParseError
from kicad_core.models import PARAM_COUNT
from lcsc_core import parsers
from lcsc_core.text import (
    decimal_number,
    derive_value,
    part_number,
    product_id,
    public_url,
    quantity,
    strip_markup,
    text,
)


class TestTextHelpers:
    def test_strip_markup_removes_highlight_span(self):
        value = "<SPAN CLASS='LUCENE_HIGHLIGHT_CLASS'>10kΩ</SPAN>"
        assert strip_markup(value) == "10kΩ"

    def test_strip_markup_decodes_entities(self):
        assert strip_markup("10k&Omega; &amp; 1%") == "10kΩ & 1%"

    def test_text_collapses_whitespace_and_caps_length(self):
        assert text("  a\n\tb  ") == "a b"
        assert len(text("x" * 400, 10)) == 10

    def test_text_rejects_non_scalars(self):
        assert text(None) == ""
        assert text({"a": 1}) == ""
        assert text(True) == ""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://a.test/x.pdf", "https://a.test/x.pdf"),
            ("//a.test/x.pdf", "https://a.test/x.pdf"),
            ("http://a.test/x.pdf", ""),
            ("javascript:alert(1)", ""),
            ("https://user:pw@a.test/x", ""),
            ("", ""),
            (None, ""),
        ],
    )
    def test_public_url(self, value, expected):
        assert public_url(value) == expected

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("c25804", "C25804"),
            (" C8734 ", "C8734"),
            ("C123456789012345678", "C123456789012345678"),  # 18 digits is the maximum
            ("C1234567890123456789", ""),                     # 19 digits is too long
            ("LM324N", ""),
            ("C", ""),
        ],
    )
    def test_part_number(self, value, expected):
        assert part_number(value) == expected

    @pytest.mark.parametrize(
        "value, expected",
        [("26547", "26547"), (26547, "26547"), (0, "0"), (-1, ""), ("abc", ""), (True, "")],
    )
    def test_product_id(self, value, expected):
        assert product_id(value) == expected

    def test_quantity_rejects_open_end_and_fractions(self):
        assert quantity(-1) is None
        assert quantity("1.5") is None
        assert quantity("10") == 10
        assert quantity(None) is None

    def test_decimal_number_rejects_bad_values(self):
        assert decimal_number("1e999") is None
        assert decimal_number(-1) is None
        assert decimal_number("0.0101") == decimal_number("0.0101")
        assert str(decimal_number("0.0101")) == "0.0101"


class TestValueDerivation:
    NAMES = parsers.VALUE_PARAMETER_NAMES

    def test_ohms_are_stripped_and_uppercased(self):
        assert derive_value("MPN", [("阻值", "10kΩ")], self.NAMES) == "10K"
        assert derive_value("MPN", [("Resistance", "10kOhms")], self.NAMES) == "10K"
        assert derive_value("MPN", [("阻值", "4.7Ω")], self.NAMES) == "4.7"

    def test_other_units_are_left_alone(self):
        assert derive_value("MPN", [("容值", "100nF")], self.NAMES) == "100nF"
        assert derive_value("MPN", [("Capacitance", "10µF")], self.NAMES) == "10µF"

    def test_unrelated_parameter_falls_back_to_mpn(self):
        assert derive_value("TEST-1", [("精度", "±1%")], self.NAMES) == "TEST-1"
        assert derive_value("TEST-1", [], self.NAMES) == "TEST-1"

    def test_blank_value_falls_through_to_the_next_parameter(self):
        pairs = [("阻值", ""), ("Resistance", "1kΩ")]
        assert derive_value("MPN", pairs, self.NAMES) == "1K"


class TestParameterSlots:
    def test_pads_to_32_slots(self):
        slots = parsers.parameter_slots([("阻值", "10kΩ")])
        assert len(slots) == PARAM_COUNT
        assert slots[0] == {"param": "阻值", "value": "10kΩ"}
        assert slots[-1] == {"param": "-", "value": "-"}

    def test_truncates_to_32_slots(self):
        pairs = [(f"p{index}", f"v{index}") for index in range(40)]
        slots = parsers.parameter_slots(pairs)
        assert len(slots) == PARAM_COUNT
        assert slots[-1]["param"] == "p31"

    def test_priority_names_come_first_and_order_is_preserved_afterwards(self):
        pairs = [("电阻类型", "厚膜电阻"), ("功率", "100mW"), ("阻值", "10kΩ"), ("精度", "±1%")]
        ordered = parsers.order_parameters(pairs, parsers.KEY_SPEC_ORDER_ZH)
        assert [name for name, _ in ordered][:3] == ["阻值", "精度", "功率"]
        assert ordered[-1][0] == "电阻类型"

    def test_all_parameters_keeps_everything_reported(self):
        pairs = [(f"p{index}", "v") for index in range(40)]
        assert len(parsers.all_parameters(pairs)) == 40


class TestDomesticParsing:
    def _vo(self):
        return load_fixture("domestic_search")["result"]["searchResult"]["productRecordList"][0]

    def test_price_ladder_is_cny_and_complete(self):
        price = parsers.domestic_price(self._vo()["productVO"])
        assert price.startswith("¥0.0101@1/")
        assert price.count("/") == 4
        assert "¥0.0058@500" in price

    def test_ladder_is_capped_at_six_tiers(self):
        vo = {"isShowPrice": True,
              "productPriceList": [{"startPurchasedNumber": n, "productPrice": 0.1}
                                   for n in (1, 10, 100, 1000, 10000, 100000, 1000000)]}
        assert parsers.domestic_price(vo).count("/") == parsers.MAX_PRICE_TIERS - 1

    def test_hidden_price_is_empty_not_zero(self):
        assert parsers.domestic_price({"isShowPrice": False, "productPriceList": []}) == ""

    def test_highlight_markup_is_removed_from_parameters(self):
        row = self._vo()
        row["paramLinkedMap"]["阻值"] = "<SPAN CLASS='LUCENE_HIGHLIGHT_CLASS'>10kΩ</SPAN>"
        product = parsers.domestic_product(row)
        assert ("阻值", "10kΩ") in [(item["param"], item["value"]) for item in product.params]

    def test_images_drop_brand_certificates_and_upgrade_to_full_size(self):
        images = parsers.domestic_images(self._vo()["productVO"])
        assert images, "expected product photographs"
        assert all("/product/source/" in url for url in images)
        assert all("/brand/" not in url for url in images)

    def test_product_mapping_from_a_search_row(self):
        product = parsers.domestic_product(self._vo())
        base = product.base
        assert base.distributor_product_number == "C25804"
        assert base.manufacturer_product_number == "0603WAF1002T5E"
        assert base.value == "10K"
        assert base.package == "0603"
        assert base.manufacturer == "UNI-ROYAL(厚声)"
        assert base.distributor == "LCSC"
        assert base.part_status == "Active"
        # the search row reports 201600 as the visible stock; the ratios differ
        assert base.qty_available == "201600"
        assert base.product_url == "https://item.szlcsc.com/26547.html"
        assert base.datasheet_url.startswith("https://atta.szlcsc.com/upload/public/pdf/")
        assert base.id == "贴片电阻/0603WAF1002T5E"
        assert product.source_product_id == "26547"
        assert product.detail_state == "search"

    def test_stop_sale_flags_become_obsolete(self):
        row = load_fixture("domestic_search")["result"]["searchResult"]["productRecordList"][0]
        row["productVO"]["productUnsealVendition"] = "no"
        assert parsers.domestic_product(row).base.part_status == "Obsolete"

    def test_row_without_a_part_number_is_skipped(self):
        row = load_fixture("domestic_search")["result"]["searchResult"]["productRecordList"][0]
        row["productVO"]["productCode"] = "not-a-part"
        assert parsers.domestic_product(row) is None

    def test_item_page_enrichment_adds_parameters_and_datasheet(self):
        product = parsers.domestic_product(self._vo())
        enriched = parsers.apply_domestic_detail(product, load_fixture("domestic_item"))
        names = [item["param"] for item in enriched.params if item["param"] != "-"]
        assert "工作电压" in names and "温度系数" in names
        assert len(names) == 7
        assert enriched.base.datasheet_url.endswith("C422600_1E6D84923E4A46A82E41ADD87F860B5C.pdf")
        assert enriched.base.value == "10K"
        assert enriched.detail_state == "enriched"
        # the item page has no price ladder; the search row's must survive
        assert enriched.base.unit_price == product.base.unit_price

    def test_item_page_for_another_part_is_rejected(self):
        product = parsers.domestic_product(self._vo())
        webdata = load_fixture("domestic_item")
        webdata["productRecord"]["productCode"] = "C99999"
        with pytest.raises(ParseError):
            parsers.apply_domestic_detail(product, webdata)

    def test_empty_item_page_is_an_error(self):
        product = parsers.domestic_product(self._vo())
        with pytest.raises(DetailError):
            parsers.apply_domestic_detail(product, {})


class TestInternationalParsing:
    def _row(self):
        return load_fixture("international_list")["result"]["dataList"][0]

    def test_price_ladder_is_usd(self):
        price = parsers.international_price(self._row())
        assert price.startswith("US$1.4756@1/")
        assert "US$0.9419@1000" in price

    def test_missing_foreign_price_yields_no_price(self):
        row = dict(self._row(), isShowForeignPrice=False)
        assert parsers.international_price(row) == ""
        assert "US$" not in parsers.international_price(row)

    def test_cny_amount_is_never_used_as_usd(self):
        row = {"isShowForeignPrice": True,
               "productPriceList": [{"ladder": 1, "usdPrice": None, "productPrice": "9.99"}]}
        assert parsers.international_price(row) == ""

    def test_product_mapping_from_a_search_row(self):
        product = parsers.international_product(self._row())
        base = product.base
        assert base.distributor_product_number == "C8734"
        assert base.manufacturer_product_number == "STM32F103C8T6"
        assert base.manufacturer == "ST"
        assert base.package == "LQFP-48(7x7)"
        assert base.distributor == "LCSC International"
        assert base.qty_available == "87"
        assert base.unit_price.startswith("US$")
        assert base.product_url == "https://www.lcsc.com/product-detail/C8734.html"
        assert base.datasheet_url == self._row()["pdfUrl"]
        assert base.id == "Microcontrollers/STM32F103C8T6"
        assert base.part_status == "Active"
        # English parameter names are used, and the headline spec comes first
        assert product.params[0]["param"] == "Voltage - Supply"

    def test_detail_merge_prefers_the_richer_parameter_set(self):
        row = self._row()
        search = parsers.international_product(row)
        detail = parsers.international_product(load_fixture("international_detail")["result"])
        merged = parsers.international_merge(search, detail)
        assert merged.detail_state == "enriched"
        assert merged.base.distributor_product_number == "C8734"
        assert merged.base.datasheet_url
        assert len(merged.source_parameters) >= len(search.source_parameters)

    def test_a_code_without_the_c_prefix_is_not_a_product(self):
        assert parsers.international_product({"productCode": "8734"}) is None
        assert parsers.international_product({"productCode": ""}) is None

    def test_a_lowercase_code_is_normalised_rather_than_dropped(self):
        # The storefront is case-sensitive, so the program upper-cases it first.
        assert parsers.international_product({"productCode": "c8734"}).base \
            .distributor_product_number == "C8734"
