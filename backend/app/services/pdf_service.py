"""PDF generation service using WeasyPrint + Jinja2."""

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
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "j2"]),
        )
        template = env.get_template("itinerary.html.j2")
        return template.render(**data)
    except ImportError as exc:
        raise RuntimeError("Jinja2 is required for itinerary PDF generation") from exc


def _html_to_pdf(html: str) -> bytes:
    """Convert HTML to PDF bytes using WeasyPrint."""
    try:
        from weasyprint import HTML

        return bytes(HTML(string=html).write_pdf())
    except ImportError as exc:
        logger.warning(
            "weasyprint_not_installed",
            hint="pip install weasyprint",
        )
        raise RuntimeError("WeasyPrint is required for itinerary PDF generation") from exc
