"""Unit tests for AppSync VTL mapping templates.

These tests render the Velocity templates with a small in-process engine so we
can assert observable resolver behavior (authorization, filtering, error
handling) without relying on string matching.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

import airspeed
import pytest

MAPPING_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "tofu" / "application" / "appsync" / "mapping-templates"


class _Util:
    """Minimal mock for AppSync ``$util`` functions used by the templates."""

    def toJson(self, obj: Any) -> str:
        return json.dumps(obj)

    def error(self, message: str, error_type: str) -> None:
        raise RuntimeError(f"{error_type}: {message}")


def _render(template_name: str, ctx: Dict[str, Any]) -> str:
    """Render a mapping template with the supplied AppSync context.

    Re-raises the original resolver-side exception so tests can assert on the
    error type and message AppSync would surface.
    """
    template_path = MAPPING_TEMPLATES_DIR / template_name
    template = airspeed.Template(template_path.read_text())
    try:
        return template.merge({"ctx": ctx, "util": _Util()}).strip()
    except airspeed.TemplateExecutionError as exc:
        if exc.__cause__ is not None:
            raise exc.__cause__ from None
        raise


def _catalog_result(
    *,
    catalog_id: str = "CATALOG#test",
    is_public: Any = "true",
    owner_account_id: Optional[str] = "ACCOUNT#owner-1",
    is_deleted: Any = False,
) -> Dict[str, Any]:
    """Build a DynamoDB-style catalog result for VTL rendering."""
    result: Dict[str, Any] = {
        "catalogId": catalog_id,
        "isPublic": is_public,
    }
    if owner_account_id is not None:
        result["ownerAccountId"] = owner_account_id
    if is_deleted is not None:
        result["isDeleted"] = is_deleted
    return result


class TestGetCatalogResponse:
    """Authorization behavior of the ``getCatalog`` response template."""

    @pytest.mark.parametrize("is_public", ["true", True])
    def test_public_catalog_is_returned(self, is_public: Any) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "any-caller"},
            "result": _catalog_result(is_public=is_public),
        }

        output = _render("get_catalog_response.vtl", ctx)

        assert json.loads(output)["catalogId"] == "CATALOG#test"

    def test_private_catalog_owned_by_caller_is_returned(self) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "owner-1"},
            "result": _catalog_result(is_public="false"),
        }

        output = _render("get_catalog_response.vtl", ctx)

        assert json.loads(output)["catalogId"] == "CATALOG#test"

    def test_private_catalog_owned_by_another_is_hidden(self) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "other-caller"},
            "result": _catalog_result(is_public="false"),
        }

        output = _render("get_catalog_response.vtl", ctx)

        assert json.loads(output) is None

    @pytest.mark.parametrize("is_deleted", ["true", True])
    def test_deleted_catalog_is_hidden(self, is_deleted: Any) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "owner-1"},
            "result": _catalog_result(is_public="true", is_deleted=is_deleted),
        }

        output = _render("get_catalog_response.vtl", ctx)

        assert json.loads(output) is None

    @pytest.mark.parametrize("result", [None, {}])
    def test_missing_catalog_returns_null(self, result: Any) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "owner-1"},
            "result": result,
        }

        output = _render("get_catalog_response.vtl", ctx)

        assert json.loads(output) is None

    def test_resolver_error_is_propagated(self) -> None:
        ctx = {
            "error": {"message": "DynamoDB failure", "type": "DynamoDB:UserError"},
            "identity": {"sub": "owner-1"},
            "result": _catalog_result(),
        }

        with pytest.raises(RuntimeError, match="DynamoDB:UserError"):
            _render("get_catalog_response.vtl", ctx)


class TestCampaignCatalogResponse:
    """Authorization behavior of the ``Campaign.catalog`` field resolver."""

    @pytest.mark.parametrize("is_public", ["true", True])
    def test_public_catalog_is_returned(self, is_public: Any) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "any-caller"},
            "result": _catalog_result(is_public=is_public),
            "source": {"catalogId": "CATALOG#test"},
        }

        output = _render("campaign_catalog_response.vtl", ctx)

        assert json.loads(output)["catalogId"] == "CATALOG#test"

    def test_private_catalog_owned_by_caller_is_returned(self) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "owner-1"},
            "result": _catalog_result(is_public="false"),
            "source": {"catalogId": "CATALOG#test"},
        }

        output = _render("campaign_catalog_response.vtl", ctx)

        assert json.loads(output)["catalogId"] == "CATALOG#test"

    def test_private_catalog_owned_by_another_is_hidden(self) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "other-caller"},
            "result": _catalog_result(is_public="false"),
            "source": {"catalogId": "CATALOG#test"},
        }

        output = _render("campaign_catalog_response.vtl", ctx)

        assert json.loads(output) is None

    @pytest.mark.parametrize("is_deleted", ["true", True])
    def test_deleted_catalog_is_hidden(self, is_deleted: Any) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "owner-1"},
            "result": _catalog_result(is_public="true", is_deleted=is_deleted),
            "source": {"catalogId": "CATALOG#test"},
        }

        output = _render("campaign_catalog_response.vtl", ctx)

        assert json.loads(output) is None

    @pytest.mark.parametrize("result", [None, {}])
    def test_missing_catalog_returns_null(self, result: Any) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "owner-1"},
            "result": result,
            "source": {"catalogId": "CATALOG#missing"},
        }

        output = _render("campaign_catalog_response.vtl", ctx)

        assert json.loads(output) is None

    def test_resolver_error_is_propagated(self) -> None:
        ctx = {
            "error": {"message": "DynamoDB failure", "type": "DynamoDB:UserError"},
            "identity": {"sub": "owner-1"},
            "result": _catalog_result(),
            "source": {"catalogId": "CATALOG#test"},
        }

        with pytest.raises(RuntimeError, match="DynamoDB:UserError"):
            _render("campaign_catalog_response.vtl", ctx)


class TestSharedCampaignCatalogResponse:
    """Authorization behavior of the ``SharedCampaign.catalog`` field resolver."""

    @pytest.mark.parametrize("is_public", ["true", True])
    def test_public_catalog_is_returned(self, is_public: Any) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "any-caller"},
            "result": _catalog_result(is_public=is_public),
            "source": {"catalogId": "CATALOG#test"},
        }

        output = _render("shared_campaign_catalog_response.vtl", ctx)

        assert json.loads(output)["catalogId"] == "CATALOG#test"

    def test_private_catalog_owned_by_caller_is_returned(self) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "owner-1"},
            "result": _catalog_result(is_public="false"),
            "source": {"catalogId": "CATALOG#test"},
        }

        output = _render("shared_campaign_catalog_response.vtl", ctx)

        assert json.loads(output)["catalogId"] == "CATALOG#test"

    def test_private_catalog_owned_by_another_is_hidden(self) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "other-caller"},
            "result": _catalog_result(is_public="false"),
            "source": {"catalogId": "CATALOG#test"},
        }

        output = _render("shared_campaign_catalog_response.vtl", ctx)

        assert json.loads(output) is None

    @pytest.mark.parametrize("is_deleted", ["true", True])
    def test_deleted_catalog_is_hidden(self, is_deleted: Any) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "owner-1"},
            "result": _catalog_result(is_public="true", is_deleted=is_deleted),
            "source": {"catalogId": "CATALOG#test"},
        }

        output = _render("shared_campaign_catalog_response.vtl", ctx)

        assert json.loads(output) is None

    @pytest.mark.parametrize("result", [None, {}])
    def test_missing_catalog_returns_null(self, result: Any) -> None:
        ctx = {
            "error": None,
            "identity": {"sub": "owner-1"},
            "result": result,
            "source": {"catalogId": "CATALOG#missing"},
        }

        output = _render("shared_campaign_catalog_response.vtl", ctx)

        assert json.loads(output) is None

    def test_resolver_error_is_propagated(self) -> None:
        ctx = {
            "error": {"message": "DynamoDB failure", "type": "DynamoDB:UserError"},
            "identity": {"sub": "owner-1"},
            "result": _catalog_result(),
            "source": {"catalogId": "CATALOG#test"},
        }

        with pytest.raises(RuntimeError, match="DynamoDB:UserError"):
            _render("shared_campaign_catalog_response.vtl", ctx)
