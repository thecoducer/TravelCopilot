"""Services layer."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.cache_service import CacheService
    from app.services.fx_converter_service import FxConverter
    from app.services.pdf_service import render_pdf

__all__ = [
    "CacheService",
    "FxConverter",
    "render_pdf",
]


def __getattr__(name: str) -> Any:
    """Load service exports lazily so service modules can depend on ToolFactory."""
    if name == "CacheService":
        from app.services.cache_service import CacheService

        return CacheService
    if name == "FxConverter":
        from app.services.fx_converter_service import FxConverter

        return FxConverter
    if name == "render_pdf":
        from app.services.pdf_service import render_pdf

        return render_pdf
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
