"""Unit tests for src/handlers/payment_method_operations.py (Show & Sell
wave 5 fast-follow): Unit payment methods + the QR S3 flow."""

import os
from typing import Any, Dict
from uuid import uuid4

import boto3
import pytest
from moto import mock_aws

from src.handlers.payment_method_operations import handler
from src.utils.errors import ErrorCode

ACCOUNT_A = "ACCOUNT#user-123-456"


@pytest.fixture
def t(dynamodb_table: Any) -> Dict[str, Any]:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return {
        "units": dynamodb.Table("kernelworx-units-ue1-dev"),
        "unit_campaigns": dynamodb.Table("kernelworx-unit-campaigns-ue1-dev"),
    }


def _seed(t: Dict[str, Any]) -> None:
    t["units"].put_item(
        Item={
            "unitId": "unit-1",
            "itemKey": "METADATA",
            "accountId": ACCOUNT_A,
            "unitType": "Pack",
            "unitNumber": "1",
            "city": "D",
            "state": "CO",
            "displayName": "d",
            "timezone": "America/Denver",
            "splitDefault": "EQUAL",
            "councilNeedBasis": "PHYSICAL_STOCK",
            "metadataKey": "k",
            "adminCount": 1,
            "activeInviteCount": 0,
            "version": 1,
            "createdAt": "t",
            "updatedAt": "t",
            "createdByAccountId": ACCOUNT_A,
        }
    )
    t["units"].put_item(
        Item={
            "unitId": "unit-1",
            "itemKey": f"GRANT#{ACCOUNT_A}",
            "accountId": ACCOUNT_A,
            "role": "UNIT_ADMIN",
            "createdByAccountId": ACCOUNT_A,
            "createdAt": "t",
        }
    )


def _ev(field: str, args: Dict[str, Any], sub: str = "user-123-456") -> Dict[str, Any]:
    return {"arguments": args, "identity": {"sub": sub, "username": sub}, "info": {"fieldName": field}}


def _create(t: Dict[str, Any], name: str = "Venmo", key: str = "pm-create-01") -> Dict[str, Any]:
    return handler(
        _ev("createUnitPaymentMethod", {"unitId": "unit-1", "displayName": name, "idempotencyKey": key}), None
    )


class TestCreateAndList:
    def test_create_and_list_with_builtins(self, t: Dict[str, Any]) -> None:
        _seed(t)
        created = _create(t)
        assert created["paymentMethodId"] and created["isActive"] is True and created["isBuiltin"] is False
        listing = handler(_ev("unitPaymentMethods", {"unitId": "unit-1"}), None)
        codes = [m["normalizedName"] for m in listing]
        assert codes[:3] == ["CASH", "CHECK", "OTHER"]  # builtins computed first
        assert "VENMO" in codes

    def test_cap_and_validation(self, t: Dict[str, Any]) -> None:
        _seed(t)
        for i in range(50):
            result = _create(t, name=f"M{i}", key=f"pm-cap-{i:03d}")
            assert "paymentMethodId" in result, result
        blocked = _create(t, name="One More", key="pm-cap-050")
        assert blocked["errorCode"] == ErrorCode.CONFLICT
        long_name = _create(t, name="x" * 101, key="pm-long-001")
        assert long_name["errorCode"] == ErrorCode.INVALID_INPUT

    def test_non_admin_blocked(self, t: Dict[str, Any]) -> None:
        _seed(t)
        result = _create(
            t,
            key="pm-nonadm1",
        )
        assert "paymentMethodId" in result
        blocked = handler(
            _ev(
                "createUnitPaymentMethod",
                {"unitId": "unit-1", "displayName": "X", "idempotencyKey": "pm-nonadm2"},
                sub="user-789",
            ),
            None,
        )
        assert blocked["errorCode"] == ErrorCode.NOT_FOUND

    def test_replay(self, t: Dict[str, Any]) -> None:
        _seed(t)
        first = _create(t, key="pm-replay-1")
        second = _create(t, key="pm-replay-1")
        assert second == first


class TestUpdateAndDeactivate:
    def test_update_name(self, t: Dict[str, Any]) -> None:
        _seed(t)
        created = _create(t, key="pm-upd-001")
        result = handler(
            _ev(
                "updateUnitPaymentMethod",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "displayName": "Zelle",
                    "expectedVersion": 1,
                    "idempotencyKey": "pm-upd-002",
                },
            ),
            None,
        )
        assert result["displayName"] == "Zelle" and result["normalizedName"] == "ZELLE"

    def test_deactivate_and_builtin_guard(self, t: Dict[str, Any]) -> None:
        _seed(t)
        created = _create(t, key="pm-deact1")
        result = handler(
            _ev(
                "deactivateUnitPaymentMethod",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "expectedVersion": 1,
                    "idempotencyKey": "pm-deact2",
                },
            ),
            None,
        )
        assert result["isActive"] is False
        builtin = handler(
            _ev(
                "deactivateUnitPaymentMethod",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": "BUILTIN#CASH",
                    "expectedVersion": 1,
                    "idempotencyKey": "pm-deact3",
                },
            ),
            None,
        )
        assert builtin["errorCode"] == ErrorCode.INVALID_INPUT


class TestQrFlow:
    @pytest.fixture
    def s3_world(self, t: Dict[str, Any]) -> Any:
        with mock_aws():
            conn = boto3.client("s3", region_name="us-east-1")
            conn.create_bucket(Bucket="kernelworx-exports-ue1-dev")
            os.environ["EXPORTS_BUCKET"] = "kernelworx-exports-ue1-dev"
            yield t
            os.environ.pop("EXPORTS_BUCKET", None)

    def _created(self, t: Dict[str, Any]) -> Dict[str, Any]:
        _seed(t)
        return _create(t, key=f"pm-qr-{uuid4()}")

    def test_request_confirm_delete_round_trip(self, s3_world: Dict[str, Any]) -> None:
        created = self._created(s3_world)
        requested = handler(
            _ev(
                "requestUnitPaymentMethodQrUpload",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "contentType": "image/png",
                    "idempotencyKey": "pm-qr-req1",
                },
            ),
            None,
        )
        assert requested["uploadUrl"] and requested["s3Key"].startswith(
            f"payment-qr-codes/units/unit-1/{created['paymentMethodId']}/"
        )
        # Replay returns the same URL/key.
        replayed = handler(
            _ev(
                "requestUnitPaymentMethodQrUpload",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "contentType": "image/png",
                    "idempotencyKey": "pm-qr-req1",
                },
            ),
            None,
        )
        assert replayed == requested
        confirmed = handler(
            _ev(
                "confirmUnitPaymentMethodQrUpload",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "expectedVersion": 1,
                    "s3Key": requested["s3Key"],
                    "idempotencyKey": "pm-qr-con1",
                },
            ),
            None,
        )
        assert confirmed["qrCodeS3Key"] == requested["s3Key"]
        deleted = handler(
            _ev(
                "deleteUnitPaymentMethodQrCode",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "expectedVersion": 2,
                    "idempotencyKey": "pm-qr-del1",
                },
            ),
            None,
        )
        assert deleted["qrCodeS3Key"] is None

    def test_prefix_and_content_type_guards(self, s3_world: Dict[str, Any]) -> None:
        created = self._created(s3_world)
        bad_type = handler(
            _ev(
                "requestUnitPaymentMethodQrUpload",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "contentType": "application/pdf",
                    "idempotencyKey": "pm-qr-bad1",
                },
            ),
            None,
        )
        assert bad_type["errorCode"] == ErrorCode.INVALID_INPUT
        bad_key = handler(
            _ev(
                "confirmUnitPaymentMethodQrUpload",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "expectedVersion": 1,
                    "s3Key": "payment-qr-codes/other/unit/x.png",
                    "idempotencyKey": "pm-qr-bad2",
                },
            ),
            None,
        )
        assert bad_key["errorCode"] == ErrorCode.INVALID_INPUT

    def test_inactive_method_cannot_take_qr(self, s3_world: Dict[str, Any]) -> None:
        created = self._created(s3_world)
        handler(
            _ev(
                "deactivateUnitPaymentMethod",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "expectedVersion": 1,
                    "idempotencyKey": "pm-qr-ina1",
                },
            ),
            None,
        )
        blocked = handler(
            _ev(
                "requestUnitPaymentMethodQrUpload",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "contentType": "image/png",
                    "idempotencyKey": "pm-qr-ina2",
                },
            ),
            None,
        )
        assert blocked["errorCode"] == ErrorCode.CONFLICT


class TestSweep:
    def test_unauthorized_and_unknown(self, t: Dict[str, Any]) -> None:
        _seed(t)
        event = _ev("createUnitPaymentMethod", {"unitId": "unit-1", "displayName": "X", "idempotencyKey": "pm-sw-0001"})
        del event["identity"]
        assert handler(event, None)["errorCode"] == ErrorCode.UNAUTHORIZED
        assert handler(_ev("mysteryField", {}), None)["errorCode"] == ErrorCode.INTERNAL_ERROR

    def test_missing_method_and_version_mismatch(self, t: Dict[str, Any]) -> None:
        _seed(t)
        missing = handler(
            _ev(
                "updateUnitPaymentMethod",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": "PM#ghost",
                    "displayName": "X",
                    "expectedVersion": 1,
                    "idempotencyKey": "pm-sw-0002",
                },
            ),
            None,
        )
        assert missing["errorCode"] == ErrorCode.NOT_FOUND
        created = _create(t, key="pm-sw-0003")
        stale = handler(
            _ev(
                "deactivateUnitPaymentMethod",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "expectedVersion": 9,
                    "idempotencyKey": "pm-sw-0004",
                },
            ),
            None,
        )
        assert stale["errorCode"] == ErrorCode.CONFLICT
        confirm_stale = handler(
            _ev(
                "confirmUnitPaymentMethodQrUpload",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "expectedVersion": 9,
                    "s3Key": f"payment-qr-codes/units/unit-1/{created['paymentMethodId']}/x.png",
                    "idempotencyKey": "pm-sw-0005",
                },
            ),
            None,
        )
        assert confirm_stale["errorCode"] == ErrorCode.CONFLICT
        delete_stale = handler(
            _ev(
                "deleteUnitPaymentMethodQrCode",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "expectedVersion": 9,
                    "idempotencyKey": "pm-sw-0006",
                },
            ),
            None,
        )
        assert delete_stale["errorCode"] == ErrorCode.CONFLICT

    def test_marker_conflict_and_missing_result(self, t: Dict[str, Any]) -> None:
        _seed(t)
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#createUnitPaymentMethod#pm-sw-0007",
                "idemFingerprint": "other",
                "idemResult": {},
            }
        )
        conflict = _create(t, key="pm-sw-0007")
        assert conflict["errorCode"] == ErrorCode.CONFLICT
        from src.handlers.payment_method_operations import _check_marker, _marker_put

        no_result = _marker_put(ACCOUNT_A, "scope", "key", "fp", None, 1000)
        assert no_result["Put"]["Item"]["idemResult"] is None
        t["units"].put_item(
            Item={"unitId": "__IDEM__", "itemKey": f"{ACCOUNT_A}#scope#pm-sw-0008", "idemFingerprint": "fp"}
        )
        with pytest.raises(Exception):
            _check_marker(
                t["units"].get_item(Key={"unitId": "__IDEM__", "itemKey": f"{ACCOUNT_A}#scope#pm-sw-0008"})["Item"],
                "fp",
            )

    def test_builtin_guards_on_update_confirm_delete(self, t: Dict[str, Any]) -> None:
        _seed(t)
        for field, args in [
            ("updateUnitPaymentMethod", {"displayName": "X"}),
            ("confirmUnitPaymentMethodQrUpload", {"s3Key": "payment-qr-codes/units/unit-1/BUILTIN#CASH/x.png"}),
            ("deleteUnitPaymentMethodQrCode", {}),
        ]:
            result = handler(
                _ev(
                    field,
                    {
                        "unitId": "unit-1",
                        "paymentMethodId": "BUILTIN#CASH",
                        "expectedVersion": 1,
                        "idempotencyKey": f"pm-bg-{field[:8]}",
                        **args,
                    },
                ),
                None,
            )
            assert result["errorCode"] == ErrorCode.INVALID_INPUT, result

    def test_marker_race_mapping(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from unittest.mock import MagicMock

        from src.handlers import payment_method_operations
        from src.utils.dynamodb import TransactionCancelledError

        _seed(t)

        def _cancel_on_marker(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(payment_method_operations, "execute_transaction", _cancel_on_marker)
        raced = _create(t, key="pm-race-01")
        assert raced["errorCode"] == ErrorCode.CONFLICT

        def _cancel_on_first(plan: Any, **kwargs: Any) -> None:
            raise TransactionCancelledError([0])

        monkeypatch.setattr(payment_method_operations, "execute_transaction", _cancel_on_first)
        with pytest.raises(TransactionCancelledError):
            payment_method_operations._create_payment_method(
                _ev(
                    "createUnitPaymentMethod", {"unitId": "unit-1", "displayName": "Y", "idempotencyKey": "pm-race-02"}
                ),
                None,
            )

    def test_missing_marker_result_branches(self, t: Dict[str, Any]) -> None:
        import json as _json

        _seed(t)
        fingerprint = _json.dumps(
            {"unitId": "unit-1", "displayName": "Wire", "idempotencyKey": "pm-mr-0001", "actor": ACCOUNT_A},
            sort_keys=True,
            separators=(",", ":"),
        )
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#createUnitPaymentMethod#pm-mr-0001",
                "idemFingerprint": fingerprint,
            }
        )
        result = _create(t, name="Wire", key="pm-mr-0001")
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

    def test_update_replay(self, t: Dict[str, Any]) -> None:
        _seed(t)
        created = _create(t, key="pm-ur-0001")
        args = {
            "unitId": "unit-1",
            "paymentMethodId": created["paymentMethodId"],
            "displayName": "Renamed",
            "expectedVersion": 1,
            "idempotencyKey": "pm-ur-0002",
        }
        first = handler(_ev("updateUnitPaymentMethod", args), None)
        second = handler(_ev("updateUnitPaymentMethod", args), None)
        assert second == first

    def test_input_wrapped_marker_key_and_replays(self, t: Dict[str, Any]) -> None:
        from src.handlers.payment_method_operations import _idempotency_begin

        _seed(t)
        event = _ev("mystery", {})
        _, _, _ = _idempotency_begin(event, {"input": {"idempotencyKey": "pm-ik-0001"}}, "scope")
        # confirm + delete replay paths
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="kernelworx-exports-ue1-dev")
            os.environ["EXPORTS_BUCKET"] = "kernelworx-exports-ue1-dev"
            created = _create(t, key="pm-ik-0002")
            requested = handler(
                _ev(
                    "requestUnitPaymentMethodQrUpload",
                    {
                        "unitId": "unit-1",
                        "paymentMethodId": created["paymentMethodId"],
                        "contentType": "image/png",
                        "idempotencyKey": "pm-ik-0003",
                    },
                ),
                None,
            )
            confirm_args = {
                "unitId": "unit-1",
                "paymentMethodId": created["paymentMethodId"],
                "expectedVersion": 1,
                "s3Key": requested["s3Key"],
                "idempotencyKey": "pm-ik-0004",
            }
            first = handler(_ev("confirmUnitPaymentMethodQrUpload", confirm_args), None)
            second = handler(_ev("confirmUnitPaymentMethodQrUpload", confirm_args), None)
            assert second == first
            delete_args = {
                "unitId": "unit-1",
                "paymentMethodId": created["paymentMethodId"],
                "expectedVersion": 2,
                "idempotencyKey": "pm-ik-0005",
            }
            first_d = handler(_ev("deleteUnitPaymentMethodQrCode", delete_args), None)
            second_d = handler(_ev("deleteUnitPaymentMethodQrCode", delete_args), None)
            assert second_d == first_d
            os.environ.pop("EXPORTS_BUCKET", None)

    def test_missing_bucket_branch(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        _seed(t)
        created = _create(t, key="pm-mb-0001")
        os.environ.pop("EXPORTS_BUCKET", None)
        result = handler(
            _ev(
                "requestUnitPaymentMethodQrUpload",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "contentType": "image/png",
                    "idempotencyKey": "pm-mb-0002",
                },
            ),
            None,
        )
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

    def test_delete_without_bucket_skips_s3(self, t: Dict[str, Any]) -> None:
        """A delete with no configured bucket still clears the stored key."""
        _seed(t)
        created = _create(t, key="pm-db-0001")
        t["units"].update_item(
            Key={"unitId": "unit-1", "itemKey": f"PAYMENT#{created['paymentMethodId']}"},
            UpdateExpression="SET qrCodeS3Key = :k",
            ExpressionAttributeValues={":k": "payment-qr-codes/units/unit-1/x/y.png"},
        )
        os.environ.pop("EXPORTS_BUCKET", None)
        result = handler(
            _ev(
                "deleteUnitPaymentMethodQrCode",
                {
                    "unitId": "unit-1",
                    "paymentMethodId": created["paymentMethodId"],
                    "expectedVersion": 1,
                    "idempotencyKey": "pm-db-0002",
                },
            ),
            None,
        )
        assert result["qrCodeS3Key"] is None
