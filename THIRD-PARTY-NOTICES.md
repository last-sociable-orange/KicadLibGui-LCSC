# Third-party notices

KiCad LibGen LCSC is distributed under the MIT licence (see `LICENSE`).

## Derived from KiCad LibGen (MIT)

The KiCad `components.db` contract and the desktop shell are carried over from
[`last-sociable-orange/kicad_lib_gen`](https://github.com/last-sociable-orange/kicad_lib_gen)
and its MIT-licensed GUI front end (`KicadLibGui`), both by the same authors:

| Carried over | Files |
|---|---|
| The 80-column `components` table, its upsert and schema validation | `kicad_core/models.py`, `kicad_core/database.py` |
| Part of the shell: theme, background worker, widget helpers, banner | `gui/theme.py`, `gui/worker.py`, `gui/assets.py`, `gui/utils.py`, `gui/widgets/__init__.py`, `gui/widgets/banner.py` |
| Service patterns: short-lived SQLite connections, rotating logs, settings file | `services/database_service.py`, `services/logging_setup.py`, `services/config.py` |
| Icons in `assets/` | `assets/icons/*`, `assets/app.png`, `assets/app.ico` |

The DigiKey client, the OAuth flow, the DigiKey parser and the terminal CLI of
that project are **not** part of this program.

## Storefront protocol (re-implemented, not copied)

The LCSC/szlcsc protocol implemented in `lcsc_core/` was established by reading
[`LCSC3D`](https://github.com/) (AGPL-3.0-or-later) as a *behavioural reference*
and then verified independently against the live sites on 2026-11-21 with
`tools/probe_endpoints.py`. What was taken is protocol knowledge — endpoint URLs,
parameter names, response field names, header sets and validation rules — which is
not copyrightable expression. **No LCSC3D source code, docstring or error message
is reproduced here**, and every parser, request builder and error path in
`lcsc_core/` was written for this program.

Deliberate behavioural differences from that reference are listed in
`docs/PROTOCOL.md` §5 (price ladder handling, paging, the detail endpoint, and
parameter markup).

Because of this, the program does **not** inherit LCSC3D's AGPL obligations. If
you ever paste code from that project into this one, that changes: the copy would
be AGPL-3.0-or-later and this project would have to follow.

## Runtime dependencies

| Component | Licence | Use |
|---|---|---|
| [requests](https://requests.readthedocs.io/) | Apache-2.0 | HTTP client |
| [urllib3](https://urllib3.readthedocs.io/) | MIT | transport under `requests` |
| [certifi](https://certifi.io/) | MPL-2.0 | CA bundle used by `requests` for TLS verification |
| [charset-normalizer](https://github.com/Ousret/charset_normalizer), [idna](https://github.com/kjd/idna) | MIT / BSD-3-Clause | `requests` dependencies |
| Tcl/Tk | BSD-style | the GUI toolkit, bundled with CPython |

Build-time only: PyInstaller (GPL-2.0 with a bootloader exception), pytest
(MIT), ruff (MIT), Pillow (MIT-0 / HPND).

## Data

Product data, prices, stock figures and datasheet links belong to the respective
manufacturers and to LCSC. They are fetched at runtime and written only into the
user's local database; nothing is redistributed with this program. The fixtures in
`tests/fixtures/` are public catalogue responses with no account, cookie or
personal data.
