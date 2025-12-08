"""Tests for exception handling in profile sharing handlers."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.profile_sharing import (
    create_profile_invite,
    redeem_profile_invite,
    share_profile_direct,
)
from src.utils.errors import AppError, ErrorCode


class TestExceptionHandling:
    """Tests for exception handling in Lambda handlers."""

    @patch("src.handlers.profile_sharing.get_table")
    def test_create_invite_database_error(
        self,
        mock_get_table: MagicMock,
        sample_profile_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that database errors are handled in create_invite."""
        # Mock table to raise exception
        mock_table = MagicMock()
        mock_table.get_item.side_effect = Exception("Database connection failed")
        mock_get_table.return_value = mock_table

        event = {
            **appsync_event,
            "arguments": {
                "profileId": sample_profile_id,
                "permissions": ["READ"],
            },
        }

        with pytest.raises(AppError) as exc_info:
            create_profile_invite(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    @patch("src.handlers.profile_sharing.get_table")
    def test_redeem_invite_database_error(
        self,
        mock_get_table: MagicMock,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        another_account_id: str,
    ) -> None:
        """Test that database errors are handled in redeem_invite."""
        # Mock table to raise exception
        mock_table = MagicMock()
        mock_table.scan.side_effect = Exception("Database connection failed")
        mock_get_table.return_value = mock_table

        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {"inviteCode": "TEST123456"},
        }

        with pytest.raises(AppError) as exc_info:
            redeem_profile_invite(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    @patch("src.handlers.profile_sharing.get_table")
    def test_share_direct_database_error(
        self,
        mock_get_table: MagicMock,
        sample_profile_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        another_account_id: str,
    ) -> None:
        """Test that database errors are handled in share_direct."""
        # Mock table to raise exception
        mock_table = MagicMock()
        mock_table.get_item.side_effect = Exception("Database connection failed")
        mock_get_table.return_value = mock_table

        event = {
            **appsync_event,
            "arguments": {
                "profileId": sample_profile_id,
                "targetAccountId": another_account_id,
                "permissions": ["READ"],
            },
        }

        with pytest.raises(AppError) as exc_info:
            share_profile_direct(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    # NOTE: test_revoke_share_database_error removed - revoke_share was migrated to VTL resolver
