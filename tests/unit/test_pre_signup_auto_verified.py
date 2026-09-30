"""Regression test for issue #503.

The pre-signup trigger (``src/handlers/pre_signup.py``) refuses to link a
federated identity to an existing native account unless that account is
CONFIRMED and its email is verified, on the assumption that a confirmed
+ verified native account proves mailbox possession. The user pool defeats
that assumption when it sets ``auto_verified_attributes = ["email"]``: a
native ``SignUp`` supplying an arbitrary address is then auto-confirmed and
marked ``email_verified = "true"`` with no proof of mailbox possession, so an
attacker's squat satisfies both guard checks and receives the victim's
federated identity (and intercepts ``verified_email`` password resets).

This test parses the Cognito module semantically (python-hcl2, the same
approach as ``test_exports_bucket_lifecycle.py``) rather than grepping, and
asserts the pool does NOT auto-verify email. It fails on the pre-fix
configuration and passes once ``auto_verified_attributes`` is removed.
"""

from pathlib import Path

import hcl2
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COGNITO_MODULE = REPO_ROOT / "tofu" / "application" / "modules" / "cognito" / "main.tf"


def _norm(value):
    """Strip the quote wrapper python-hcl2 adds around string values and keys."""
    if isinstance(value, dict):
        return {_norm(k): _norm(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    if isinstance(value, str) and len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def _load_module() -> dict:
    """Parse the module, normalizing away hcl2's quote wrappers and bookkeeping."""
    with open(COGNITO_MODULE, encoding="utf-8") as f:
        doc = hcl2.load(f)
    return _norm(doc)


def _user_pool_attrs(doc: dict) -> dict:
    """Return the attribute map of ``aws_cognito_user_pool.main`` (already normalized)."""
    for entry in doc.get("resource", []):
        for rtype, bodies in entry.items():
            if rtype != "aws_cognito_user_pool":
                continue
            for label, attrs in bodies.items():
                if label == "main":
                    return attrs
    pytest.fail("aws_cognito_user_pool.main not found in the cognito module")


def test_pool_does_not_auto_verify_email():
    """Email must not be auto-verified, or the pre-signup fail-closed guard is
    defeated by an unpossessed squat (issue #503).

    Auto-verified email means a native SignUp for an arbitrary address is
    auto-confirmed and marked ``email_verified = "true"`` with no proof of
    mailbox possession. That is exactly the account that satisfies both checks
    in ``pre_signup._handle_existing_user`` and receives the victim's federated
    identity, and it also intercepts ``verified_email`` password resets. The
    attribute is absent in the fix; an explicit empty list or a list that
    excludes email is equally safe.
    """
    attrs = _user_pool_attrs(_load_module())
    auto_verified = attrs.get("auto_verified_attributes")
    if auto_verified is None:
        return
    auto_verified_emails = [a for a in auto_verified if _norm(a) == "email"]
    assert not auto_verified_emails, (
        f"aws_cognito_user_pool.main auto-verifies email "
        f"(auto_verified_attributes={auto_verified!r}); this auto-confirms a native SignUp "
        "for an unpossessed email and defeats the pre-signup account-linking "
        "fail-closed guard (issue #503)"
    )


def test_pool_still_uses_email_as_username():
    """The fix removes auto-verification only; email must remain the username
    attribute so the frontend and existing flows are unaffected."""
    attrs = _user_pool_attrs(_load_module())
    username_attributes = attrs.get("username_attributes")
    assert username_attributes == ["email"], (
        f"username_attributes changed unexpectedly: {username_attributes!r}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
