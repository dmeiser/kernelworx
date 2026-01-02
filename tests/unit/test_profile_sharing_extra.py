import pytest

from src.utils.errors import AppError, ErrorCode


def test_list_my_shares_outer_exception(monkeypatch, appsync_event, lambda_context):
    # Simulate get_shares_table raising to exercise outer exception handler
    def raise_exc():
        raise Exception("boom")

    monkeypatch.setattr("src.handlers.profile_sharing.get_shares_table", raise_exc)

    with pytest.raises(AppError) as excinfo:
        from src.handlers.profile_sharing import list_my_shares

        event = {**appsync_event, "identity": {"sub": "user-1"}}
        list_my_shares(event, lambda_context)

    assert excinfo.value.error_code == ErrorCode.INTERNAL_ERROR
    assert "Failed to list shared profiles" in excinfo.value.message
