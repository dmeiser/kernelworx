"""
Unit tests for template rendering utility.
"""

from src.utils.templates import render_template


def test_render_template_basic() -> None:
    """Test rendering a template with basic context."""
    html = render_template("base.html", {"is_authenticated": False, "is_admin": False})
    assert "<!DOCTYPE html>" in html
    assert "KernelWorx" in html
    assert "Sign in" in html


def test_render_template_authenticated() -> None:
    """Test rendering base template for an authenticated admin user."""
    html = render_template("base.html", {"is_authenticated": True, "is_admin": True})
    assert "My Scouts" in html
    assert "Sign out" in html


def test_render_template_default_context() -> None:
    """Test rendering template with None context default."""
    html = render_template("base.html", None)
    assert "<!DOCTYPE html>" in html
