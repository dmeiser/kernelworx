"""Smoke tests for the signup UI and new-user authentication flows.

In dev and ephemeral environments, test users (including the smoke test user)
are pre-created and confirmed during environment provisioning (via
``admin_create_user`` and ``admin_set_user_password`` with message suppression)
so native sign-ups do not burn the account's 50-emails/day Cognito email quota.
Signups stay closed from self-confirmation in the pre-signup Lambda.

Design decisions
----------------
* ``test_signup_ui_renders`` verifies the signup page renders all required form
  fields without submitting to Cognito.
* ``test_signup_completes_after_backend_confirmation`` verifies that the
  pre-created confirmed smoke test user provisioned during environment setup
  (``TEST_SMOKE_EMAIL`` / ``TEST_SMOKE_PASSWORD``) can navigate from the
  signup page's *Sign In* link, authenticate, and reach the dashboard.
* ``test_signup_shows_verification_prompt`` is gated by ``RUN_NATIVE_SIGNUP``
  because submitting native signups burns Cognito's daily email quota (50/day
  per account). When opted in, it submits to Cognito and verifies the
  verification prompt appears.
"""

import os
import random
import re
import string
import subprocess

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.base_page import BasePage
from tests.e2e.utils.auth import login

_SIGNUP_PATH: str = "/signup"
_CREATE_ACCOUNT_BTN: str = "Create Account"
_AGE_LABEL: str = "I confirm that I am 13 years of age or older"


def _random_smoke_email() -> str:
    """Return a unique, non-deliverable email address for each test run."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"smoke+{suffix}@example-test.invalid"


# Throwaway password for smoke signup users; never a real credential.
_SMOKE_PASSWORD = "SmokeT3st!2026"


# Cognito account-level email quota: with the default email configuration
# Cognito caps sending at 50 emails/day/account. Once the fleet's smoke
# signup runs exhaust that quota, ``SignUp`` itself is rejected with this
# message, so the native-signup path is untestable (not failing) until the
# quota resets.
_DAILY_EMAIL_LIMIT_RE = re.compile(r"Exceeded daily email limit", re.IGNORECASE)


def _submit_signup_and_wait_for_verification(page: Page, email: str, password: str) -> None:
    """Fill and submit the signup form, then wait for the verification UI.

    After a successful Cognito ``signUp`` call the UI transitions to the
    verification step showing text containing "check your email" or
    "verification" (case-insensitive).

    A failed ``signUp`` renders a MUI *error* alert instead (``AlertMessages``
    in ``SignupPage.tsx`` gives error and success alerts the same
    ``role="alert"``, so a generic alert match would false-pass). If the
    error alert appears, the helper fails fast with the alert text — except
    when the text is Cognito's daily-email-limit quota message, in which case
    native signup is untestable and the test is skipped with that reason.
    """
    page.locator('input[type="email"]').first.fill(email)

    # The form renders two password fields (password + confirm password).
    for pw_field in page.locator('input[type="password"]').all():
        pw_field.fill(password)

    # Age confirmation checkbox — required before submit.
    age_checkbox = page.get_by_label(_AGE_LABEL, exact=False)
    if not age_checkbox.is_checked():
        age_checkbox.check()

    page.get_by_role("button", name=_CREATE_ACCOUNT_BTN).click()

    verification_text = page.get_by_text(re.compile("check your email", re.IGNORECASE)).or_(
        page.get_by_text(re.compile("verification", re.IGNORECASE))
    )
    error_alert = page.locator(".MuiAlert-standardError")
    expect(verification_text.first.or_(error_alert.first)).to_be_visible(timeout=20_000)
    if error_alert.first.is_visible():
        message = error_alert.first.inner_text()
        if _DAILY_EMAIL_LIMIT_RE.search(message):
            pytest.skip(f"Cognito daily email quota exhausted, native signup untestable: {message}")
        pytest.fail(f"SignUp failed unexpectedly: {message}")


def _cognito_cli(*args: str) -> None:
    """Run an ``aws cognito-idp`` admin command via the AWS CLI subprocess."""
    cmd = ["aws", "cognito-idp", *args, "--output", "json", "--no-cli-pager"]
    region = os.environ.get("TEST_REGION")
    if region:
        cmd.extend(["--region", region])
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"aws cognito-idp {' '.join(args)} failed: {result.stderr}")


@pytest.mark.smoke
def test_signup_ui_renders(page: Page) -> None:
    """Verify the signup page renders all required form fields.

    Checks that:
    * An email ``<input>`` is visible.
    * At least one password ``<input>`` is visible.
    * The age-confirmation checkbox is present.
    * The *Create Account* submit button is visible.
    """
    base = BasePage(page)
    base.navigate(_SIGNUP_PATH)
    base.wait_for_loading()

    expect(page.locator('input[type="email"]').first).to_be_visible(timeout=10_000)
    expect(page.locator('input[type="password"]').first).to_be_visible(timeout=10_000)
    expect(page.get_by_label(_AGE_LABEL, exact=False)).to_be_visible(timeout=10_000)
    expect(page.get_by_role("button", name=_CREATE_ACCOUNT_BTN)).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_signup_completes_after_backend_confirmation(page: Page) -> None:
    """Verify a confirmed smoke test user can navigate from signup and sign in.

    Consumes the pre-created confirmed smoke test user provisioned during
    environment setup (``TEST_SMOKE_EMAIL`` / ``TEST_SMOKE_PASSWORD``)
    instead of relying on auto-confirmation or dynamic signups during the
    smoke test run (#483).
    """
    email = os.environ.get("TEST_SMOKE_EMAIL") or os.environ.get("TEST_OWNER_EMAIL")
    password = os.environ.get("TEST_SMOKE_PASSWORD") or os.environ.get("TEST_OWNER_PASSWORD")
    if not email or not password:
        pytest.fail("Neither TEST_SMOKE_EMAIL nor TEST_OWNER_EMAIL configured")

    base = BasePage(page)
    base.navigate(_SIGNUP_PATH)
    base.wait_for_loading()

    # From the signup page, navigate to login via "Sign In" link
    page.get_by_role("button", name="Sign In").click()
    page.wait_for_url("**/login", timeout=10_000)

    login(page, email, password)

    expect(page).to_have_url(re.compile(r"/(scouts|home)"), timeout=15_000)


@pytest.mark.smoke
@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("RUN_NATIVE_SIGNUP"),
    reason="Native signup burns Cognito daily email quota; set RUN_NATIVE_SIGNUP=1 to opt in",
)
def test_signup_shows_verification_prompt(page: Page) -> None:
    """Fill and submit the signup form; verify the verification-code prompt appears.

    Gated by ``RUN_NATIVE_SIGNUP`` to avoid burning the account's 50-emails/day
    quota during routine smoke runs. When enabled, submits to the real Cognito
    pool and stops once the verification UI appears.
    """
    base = BasePage(page)
    base.navigate(_SIGNUP_PATH)
    base.wait_for_loading()

    email = _random_smoke_email()
    user_pool_id = os.environ.get("TEST_USER_POOL_ID")

    try:
        _submit_signup_and_wait_for_verification(page, email, _SMOKE_PASSWORD)
    finally:
        if user_pool_id:
            try:
                _cognito_cli(
                    "admin-delete-user",
                    "--user-pool-id",
                    user_pool_id,
                    "--username",
                    email,
                )
            except Exception:  # noqa: BLE001
                pass
