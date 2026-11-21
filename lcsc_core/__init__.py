"""LCSC data source: one :class:`Backend` per storefront, one record shape.

```python
from lcsc_core import create_backend, normalise_language

backend = create_backend("zh_CN")          # szlcsc.com
page = backend.search("10k 0603 resistor")
product = backend.detail(page.items[0])    # item page: full parameters + datasheet
```

Everything returned is a :class:`kicad_core.models.ProductInfo`, so the database
layer and the GUI do not care which site produced it.
"""

from .base import Backend, Category, SearchPage, page_count
from .routing import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    create_backend,
    currency_for,
    normalise_language,
    site_for,
    storefront_url,
)
from .text import part_number, public_url, strip_markup

__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGES",
    "Backend",
    "Category",
    "SearchPage",
    "create_backend",
    "currency_for",
    "normalise_language",
    "page_count",
    "part_number",
    "public_url",
    "site_for",
    "storefront_url",
    "strip_markup",
]
