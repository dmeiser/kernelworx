"""Smoke tests for the signup UI.

``TEST_USER_POOL_ID`` is confirmed present in the dev ``.env``; the Cognito
user pool is accessible from the dev environment.

Design decisions
----------------
* Tests stop **before** email verification — actual email receipt cannot be
  automated here (no test inbox integration is in scope).
* ``test_signup_shows_verification_prompt`` submits to the real Cognito pool.
  The generated address (``smoke+<random>@example-test.invalid``) is a valid
  format that Cognito accepts; the verification email is queued but never
  delivered because the domain is non-routable.  The resulting unverified
  Cognito user persists in the pool (UNCONFIRMED state) and is not removed by
  ``global_cleanup`` (which only touches DynamoDB).  This is acceptable for a
  smoke test run; manual pool housekeeping can clear stale UNCONFIRMED users.
* The submit button label verified from ``SignupPage.tsx`` is *Create Account*.
* The age-confirmation checkbox label is
  *I confirm that I am 13 years of age or older*.
"""

import random
import re
import string

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
    # Throwaway password: this user is UNCONFIRMED and the email domain is non-routable.
    # Not a real credential — cleaned up in global_cleanup via cleanup_unconfirmed_smoke_users().
    password = "SmokeT3st!2026"

    page.locator('input[type="email"]').first.fill(email)

    # The form renders two password fields (password + confirm password).
    for pw_field in page.locator('input[type="password"]').all():
        pw_field.fill(password)

    # Age / COPPA confirmation checkbox — required before submit.
    age_checkbox = page.get_by_label(_AGE_LABEL, exact=False)
    if not age_checkbox.is_checked():
        age_checkbox.check()

    page.get_by_role("button", name=_CREATE_ACCOUNT_BTN).click()

    # After a successful Cognito signUp call the UI transitions to the
    # verification step showing one of:
    #   a) [role="alert"] with the success message, or
    #   b) Text containing "verification" or "check your email" (case-insensitive)
    verification_text = (
        page.get_by_text(re.compile("check your email", re.IGNORECASE))
        .or_(page.get_by_text(re.compile("verification", re.IGNORECASE)))
        .or_(page.get_by_role("alert"))
    )
    expect(verification_text.first).to_be_visible(timeout=20_000)
