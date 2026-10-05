"""Product registry and specifications for IGS analysis centers."""

from canvod.auxiliary.products.models import (
    ClkHeader,
    FileValidationResult,
    ProductRequest,
    Sp3Header,
)
from canvod.auxiliary.products.registry_config import (
    FtpServerConfig,
    ProductRegistry,
    ProductSpec,
    UnknownProductError,
    check_product,
    get_product_spec,
    get_products_for_agency,
    get_registry,
    list_agencies,
    list_products,
)

__all__ = [
    "ClkHeader",
    "FileValidationResult",
    # Registry
    "FtpServerConfig",
    "ProductRegistry",
    "ProductRequest",
    "ProductSpec",
    # Models
    "Sp3Header",
    "UnknownProductError",
    "check_product",
    "get_product_spec",
    "get_products_for_agency",
    "get_registry",
    "list_agencies",
    "list_products",
]
