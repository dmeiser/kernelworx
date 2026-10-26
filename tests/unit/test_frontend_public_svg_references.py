"""Guard: every relative href inside a shipped frontend/public SVG must resolve.

Issue #755: ``kernelworx-logo-rotating.svg`` embedded ``<image href="logo.svg">``,
a path #689 renamed away, so the served document was a valid ``image/svg+xml``
200 that rendered blank. The deploy probe only checks status + content-type +
``<svg``, so nothing caught it. This test parses every SVG shipped from
``frontend/public/`` and asserts each ``href``/``xlink:href`` that names a
local (non-scheme, non-fragment) target exists on disk, relative to the
referencing file.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_PUBLIC = REPO_ROOT / "frontend" / "public"

_HREF_ATTRS = ("href", "{http://www.w3.org/1999/xlink}href")
_LOCAL_REF = re.compile(r"^[^\s?#]+")


def _local_href_targets(svg_path: Path) -> list[str]:
    tree = ET.parse(svg_path)
    targets = []
    for el in tree.iter():
        for attr in _HREF_ATTRS:
            value = el.attrib.get(attr)
            if not value:
                continue
            parsed = urlparse(value)
            if parsed.scheme or parsed.netloc or value.startswith(("#", "//")):
                continue
            match = _LOCAL_REF.match(parsed.path)
            if match:
                targets.append(match.group(0))
    return targets


def test_all_relative_svg_href_targets_resolve() -> None:
    missing: list[str] = []
    for svg_path in sorted(FRONTEND_PUBLIC.rglob("*.svg")):
        for target in _local_href_targets(svg_path):
            if not (svg_path.parent / target).is_file():
                missing.append(f"{svg_path.relative_to(REPO_ROOT)} -> {target}")
    assert not missing, (
        "frontend/public SVGs embed relative references whose target does not exist "
        f"(renders blank while still served 200): {missing}"
    )
