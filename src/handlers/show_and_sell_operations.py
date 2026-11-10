"""Show & Sell operations handler (Stage 3).

Stub entry point; full mutation/query implementations follow in subsequent commits.
"""

from __future__ import annotations

from typing import Any

from src.utils.handlers import lambda_handler


@lambda_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    _ = event
    return {"ok": True}
