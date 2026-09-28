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
import logging
import os
import pathlib
import subprocess
import sys
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from src.handlers import post_authentication, pre_signup, pre_token_generation
from src.utils.logging import mask_email


def _structured_records(capsys: Any) -> List[Dict[str, Any]]:
    """Parse every captured stdout JSON object line as a structured log record."""
    records: List[Dict[str, Any]] = []
    for line in capsys.readouterr().out.splitlines():
        if line.strip().startswith("{"):
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


# Imports the three triggers in a *fresh* interpreter and reports the root
# logger's level and handler count afterwards, so the module-scope side effect
# of importing them is what gets measured (not a level some earlier test left).
_ROOT_LOGGER_PROBE = """
import logging

for module in (
    "src.handlers.pre_signup",
    "src.handlers.post_authentication",
    "src.handlers.pre_token_generation",
):
    __import__(module)

root = logging.getLogger()
print(root.level, len(root.handlers))
"""


def test_trigger_imports_leave_the_root_logger_untouched() -> None:
    """Importing the triggers must not configure the shared root logger.

    Before the fix each trigger module ran ``logging.getLogger().setLevel(INFO)``
    at import time, silently re-configuring the root logger that every other
    Lambda function in the project shares. A fresh interpreter starts with the
    root logger at WARNING and no handlers; importing the triggers must not
    change that.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    env = dict(os.environ, PYTHONPATH=str(repo_root), AWS_DEFAULT_REGION="us-east-1")

    result = subprocess.run(
        [sys.executable, "-c", _ROOT_LOGGER_PROBE],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env=env,
        check=True,
    )
    level, handler_count = result.stdout.strip().split()

    assert int(level) == logging.WARNING, f"importing the triggers reconfigured the root logger to level {level}"
    assert int(handler_count) == 0, "importing the triggers attached handlers to the root logger"


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


def test_pre_signup_native_signup_log_record_has_no_clear_text_email(capsys: Any) -> None:
    """Native sign-up records must not leak the clear-text email in any field.

    The pool sets username_attributes = ["email"], so on a native
    PreSignUp_SignUp event Cognito's userName IS the user's email address.
    Every field of every record emitted for that event must be free of the
    clear-text address, while correlationId and level keep working.
    """
    email = "victim@example.com"
    event: Dict[str, Any] = {
        "version": "1",
        "triggerSource": "PreSignUp_SignUp",
        "userPoolId": "us-east-1_TEST123",
        "userName": email,
        "request": {"userAttributes": {"email": email}},
        "response": {},
    }

    result = pre_signup.lambda_handler(event, MagicMock())

    assert result is event
    records = _structured_records(capsys)
    invoked = [record for record in records if record["message"] == "Pre-signup trigger invoked"]
    assert invoked, "invocation record not emitted"
    assert invoked[0]["username"] == mask_email(email)
    for record in records:
        assert record["correlationId"], "record missing correlationId"
        assert record["level"] == "INFO"
        for key, value in record.items():
            if isinstance(value, str):
                assert email not in value, f"clear-text email leaked in field {key}"


def test_pre_signup_invocation_log_never_emits_a_clear_text_email(capsys: Any) -> None:
    """No field of the native sign-up invocation record may hold the address.

    The user pool uses ``username_attributes = [email]``, so Cognito sets the
    event's ``userName`` to the sign-up email address; both it and the
    ``email`` attribute must be masked before they reach CloudWatch.
    """
    address = "signer@example.com"
    event: Dict[str, Any] = {
        "version": "1",
        "triggerSource": "PreSignUp_SignUp",
        "userPoolId": "us-east-1_TEST123",
        "userName": address,
        "request": {"userAttributes": {"email": address}},
        "response": {},
    }

    assert pre_signup.lambda_handler(event, MagicMock()) is event

    invoked = [r for r in _structured_records(capsys) if r["message"] == "Pre-signup trigger invoked"]
    assert invoked, "invocation record not emitted"
    record = invoked[0]
    assert address not in json.dumps(record), f"clear-text email leaked into log record: {record}"
    assert record["level"] == "INFO"
    assert record["correlationId"]


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
