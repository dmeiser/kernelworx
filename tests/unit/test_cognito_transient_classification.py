"""Unit tests for the single Cognito transient/permanent classifier."""

from typing import Any

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from src.utils.cognito import COGNITO_TRANSIENT_ERROR_CODES, is_transient_cognito_error


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "ListUsers")


@pytest.mark.parametrize("code", sorted(COGNITO_TRANSIENT_ERROR_CODES))
def test_known_transient_codes_are_retryable(code: str) -> None:
    assert is_transient_cognito_error(_client_error(code)) is True


def test_a_permanent_service_code_is_not_retryable() -> None:
    """A service verdict like NotAuthorizedException is the caller's to fix."""
    assert is_transient_cognito_error(_client_error("NotAuthorizedException")) is False


def test_a_transport_fault_is_retryable_without_a_service_code() -> None:
    """A BotoCoreError is a transport fault, not a verdict, so it always retries.

    This is the shape that has no ``response`` at all: classifying it by
    ``error.response`` would raise AttributeError instead of answering.
    """
    assert is_transient_cognito_error(BotoCoreError()) is True


def test_a_non_botocore_exception_is_permanent() -> None:
    """Anything outside botocore is a programming fault, not a retryable fault."""
    assert is_transient_cognito_error(RuntimeError("boom")) is False
    assert is_transient_cognito_error(ValueError("boom")) is False


def test_a_client_error_without_an_error_block_is_permanent() -> None:
    assert is_transient_cognito_error(ClientError({}, "ListUsers")) is False


def test_the_retry_wrapper_and_the_classifier_agree_on_the_same_set() -> None:
    """The wrapper retries exactly the codes the classifier calls retryable.

    Guards against the two drifting into a code that is retried but then
    reported as permanent (or the reverse) -- the contradiction that made a
    genuinely transient Cognito fault promise no retry.
    """
    import inspect

    from src.utils import cognito

    source = inspect.getsource(cognito.retry_on_transient_errors)
    assert "COGNITO_TRANSIENT_ERROR_CODES" in source
    # The wrapper must not consult a second, parallel set.
    assert "_RETRYABLE_CODES" not in source
    assert not hasattr(cognito, "_RETRYABLE_CODES")


def test_transport_faults_classify_as_retryable_for_the_deletion_paths() -> None:
    """A BotoCoreError reaching a deletion-path classifier answers True, not an exception."""

    def classify(error: Any) -> bool:
        return is_transient_cognito_error(error)

    assert classify(BotoCoreError()) is True
