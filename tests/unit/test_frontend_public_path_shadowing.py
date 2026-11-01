"""Guard: no frontend/public path may be shadowed by the CloudFront auth behaviors.

The #665 Free-tier collapse made ``/l*`` one of the ordered cache behaviors
proxying to the Cognito origin (``local.auth_path_patterns`` in
``tofu/application/modules/cloudfront/main.tf``). Any request whose path
matches one of those patterns never reaches the S3 origin: on 2026-10-06 the
root static assets ``/logo.svg`` and ``/logo-rotating.svg`` matched ``/l*``,
Cognito answered 404, and the distribution's 403/404 custom error response
served ``index.html`` as a 200 - the logo was silently broken on dev and prod
while every gate stayed green (issue #689, proven 2026-10-10). The assets were
renamed ``kernelworx-logo*.svg`` (KW-LOGO-PATHFIX-1).

This test is the regression net for the whole class: it reads the real
``auth_path_patterns`` local from the tofu module and asserts that no file or
directory shipped from ``frontend/public/`` has a URL path matching any of
those patterns. It fails if either side drifts - a new auth pattern, or a new
public asset under a shadowed segment.
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path

import hcl2

REPO_ROOT = Path(__file__).resolve().parents[2]
CLOUDFRONT_MAIN_TF = REPO_ROOT / "tofu" / "application" / "modules" / "cloudfront" / "main.tf"
FRONTEND_PUBLIC = REPO_ROOT / "frontend" / "public"


def _load_auth_path_patterns() -> list[str]:
    with CLOUDFRONT_MAIN_TF.open() as f:
        doc = hcl2.load(f)
    locals_block = doc["locals"]
    if isinstance(locals_block, list):
        locals_block = locals_block[0]
    patterns = locals_block["auth_path_patterns"]
    return [json.loads(p) if isinstance(p, str) and p.startswith('"') else p for p in patterns]


def _public_url_paths() -> list[str]:
    """Every URL path the static bucket can serve, from frontend/public."""
    paths = []
    for entry in sorted(FRONTEND_PUBLIC.rglob("*")):
        rel = entry.relative_to(FRONTEND_PUBLIC).as_posix()
        paths.append(f"/{rel}")
    return paths


def test_auth_path_patterns_local_exists() -> None:
    patterns = _load_auth_path_patterns()
    assert patterns, "local.auth_path_patterns must not be empty"


def test_no_frontend_public_path_matches_an_auth_pattern() -> None:
    patterns = _load_auth_path_patterns()
    shadowed = [p for p in _public_url_paths() if any(fnmatch.fnmatchcase(p, pat) for pat in patterns)]
    assert not shadowed, (
        f"frontend/public paths shadowed by the CloudFront auth behaviors {patterns}: {shadowed}. "
        "They would be proxied to the Cognito origin and 404 (the /logo.svg incident, #689) - "
        "rename them off the wildcard."
    )


def test_renamed_brand_assets_are_off_the_wildcard() -> None:
    """The #689 fix itself: both brand assets exist under their new names and
    the old shadowed names are gone."""
    patterns = _load_auth_path_patterns()
    for name in ("kernelworx-logo.svg", "kernelworx-logo-rotating.svg"):
        path = f"/{name}"
        assert (FRONTEND_PUBLIC / name).is_file(), f"{path} must exist in frontend/public"
        assert not any(fnmatch.fnmatchcase(path, pat) for pat in patterns)
    assert not (FRONTEND_PUBLIC / "logo.svg").exists()
    assert not (FRONTEND_PUBLIC / "logo-rotating.svg").exists()
