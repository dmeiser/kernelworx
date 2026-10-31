"""Centralized dual-layout import helper for ``utils`` modules (#774).

The Lambda payload zip lays ``src/`` out as top-level ``utils`` and
``handlers`` packages, so runtime code imports ``utils.<module>``
absolutely. Unit tests import through the ``src`` package (``from
src.handlers import ...``), where the absolute name does not resolve.
Every module crossing that boundary used to carry its own copy of::

    try:
        from utils.errors import AppError, ErrorCode
    except ModuleNotFoundError:
        from ..utils.errors import AppError, ErrorCode

This module owns that fallback once. Call sites keep exactly one
mechanical locator import — absolute with a relative fallback, the same
shape at a fixed four lines — and bind names through
`import_from_utils`, which resolves the SAME module objects in both
layouts, so test monkeypatching and Lambda behavior are unchanged.
"""

import importlib
from typing import Any


def import_from_utils(module_name: str, *names: str) -> Any:
    """Return attribute(s) of ``utils.<module_name>`` under either import layout.

    Tries the Lambda layout (``utils.<module_name>``) first and falls back
    to the unit-test layout (``src.utils.<module_name>``) when the
    top-level ``utils`` package does not resolve. With a single name the
    bare attribute is returned; with several, a tuple in the requested
    order.
    """
    try:
        module = importlib.import_module(f"utils.{module_name}")
    except ModuleNotFoundError:
        module = importlib.import_module(f".{module_name}", package=__package__)
    values = tuple(getattr(module, name) for name in names)
    return values[0] if len(values) == 1 else values
