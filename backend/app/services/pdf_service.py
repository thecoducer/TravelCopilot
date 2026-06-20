"""PDF generation service using WeasyPrint + Jinja2.

``render_pdf(itinerary_data)`` renders the itinerary.html.j2 template and
converts it to PDF bytes via WeasyPrint.  Falls back to a plain-text stub
if WeasyPrint is not installed (avoids crashing the API in dev environments).
"""

from __future__ import annotations

import pathlib
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"


async def render_pdf(itinerary_data: dict[str, Any] | str) -> bytes:
    """Render an itinerary dict to PDF bytes.

    Args:
        itinerary_data: Either a dict (from Pydantic ``model_dump()``) or a
            JSON string (straight from the database ``itinerary_json`` column).
    """
    import json as _json

    if isinstance(itinerary_data, str):
        data: dict[str, Any] = _json.loads(itinerary_data)
    else:
        data = itinerary_data

    html_content = _render_html(data)
    return _html_to_pdf(html_content)


def _render_html(data: dict[str, Any]) -> str:
    """Render the Jinja2 HTML template with itinerary data."""
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape  # type: ignore[import]

        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "j2"]),
        )
        template = env.get_template("itinerary.html.j2")
        return template.render(**data)
    except ImportError:
        # Jinja2 not installed — render minimal HTML
        title = data.get("title", "Itinerary")
        dest = data.get("destination", "")
        return f"<html><body><h1>{title}</h1><p>{dest}</p></body></html>"


def _html_to_pdf(html: str) -> bytes:
    """Convert HTML to PDF bytes using WeasyPrint."""
    try:
        from weasyprint import HTML  # type: ignore[import]

        return HTML(string=html).write_pdf()
    except ImportError:
        logger.warning(
            "weasyprint_not_installed",
            hint="pip install weasyprint",
        )
        # Return a minimal valid PDF stub (1-page blank PDF)
        return _minimal_pdf_stub()


def _minimal_pdf_stub() -> bytes:
    """Return the smallest valid PDF as a stub when WeasyPrint is absent."""
    # Minimal PDF 1.4 with a single blank page
    stub = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000052 00000 n \n"
        b"0000000101 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n173\n%%EOF"
    )
    return stub
