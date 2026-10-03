"""Shared ServiceError code sets for the transient/permanent split (#291).

DynamoDB throttling classification lives in :mod:`utils.dynamodb` (`TRANSIENT_ERROR_CODES`,
`is_transient_client_error`); this module holds what is neither a service error code nor a
DynamoDB condition but is common to more than one service, so no caller has to redeclare it.
"""

from botocore.exceptions import ClientError

# The Cognito retryable set, matching `_RETRYABLE_CODES` in utils.cognito — the
# project's own definition of a Cognito fault worth retrying. Client
# `InternalErrorException` is included here and deliberately absent from the
# DynamoDB `TRANSIENT_ERROR_CODES`: Cognito classifies it as a retryable
# server-side fault.
COGNITO_TRANSIENT_ERROR_CODES: frozenset[str] = frozenset(
    {
        "ProvisionedThroughputExceededException",
        "InternalErrorException",
        "TooManyRequestsException",
    }
)


def is_transient_cognito_error(error: ClientError) -> bool:
    """Return True when ``error`` is a retryable Cognito condition."""
    return error.response.get("Error", {}).get("Code", "") in COGNITO_TRANSIENT_ERROR_CODES
