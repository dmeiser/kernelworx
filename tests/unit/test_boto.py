"""Tests for src/utils/boto.py - shared boto3 client factories (#523, #575)."""

from unittest.mock import MagicMock, patch

import pytest

from src.utils.boto import get_cognito_client, get_s3_client


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
        """An https endpoint override is accepted."""
        monkeypatch.setenv("COGNITO_ENDPOINT", "https://cognito-idp.us-east-1.amazonaws.com")

        with patch("src.utils.boto.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            get_cognito_client()

            mock_client.assert_called_once_with(
                "cognito-idp", endpoint_url="https://cognito-idp.us-east-1.amazonaws.com"
            )


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
    """Tests for centralized endpoint-override validation (#523)."""

    @pytest.mark.parametrize("env_name", ["S3_ENDPOINT", "COGNITO_ENDPOINT"])
    def test_missing_variable_is_not_an_error(self, monkeypatch: pytest.MonkeyPatch, env_name: str) -> None:
        """An unset override variable is valid (no endpoint passed)."""
        monkeypatch.delenv(env_name, raising=False)

        with patch("src.utils.boto.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            if env_name == "S3_ENDPOINT":
                get_s3_client()
            else:
                get_cognito_client()

            assert mock_client.call_args.kwargs["endpoint_url"] is None

    @pytest.mark.parametrize(
        "bad_value",
        [
            "localhost:4566",
            "ftp://localhost:4566",
            "http://",
            "",
        ],
    )
    def test_invalid_s3_endpoint_rejected(self, monkeypatch: pytest.MonkeyPatch, bad_value: str) -> None:
        """An S3_ENDPOINT that is not an http(s) URL with a host raises ValueError."""
        monkeypatch.setenv("S3_ENDPOINT", bad_value)

        with pytest.raises(ValueError, match="S3_ENDPOINT"):
            get_s3_client()

    @pytest.mark.parametrize(
        "bad_value",
        [
            "localhost:4566",
            "ftp://localhost:4566",
            "http://",
            "",
        ],
    )
    def test_invalid_cognito_endpoint_rejected(self, monkeypatch: pytest.MonkeyPatch, bad_value: str) -> None:
        """A COGNITO_ENDPOINT that is not an http(s) URL with a host raises ValueError."""
        monkeypatch.setenv("COGNITO_ENDPOINT", bad_value)

        with pytest.raises(ValueError, match="COGNITO_ENDPOINT"):
            get_cognito_client()
