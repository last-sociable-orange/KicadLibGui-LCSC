# KiCad LibGen LCSC — development plan and record

**Status:** implemented (v1.0.0) · **Date:** 2026-11-21
**Approved plan:** [`APPROVED-PLAN.md`](APPROVED-PLAN.md) (kept as approved)
**Sibling:** the DigiKey front end this mirrors (outside this repository)

---

## 1. Goal

A standalone desktop program that sources component data from LCSC instead of
DigiKey, writes the *same* 80-column KiCad `components` table, and picks the
storefront from the language setting:

| Language | Storefront | Currency | Parameter language |
|---|---|---|---|
| `zh_CN` (default) | `szlcsc.com` | ¥ | Chinese |
| `en_US` | `lcsc.com` | US$ | English |

## 2. Decisions taken before implementation

| # | Decision |
|---|---|
| 1 | Public storefront endpoints only. No agent API, no key, no credential UI. |
| 2 | One language setting controls both the interface language and the storefront. |
| 3 | `UnitPrice` keeps the `price@qty` grammar with a currency symbol, max 6 tiers. |
| 4 | 32 parameter slots: headline specifications first, then the store's own order. |
| 5 | 30 results per page, `Prev`/`Next`/`Load 30 more`; no 20-from-30 stitching. |
| 6 | Batch CSV is keyed by LCSC part number only. |

## 3. Architecture

```
gui_main.py ── gui/app.py ─┬─ gui/main_window.py ─┬─ gui/widgets/results_table.py
                           │                      ├─ gui/widgets/detail_panel.py
                           │                      └─ gui/widgets/param_table.py
                           ├─ gui/database_tab.py
                           └─ gui/dialogs/{settings,batch,about}_dialog.py
services/ ── config, search_service, database_service, batch_service, logging
lcsc_core/ ─ session, routing, domestic, international, parsers, texts, cache
kicad_core/ ─ models, database (80 columns, fixed upsert), errors
```

Two rules keep this maintainable:

* **nothing above `lcsc_core/` knows which storefront is in use** — the GUI only
  sees `ProductInfo` records and a `SearchPage`, exactly as it saw DigiKey
  results before;
* **nothing below `services/` touches Tk** — the backends, parsers and parsers
  are testable without a display, and the test suite runs entirely from recorded
  responses.

## 4. Phases

| Phase | Content | State |
|---|---|---|
| 0 | Protocol lock-down: `tools/probe_endpoints.py`, 52 live checks, recorded fixtures, `docs/PROTOCOL.md` | done |
| 1 | `kicad_core` carried over; `lcsc_core` session/routing/parsers/backends; `services/config.py` + `search_service.py`; headless CLI | done |
| 2 | GUI shell, bilingual text table, search/save flow, in-place language switch | done |
| 3 | Database tab (browse/filter/edit/delete/duplicates), detail enrichment with caching, paging controls | done |
| 4 | Batch import (C-number CSV), settings dialog, on-disk response cache | done |
| 5 | PyInstaller spec + build scripts, README, self-test, lint, verification, commit | done |

## 5. Deviations from the approved plan (all improvements)

| Plan said | Built | Why |
|---|---|---|
| Domestic datasheet needs the item-page fetch | Taken from the **search row**, which already carries `fileTypeVOList` | One fewer request per part; verified live and by fixture |
| `lcsc_core/text.py` handles the ladder | Ladder logic lives in `parsers.py` next to the other mapping rules | It needs both symbol and currency context |
| A response cache was Phase 4 "later" | Implemented in `lcsc_core/cache.py` and wired through Settings | The Settings dialog advertises a cache lifetime; a button that does nothing would be a lie |
| Batch CSV keeps `manufacturer_product_number` as the header name | Header is `lcsc_part_number`, legacy name accepted as an alias with **C-number validation** | The key genuinely changed; accepting MPNs silently would break the "one request per row" property |
| `TaskRunner` was single-job | Added `submit_background` for detail enrichment | A 1 s detail fetch must not block a new search, and enrichment must never clear the search's busy flag |
| International detail scrapes `__NEXT_DATA__` | JSON `/ftps/wm/product/detail` endpoint, HTML scrape only as a fallback | Verified live; smaller responses, stable field names |

## 6. Verification record (2026-11-21)

| Check | Result |
|---|---|
| `python tools/probe_endpoints.py` | 52/52 live checks pass; fixtures written |
| `pytest` | 168 tests pass, offline, no network |
| `ruff check .` | clean |
| `python gui_main.py --self-test` | `SELF-TEST OK` |
| `python gui_main.py --smoke-test` | window builds and closes |
| Live search, both languages | `C25804` → 7 parameters + datasheet; `C2040` → 9 parameters, USD ladder |
| Live paging | domestic page 2/50; international page 2/24 with a category filter |
| In-place language switch | relabels, switches storefront, clears foreign results |
| Dialogs | settings (both languages), batch import with a deliberately invalid row |
| One-file build | `build\kicad_lib_gen_lcsc.spec` builds `dist\KiCadLibGenLCSC.exe` (13.3 MB) with PyInstaller 6.22.3 |

**Caveat on the packaged binary:** it was built successfully, but this
development environment refuses to *execute* a freshly built unsigned executable
(`Access is denied`, and the same build in a restricted sandbox also cannot use
`%TEMP%` for the one-file extraction), so the packaged `--self-test` has not been
observed here. Run `dist\KiCadLibGenLCSC.exe --self-test` once on a normal
machine, or `python gui_main.py --self-test`, before publishing an artifact. The
same check is the last step of both build scripts.

## 7. Deliberate non-goals

Login, favourites, cart, orders, 3D models, symbol/footprint generation (that is
LCSC3D's job), PDF downloading beyond storing the URL, and any agent-API key
handling.
