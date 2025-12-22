"""Tests for error handling utilities."""

from src.utils.errors import AppError, ErrorCode, create_error_response, handle_error


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


class TestHandleError:
    """Tests for handle_error function."""

    def test_handle_app_error(self) -> None:
        """Test handling AppError returns error dict."""
        error = AppError(ErrorCode.INVALID_INPUT, "Bad request", {"field": "name"})

        result = handle_error(error)

        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        assert result["message"] == "Bad request"
        assert result["field"] == "name"

    def test_handle_generic_exception(self) -> None:
        """Test handling generic exception returns internal error."""
        error = ValueError("Unexpected error")

        result = handle_error(error)

        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
        assert "unexpected" in result["message"].lower()


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


class TestCreateErrorResponse:
    """Tests for create_error_response function."""

    def test_create_error_response(self) -> None:
        """Test creating error response dictionary."""
        result = create_error_response(ErrorCode.NOT_FOUND, "Profile not found")

        assert result["errorCode"] == ErrorCode.NOT_FOUND
        assert result["message"] == "Profile not found"
        assert isinstance(result, dict)

    def test_create_error_response_with_different_code(self) -> None:
        """Test creating error response with different error code."""
        result = create_error_response(ErrorCode.FORBIDDEN, "Access denied")

        assert result["errorCode"] == ErrorCode.FORBIDDEN
        assert result["message"] == "Access denied"


class TestValidationError:
    """Tests for ValidationError convenience class."""

    def test_validation_error_basic(self) -> None:
        """Test creating ValidationError with message only."""
        from src.utils.errors import ValidationError

        error = ValidationError("Field is required")

        assert error.error_code == ErrorCode.INVALID_INPUT
        assert error.message == "Field is required"
        assert error.details == {}

    def test_validation_error_with_details(self) -> None:
        """Test creating ValidationError with details."""
        from src.utils.errors import ValidationError

        error = ValidationError("Field is invalid", {"field": "email"})

        assert error.error_code == ErrorCode.INVALID_INPUT
        assert error.message == "Field is invalid"
        assert error.details == {"field": "email"}


class TestAuthorizationError:
    """Tests for AuthorizationError convenience class."""

    def test_authorization_error_basic(self) -> None:
        """Test creating AuthorizationError with message only."""
        from src.utils.errors import AuthorizationError

        error = AuthorizationError("Access denied")

        assert error.error_code == ErrorCode.FORBIDDEN
        assert error.message == "Access denied"
        assert error.details == {}

    def test_authorization_error_with_details(self) -> None:
        """Test creating AuthorizationError with details."""
        from src.utils.errors import AuthorizationError

        error = AuthorizationError("Access denied", {"resource": "profile"})

        assert error.error_code == ErrorCode.FORBIDDEN
        assert error.message == "Access denied"
        assert error.details == {"resource": "profile"}
