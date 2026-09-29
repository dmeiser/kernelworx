"""Tests for src/utils/boto.py - shared boto3 client factories (#523, #575)."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.utils.boto import get_cognito_client, get_dynamodb_client, get_s3_client


class TestGetCognitoClient:
    """Tests for the shared Cognito client factory."""

    def test_default_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without COGNITO_ENDPOINT the client is built with no override."""
        monkeypatch.delenv("COGNITO_ENDPOINT", raising=False)

        with patch("src.utils.boto.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            get_cognito_client()

            mock_client.assert_called_once_with("cognito-idp", endpoint_url=None)

    def test_endpoint_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """COGNITO_ENDPOINT is passed through as the client endpoint_url."""
        monkeypatch.setenv("COGNITO_ENDPOINT", "http://localhost:4566")

        with patch("src.utils.boto.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            get_cognito_client()

            mock_client.assert_called_once_with("cognito-idp", endpoint_url="http://localhost:4566")

    def test_https_endpoint_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An https endpoint override on a loopback host is accepted."""
        monkeypatch.setenv("COGNITO_ENDPOINT", "https://localhost:4566")

        with patch("src.utils.boto.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            get_cognito_client()

            mock_client.assert_called_once_with("cognito-idp", endpoint_url="https://localhost:4566")


class TestGetDynamodbClient:
    """Tests for the shared low-level DynamoDB client factory."""

    def test_default_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without DYNAMODB_ENDPOINT the client is built with no override."""
        monkeypatch.delenv("DYNAMODB_ENDPOINT", raising=False)

        with patch("src.utils.boto.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            get_dynamodb_client()

            mock_client.assert_called_once_with("dynamodb", endpoint_url=None)

    def test_endpoint_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DYNAMODB_ENDPOINT is passed through as the client endpoint_url."""
        monkeypatch.setenv("DYNAMODB_ENDPOINT", "http://localhost:4566")

        with patch("src.utils.boto.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            get_dynamodb_client()

            mock_client.assert_called_once_with("dynamodb", endpoint_url="http://localhost:4566")


class TestGetS3Client:
    """Tests for the shared S3 client factory and its test-override slot."""

    def test_default_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without S3_ENDPOINT the client is built with no override."""
        monkeypatch.delenv("S3_ENDPOINT", raising=False)

        with patch("src.utils.boto.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            get_s3_client()

            mock_client.assert_called_once_with("s3", endpoint_url=None)

    def test_endpoint_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """S3_ENDPOINT is passed through as the client endpoint_url."""
        monkeypatch.setenv("S3_ENDPOINT", "http://localhost:4566")

        with patch("src.utils.boto.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            get_s3_client()

            mock_client.assert_called_once_with("s3", endpoint_url="http://localhost:4566")

    def test_override_slot_returned_as_is(self) -> None:
        """A set override slot is returned without constructing a client."""
        sentinel_client = object()

        with patch("src.utils.boto.boto3.client") as mock_client:
            assert get_s3_client(sentinel_client) is sentinel_client
            mock_client.assert_not_called()

    def test_override_slot_wins_over_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The override slot takes precedence even when S3_ENDPOINT is set."""
        monkeypatch.setenv("S3_ENDPOINT", "http://localhost:4566")
        sentinel_client = object()

        with patch("src.utils.boto.boto3.client") as mock_client:
            assert get_s3_client(sentinel_client) is sentinel_client
            mock_client.assert_not_called()


class TestEndpointOverrideValidation:
    """Tests for centralized endpoint-override validation (#523).

    All three override variables share one validator, so the gate is asserted
    per variable through its factory: shape and loopback/private host policy.
    """

    @pytest.mark.parametrize(
        "env_name,factory",
        [
            ("S3_ENDPOINT", get_s3_client),
            ("COGNITO_ENDPOINT", get_cognito_client),
            ("DYNAMODB_ENDPOINT", get_dynamodb_client),
        ],
    )
    def test_missing_variable_is_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch, env_name: str, factory: Any
    ) -> None:
        """An unset override variable is valid (no endpoint passed)."""
        monkeypatch.delenv(env_name, raising=False)

        with patch("src.utils.boto.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            factory()

            assert mock_client.call_args.kwargs["endpoint_url"] is None

    @pytest.mark.parametrize(
        "env_name,factory,override",
        [
            ("S3_ENDPOINT", get_s3_client, "http://localhost:4566"),
            ("S3_ENDPOINT", get_s3_client, "http://127.0.0.1:4566"),
            ("S3_ENDPOINT", get_s3_client, "http://192.168.1.10:4566"),
            ("S3_ENDPOINT", get_s3_client, "http://10.0.0.5:4566"),
            ("S3_ENDPOINT", get_s3_client, "http://172.16.5.5:4566"),
            ("S3_ENDPOINT", get_s3_client, "http://localstack:4566"),
            ("COGNITO_ENDPOINT", get_cognito_client, "http://localhost:4566"),
            ("COGNITO_ENDPOINT", get_cognito_client, "http://192.168.1.10:4566"),
            ("COGNITO_ENDPOINT", get_cognito_client, "http://[::1]:4566"),
            ("DYNAMODB_ENDPOINT", get_dynamodb_client, "http://localhost:4566"),
            ("DYNAMODB_ENDPOINT", get_dynamodb_client, "http://192.168.1.10:4566"),
            ("DYNAMODB_ENDPOINT", get_dynamodb_client, "http://127.0.0.1:4566"),
        ],
    )
    def test_valid_override_is_passed_through(
        self, monkeypatch: pytest.MonkeyPatch, env_name: str, factory: Any, override: str
    ) -> None:
        """A loopback/private-range override is accepted and passed verbatim."""
        monkeypatch.setenv(env_name, override)

        with patch("src.utils.boto.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            factory()

            mock_client.assert_called_once_with(
                mock_client.call_args.args[0], endpoint_url=override
            )

    @pytest.mark.parametrize(
        "env_name,factory,bad_value",
        [
            ("S3_ENDPOINT", get_s3_client, "https://attacker.example.com"),
            ("S3_ENDPOINT", get_s3_client, "http://8.8.8.8:4566"),
            ("S3_ENDPOINT", get_s3_client, "localhost:4566"),
            ("S3_ENDPOINT", get_s3_client, "ftp://localhost:4566"),
            ("S3_ENDPOINT", get_s3_client, "http://"),
            ("S3_ENDPOINT", get_s3_client, ""),
            ("COGNITO_ENDPOINT", get_cognito_client, "https://attacker.example.com"),
            ("COGNITO_ENDPOINT", get_cognito_client, "http://8.8.8.8:4566"),
            ("COGNITO_ENDPOINT", get_cognito_client, "localhost:4566"),
            ("COGNITO_ENDPOINT", get_cognito_client, "ftp://localhost:4566"),
            ("COGNITO_ENDPOINT", get_cognito_client, "http://"),
            ("COGNITO_ENDPOINT", get_cognito_client, ""),
            ("DYNAMODB_ENDPOINT", get_dynamodb_client, "https://attacker.example.com"),
            ("DYNAMODB_ENDPOINT", get_dynamodb_client, "http://8.8.8.8:4566"),
            ("DYNAMODB_ENDPOINT", get_dynamodb_client, "localhost:4566"),
            ("DYNAMODB_ENDPOINT", get_dynamodb_client, "ftp://localhost:4566"),
            ("DYNAMODB_ENDPOINT", get_dynamodb_client, "http://"),
            ("DYNAMODB_ENDPOINT", get_dynamodb_client, ""),
        ],
    )
    def test_invalid_override_rejected(
        self, monkeypatch: pytest.MonkeyPatch, env_name: str, factory: Any, bad_value: str
    ) -> None:
        """A non-http(s), hostless, or public-host override raises ValueError (#523).

        Regression test: before the loopback/private gate, a valid but hostile
        URL (e.g. https://attacker.example.com) passed shape-only validation and
        silently redirected signed requests.
        """
        monkeypatch.setenv(env_name, bad_value)

        with patch("src.utils.boto.boto3.client") as mock_client:
            with pytest.raises(ValueError, match=env_name):
                factory()

            mock_client.assert_not_called()

    def test_rejection_message_names_variable_and_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The rejection names the variable and the rejected host."""
        monkeypatch.setenv("S3_ENDPOINT", "https://attacker.example.com")

        with pytest.raises(ValueError) as exc_info:
            get_s3_client()

        assert "S3_ENDPOINT" in str(exc_info.value)
        assert "attacker.example.com" in str(exc_info.value)
