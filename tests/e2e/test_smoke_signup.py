"""Smoke tests for the signup UI.

``TEST_USER_POOL_ID`` is confirmed present in the dev ``.env``; the Cognito
user pool is accessible from the dev environment.

Design decisions
----------------
* Tests stop **before** the verification-code entry step — no test email
  inbox integration is in scope, so the emailed code cannot be read here.
* ``test_signup_shows_verification_prompt`` submits to the real Cognito pool
  (``smoke+<random>@example-test.invalid``) and stops once the verification
  UI appears.
* ``test_signup_completes_after_backend_confirmation`` completes the flow
  without the emailed code: the new user is confirmed server-side via
  ``aws cognito-idp admin-confirm-sign-up`` (the AWS CLI, so the same
  credential source as the local AWS CLI is inherited), then the *Back to
  Login* path and the real login page are exercised to reach the dashboard.
* ``smoke+`` Cognito users are deleted in every state (UNCONFIRMED and
  CONFIRMED) by the cleanup stages in ``tests/e2e/conftest.py`` and
  ``tests/integration/globalTeardown.ts``; the completion test also deletes
  its own user in a ``finally`` block, so the corresponding Account rows
  created by the post-confirmation trigger are removed from DynamoDB too.
* ``admin-confirm-sign-up`` retries ``UserNotFoundException`` with
  exponential backoff (~3 minutes total): a freshly created Cognito user is
  not always visible to admin reads immediately (read-after-write
  propagation), and "not found yet" is the expected transient, not an error.
* The submit button label verified from ``SignupPage.tsx`` is *Create Account*.
* The age-confirmation checkbox label is
  *I confirm that I am 13 years of age or older*.
"""

import os
import random
import re
import string
import subprocess
import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.base_page import BasePage

_SIGNUP_PATH: str = "/signup"
_CREATE_ACCOUNT_BTN: str = "Create Account"
_AGE_LABEL: str = "I confirm that I am 13 years of age or older"


def _random_smoke_email() -> str:
    """Return a unique, non-deliverable email address for each test run."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"smoke+{suffix}@example-test.invalid"


# Throwaway password for smoke signup users; never a real credential.
_SMOKE_PASSWORD = "SmokeT3st!2026"


def _submit_signup_and_wait_for_verification(page: Page, email: str, password: str) -> None:
    """Fill and submit the signup form, then wait for the verification UI.

    After a successful Cognito ``signUp`` call the UI transitions to the
    verification step showing text containing "check your email" or
    "verification" (case-insensitive).

    A transient ``signUp`` failure renders a MUI *error* alert instead. That
    error alert must not be mistaken for reaching the verification step:
    proceeding past a failed signup surfaces later as a confusing Cognito
    ``UserNotFoundException`` from ``admin-confirm-sign-up``. If the error
    alert appears, fail immediately with its message.
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

    error_alert = page.locator(".MuiAlert-standardError")
    verification_text = page.get_by_text(re.compile("check your email", re.IGNORECASE)).or_(
        page.get_by_text(re.compile("verification", re.IGNORECASE))
    )
    expect(verification_text.first.or_(error_alert.first)).to_be_visible(timeout=20_000)
    if error_alert.first.is_visible():
        pytest.fail(f"SignUp failed unexpectedly: {error_alert.first.inner_text()}")


# Retry budget for admin-confirm-sign-up only. Since ~2026-09-09 Cognito's
# read-after-write consistency for newly created users has been slow enough
# that a single immediate admin-confirm-sign-up exhausts against
# ``UserNotFoundException`` in the ephemeral smoke runs. Backoff sleeps
# between the 7 attempts total ~195 s (~3 minutes); every other failure and
# every other command still fail on the first attempt.
_CONFIRM_SIGNUP_MAX_ATTEMPTS = 7
_CONFIRM_SIGNUP_BACKOFF_SECONDS = (5, 10, 20, 40, 60, 60)


def _cognito_cli(*args: str, retry_user_not_found: bool = False) -> None:
    """Run an ``aws cognito-idp`` admin command via the AWS CLI subprocess.

    The CLI is used instead of boto3 so the test inherits the same credential
    source as the local AWS CLI (boto3's pinned botocore may not implement the
    local credential provider plugins), matching the cleanup helper in
    ``tests/e2e/conftest.py``.

    With ``retry_user_not_found=True``, a ``UserNotFoundException`` failure is
    retried with exponential backoff (see :data:`_CONFIRM_SIGNUP_BACKOFF_SECONDS`)
    before raising; all other failures raise immediately.
    """
    cmd = ["aws", "cognito-idp", *args, "--output", "json", "--no-cli-pager"]
    region = os.environ.get("TEST_REGION")
    if region:
        cmd.extend(["--region", region])
    for attempt in range(_CONFIRM_SIGNUP_MAX_ATTEMPTS if retry_user_not_found else 1):
        result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return
        if not (retry_user_not_found and "UserNotFoundException" in result.stderr):
            break
        if attempt < _CONFIRM_SIGNUP_MAX_ATTEMPTS - 1:
            time.sleep(_CONFIRM_SIGNUP_BACKOFF_SECONDS[attempt])
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
@pytest.mark.slow
def test_signup_shows_verification_prompt(page: Page) -> None:
    """Fill and submit the signup form; verify the verification-code prompt appears.

    This test submits to the **real** Cognito user pool so that the full
    front-end signup path (including Amplify ``signUp()`` call) is exercised.
    The test stops after confirming the verification UI is shown — it does not
    attempt to enter a code or complete registration.

    Success criterion: the page transitions away from the form and displays
    text referencing email or a verification code within 20 s.
    """
    base = BasePage(page)
    base.navigate(_SIGNUP_PATH)
    base.wait_for_loading()

    email = _random_smoke_email()

    _submit_signup_and_wait_for_verification(page, email, _SMOKE_PASSWORD)


@pytest.mark.smoke
def test_signup_completes_after_backend_confirmation(page: Page) -> None:
    """Complete signup end-to-end via backend confirmation, then sign in.

    No test email inbox integration is in scope, so the emailed verification
    code cannot be read here.  Instead the new user is confirmed server-side
    via ``aws cognito-idp admin-confirm-sign-up``, then the *Back to Login*
    path and the real login page are exercised to reach the dashboard.
    """
    base = BasePage(page)
    base.navigate(_SIGNUP_PATH)
    base.wait_for_loading()

    email = _random_smoke_email()

    _submit_signup_and_wait_for_verification(page, email, _SMOKE_PASSWORD)

    user_pool_id = os.environ.get("TEST_USER_POOL_ID")
    if not user_pool_id:
        pytest.fail("TEST_USER_POOL_ID is not set in environment.")

    _cognito_cli(
        "admin-confirm-sign-up",
        "--user-pool-id",
        user_pool_id,
        "--username",
        email,
        retry_user_not_found=True,
    )

    page.get_by_role("button", name="Back to Login").click()
    page.wait_for_url("**/login", timeout=10_000)

    from tests.e2e.utils.auth import login

    try:
        login(page, email, _SMOKE_PASSWORD)

        expect(page).to_have_url(re.compile(r"/(scouts|home)"), timeout=15_000)
    finally:
        # admin-confirm-sign-up flips the user to CONFIRMED, which the
        # smoke+ cleanup stages skip; delete it here so the pool and its
        # post-confirmation Account row do not accumulate across runs.
        _cognito_cli(
            "admin-delete-user",
            "--user-pool-id",
            user_pool_id,
            "--username",
            email,
        )
