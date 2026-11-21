"""Shared, GUI-free core for the KiCad ``components`` table.

The schema, the models and the database layer are carried over from
``kicad_lib_gen`` (MIT) unchanged, so a database written by this program is
interchangeable with one written by KiCad LibGen or read by KiCad's database
library.  Only the data source differs: LCSC instead of DigiKey.
"""

from .database import (
    ProductDb,
    UpsertOutcome,
    ensure_schema,
    product_from_row,
    product_to_row,
    validate_schema,
)
from .errors import (
    AppError,
    BatchError,
    DatabaseError,
    DatabaseLockedError,
    DetailError,
    NetworkError,
    ParseError,
    RateLimitError,
    SchemaError,
    SearchError,
    ServerError,
)
from .models import (
    ALL_COLUMNS,
    DEFAULT_PARAM,
    METADATA_COLUMNS,
    PARAM_COLUMNS,
    PARAM_COUNT,
    ProductInfo,
    ProductInfoBase,
    resolve_mapping,
    validate_mapping,
)

__all__ = [
    "ALL_COLUMNS",
    "DEFAULT_PARAM",
    "METADATA_COLUMNS",
    "PARAM_COLUMNS",
    "PARAM_COUNT",
    "AppError",
    "BatchError",
    "DatabaseError",
    "DatabaseLockedError",
    "DetailError",
    "NetworkError",
    "ParseError",
    "ProductDb",
    "ProductInfo",
    "ProductInfoBase",
    "RateLimitError",
    "SchemaError",
    "SearchError",
    "ServerError",
    "UpsertOutcome",
    "ensure_schema",
    "product_from_row",
    "product_to_row",
    "resolve_mapping",
    "validate_mapping",
    "validate_schema",
]
