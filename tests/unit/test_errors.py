"""Tests for error handling utilities."""

from src.utils.errors import AppError, ErrorCode


class TestAppError:
    """Tests for AppError class."""

    def test_app_error_with_message(self) -> None:
        """Test creating AppError with message."""
        error = AppError(ErrorCode.NOT_FOUND, "Profile not found")

        assert error.error_code == ErrorCode.NOT_FOUND
        assert error.message == "Profile not found"
        assert error.details == {}

    def test_app_error_with_details(self) -> None:
        """Test creating AppError with details."""
        details = {"profileId": "PROFILE#123"}
        error = AppError(ErrorCode.NOT_FOUND, "Profile not found", details)

        assert error.error_code == ErrorCode.NOT_FOUND
        assert error.message == "Profile not found"
        assert error.details == details

    def test_app_error_to_dict(self) -> None:
        """Test converting AppError to dict."""
        error = AppError(ErrorCode.FORBIDDEN, "Access denied", {"resource": "profile"})

        result = error.to_dict()

        assert result["errorCode"] == ErrorCode.FORBIDDEN
        assert result["message"] == "Access denied"
        assert result["resource"] == "profile"


class TestErrorCode:
    """Tests for ErrorCode constants."""

    def test_error_codes_defined(self) -> None:
        """Test that all expected error codes are defined."""
        assert ErrorCode.FORBIDDEN == "FORBIDDEN"
        assert ErrorCode.UNAUTHORIZED == "UNAUTHORIZED"
        assert ErrorCode.NOT_FOUND == "NOT_FOUND"
        assert ErrorCode.ALREADY_EXISTS == "ALREADY_EXISTS"
        assert ErrorCode.INVALID_INPUT == "INVALID_INPUT"
        assert ErrorCode.INVALID_PHONE == "INVALID_PHONE"
        assert ErrorCode.INVALID_ADDRESS == "INVALID_ADDRESS"
        assert ErrorCode.INVITE_EXPIRED == "INVITE_EXPIRED"
        assert ErrorCode.INVITE_ALREADY_USED == "INVITE_ALREADY_USED"
        assert ErrorCode.CAMPAIGN_READ_ONLY == "CAMPAIGN_READ_ONLY"
        assert ErrorCode.INSUFFICIENT_PERMISSIONS == "INSUFFICIENT_PERMISSIONS"
        assert ErrorCode.INTERNAL_ERROR == "INTERNAL_ERROR"
        assert ErrorCode.DATABASE_ERROR == "DATABASE_ERROR"
