"""Behavioral regression tests: the Cognito triggers must emit structured logs (#565).

Issue #565: the three Cognito triggers (pre_signup, post_authentication,
pre_token_generation) configured the root logger at module scope and emitted
unstructured f-string messages, so their log lines — the most security-relevant
events in the system — were invisible to ``grep '"correlationId"'`` in
CloudWatch and could not be filtered by field.

These tests exercise the public ``lambda_handler`` of each trigger and assert
the emitted log records are JSON objects carrying ``correlationId``, ``level``,
``message`` and ``timestamp`` fields. They fail against the pre-fix
root-logger code (plain-text records on stderr, nothing structured on stdout)
and pass after the fix.
"""

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from src.handlers import post_authentication, pre_signup, pre_token_generation
from src.utils.logging import StructuredLogger


def _structured_records(capsys: Any) -> List[Dict[str, Any]]:
    """Parse every captured stdout line as a JSON structured log record."""
    records: List[Dict[str, Any]] = []
    for line in capsys.readouterr().out.splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _assert_structured_records(records: List[Dict[str, Any]]) -> None:
    """Every emitted record must be a structured JSON log entry."""
    assert records, "no log records emitted"
    for record in records:
        assert record["correlationId"], "record missing correlationId"
        assert record["level"] in {"INFO", "WARNING", "ERROR", "DEBUG"}
        assert record["message"], "record missing message"
        assert "timestamp" in record


def test_trigger_loggers_are_structured_loggers() -> None:
    """Each trigger module's logger is a StructuredLogger, not the root logger."""
    assert isinstance(pre_signup.logger, StructuredLogger)
    assert isinstance(post_authentication.logger, StructuredLogger)
    assert isinstance(pre_token_generation.logger, StructuredLogger)


def test_pre_signup_emits_structured_json_records(capsys: Any) -> None:
    """Pre-signup log lines are structured JSON with a correlationId."""
    event: Dict[str, Any] = {
        "version": "1",
        "triggerSource": "PreSignUp_SignUp",
        "userPoolId": "us-east-1_TEST123",
        "userName": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "request": {"userAttributes": {"email": "user@example.com"}},
        "response": {},
    }

    result = pre_signup.lambda_handler(event, MagicMock())

    assert result is event
    records = _structured_records(capsys)
    _assert_structured_records(records)
    assert any(record["message"] == "Pre-signup trigger invoked" for record in records)


def test_post_authentication_emits_structured_json_records(capsys: Any, dynamodb_table: Any) -> None:
    """Account-bootstrap log lines are structured JSON with a correlationId."""
    event: Dict[str, Any] = {
        "version": "1",
        "triggerSource": "PostAuthentication_Authentication",
        "userPoolId": "us-east-1_TEST123",
        "userName": "google_123456789",
        "request": {
            "userAttributes": {
                "sub": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "email": "user@example.com",
            },
        },
        "response": {},
    }

    result = post_authentication.lambda_handler(event, MagicMock())

    assert result == event
    records = _structured_records(capsys)
    _assert_structured_records(records)
    assert any(record["message"] == "Account bootstrap trigger invoked" for record in records)


def test_pre_token_generation_emits_structured_json_records(capsys: Any) -> None:
    """Pre-token-generation log lines are structured JSON with a correlationId."""
    event: Dict[str, Any] = {
        "version": "2",
        "triggerSource": "TokenGeneration_Authentication",
        "userPoolId": "us-east-1_TEST123",
        "userName": "Google_1234567890",
        "request": {
            "userAttributes": {
                "sub": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "identities": ('[{"providerName":"Google","providerType":"Google","userId":"1234567890"}]'),
            },
        },
        "response": {},
    }

    with patch("src.handlers.pre_token_generation.cognito") as mock_cognito:
        pre_token_generation.lambda_handler(event, MagicMock())

    mock_cognito.admin_get_user.assert_not_called()
    records = _structured_records(capsys)
    _assert_structured_records(records)
    assert any(record["message"] == "pre-token-generation: federated identity -> mfa=false" for record in records)


def test_pre_token_generation_emits_structured_traceback_on_lookup_failure(capsys: Any) -> None:
    """The fail-closed AdminGetUser warning is structured JSON carrying a traceback."""
    event: Dict[str, Any] = {
        "version": "2",
        "triggerSource": "TokenGeneration_Authentication",
        "userPoolId": "us-east-1_TEST123",
        "userName": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "request": {
            "userAttributes": {
                "sub": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            },
        },
        "response": {},
    }

    with patch("src.handlers.pre_token_generation.cognito") as mock_cognito:
        mock_cognito.admin_get_user.side_effect = Exception("cognito down")
        result = pre_token_generation.lambda_handler(event, MagicMock())

    assert result == event

    records = _structured_records(capsys)
    _assert_structured_records(records)
    failures = [
        record
        for record in records
        if record["message"] == "pre-token-generation: AdminGetUser failed; setting mfa=false (fail-closed)"
    ]
    assert failures, "fail-closed AdminGetUser warning not emitted"
    assert "traceback" in failures[0]
    assert "cognito down" in failures[0]["traceback"]
