"""
Jinja2 Template Rendering Utility
Loads HTML templates from src/templates and renders them with context variables.
"""

from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_template(template_name: str, context: Dict[str, Any] | None = None) -> str:
    """Render a Jinja2 template with the given context dictionary."""
    if context is None:
        context = {}
    template = _env.get_template(template_name)
    return template.render(**context)
