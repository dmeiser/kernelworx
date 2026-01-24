"""Tests for ResolverBuilder class."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cdk.appsync.resolver_builder import ResolverBuilder


@pytest.fixture
def mock_api():
    """Create a mock AppSync GraphQL API."""
    api = MagicMock()
    api.create_resolver.return_value = MagicMock(name="resolver")
    return api


@pytest.fixture
def mock_datasources():
    """Create mock datasources dict."""
    datasources = {}
    for name in ["accounts", "profiles", "campaigns", "orders", "shares", "catalogs", "none"]:
        ds = MagicMock()
        ds.create_resolver.return_value = MagicMock(name=f"{name}_resolver")
        datasources[name] = ds
    return datasources


@pytest.fixture
def mock_lambda_datasources():
    """Create mock Lambda datasources dict."""
    lambda_ds = {}
    for name in ["create_profile", "campaign_operations", "request_campaign_report"]:
        ds = MagicMock()
        ds.create_resolver.return_value = MagicMock(name=f"{name}_resolver")
        lambda_ds[name] = ds
    return lambda_ds


@pytest.fixture
def mock_scope():
    """Create a mock CDK construct scope."""
    return MagicMock()


@pytest.fixture
def builder(mock_api, mock_datasources, mock_lambda_datasources, mock_scope):
    """Create a ResolverBuilder instance."""
    return ResolverBuilder(
        api=mock_api,
        datasources=mock_datasources,
        lambda_datasources=mock_lambda_datasources,
        scope=mock_scope,
    )


class TestResolverBuilderInit:
    """Tests for ResolverBuilder initialization."""

    def test_init_stores_api(self, builder, mock_api):
        """Builder stores the API reference."""
        assert builder.api is mock_api

    def test_init_stores_datasources(self, builder, mock_datasources):
        """Builder stores datasources dictionary."""
        assert builder.datasources is mock_datasources

    def test_init_stores_lambda_datasources(self, builder, mock_lambda_datasources):
        """Builder stores Lambda datasources dictionary."""
        assert builder.lambda_datasources is mock_lambda_datasources

    def test_init_stores_scope(self, builder, mock_scope):
        """Builder stores the CDK scope."""
        assert builder.scope is mock_scope


class TestCreateVtlResolver:
    """Tests for VTL resolver creation."""

    def test_create_vtl_resolver_calls_datasource_create_resolver(self, builder):
        """VTL resolver uses datasource.create_resolver()."""
        req_template = Path("/path/to/request.vtl")
        resp_template = Path("/path/to/response.vtl")

        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_appsync.MappingTemplate.from_file.side_effect = lambda x: f"template:{x}"

            builder.create_vtl_resolver(
                field_name="getMyAccount",
                type_name="Query",
                datasource_name="accounts",
                request_template=req_template,
                response_template=resp_template,
            )

        builder.datasources["accounts"].create_resolver.assert_called_once()
        call_args = builder.datasources["accounts"].create_resolver.call_args
        assert call_args[0][0] == "getMyAccountResolver"  # resolver ID
        assert call_args[1]["type_name"] == "Query"
        assert call_args[1]["field_name"] == "getMyAccount"

    def test_create_vtl_resolver_with_custom_id_suffix(self, builder):
        """VTL resolver respects custom ID suffix."""
        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_appsync.MappingTemplate.from_file.side_effect = lambda x: f"template:{x}"

            builder.create_vtl_resolver(
                field_name="getMyAccount",
                type_name="Query",
                datasource_name="accounts",
                request_template=Path("/path/to/request.vtl"),
                response_template=Path("/path/to/response.vtl"),
                id_suffix="CustomAccountResolver",
            )

        call_args = builder.datasources["accounts"].create_resolver.call_args
        assert call_args[0][0] == "CustomAccountResolver"


class TestCreateJsResolver:
    """Tests for JavaScript resolver creation."""

    def test_create_js_resolver_calls_datasource_create_resolver(self, builder):
        """JS resolver uses datasource.create_resolver()."""
        code_file = Path("/path/to/resolver.js")

        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_appsync.FunctionRuntime.JS_1_0_0 = "JS_1_0_0"
            mock_appsync.Code.from_asset.return_value = "js_code"

            builder.create_js_resolver(
                field_name="listMyProfiles",
                type_name="Query",
                datasource_name="profiles",
                code_file=code_file,
            )

        builder.datasources["profiles"].create_resolver.assert_called_once()
        call_args = builder.datasources["profiles"].create_resolver.call_args
        assert call_args[0][0] == "listMyProfilesResolver"
        assert call_args[1]["type_name"] == "Query"
        assert call_args[1]["field_name"] == "listMyProfiles"
        assert call_args[1]["runtime"] == "JS_1_0_0"

    def test_create_js_resolver_on_api_calls_api_create_resolver(self, builder, mock_api):
        """JS on API resolver uses api.create_resolver()."""
        code_file = Path("/path/to/resolver.js")

        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_appsync.FunctionRuntime.JS_1_0_0 = "JS_1_0_0"
            mock_appsync.Code.from_asset.return_value = "js_code"

            builder.create_js_resolver_on_api(
                field_name="listMyProfiles",
                type_name="Query",
                datasource_name="profiles",
                code_file=code_file,
            )

        mock_api.create_resolver.assert_called_once()
        call_args = mock_api.create_resolver.call_args
        assert call_args[0][0] == "listMyProfilesResolver"
        assert call_args[1]["data_source"] == builder.datasources["profiles"]


class TestCreatePipelineResolver:
    """Tests for pipeline resolver creation."""

    def test_create_pipeline_resolver_calls_api_create_resolver(self, builder, mock_api):
        """Pipeline resolver uses api.create_resolver()."""
        code_file = Path("/path/to/pipeline.js")
        functions = [MagicMock(), MagicMock()]

        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_appsync.FunctionRuntime.JS_1_0_0 = "JS_1_0_0"
            mock_appsync.Code.from_asset.return_value = "js_code"

            builder.create_pipeline_resolver(
                field_name="createProfileInvite",
                type_name="Mutation",
                functions=functions,
                code_file=code_file,
            )

        mock_api.create_resolver.assert_called_once()
        call_args = mock_api.create_resolver.call_args
        assert call_args[0][0] == "createProfileInvitePipelineResolver"
        assert call_args[1]["pipeline_config"] == functions

    def test_create_pipeline_resolver_with_custom_id(self, builder, mock_api):
        """Pipeline resolver respects custom ID suffix."""
        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_appsync.FunctionRuntime.JS_1_0_0 = "JS_1_0_0"
            mock_appsync.Code.from_asset.return_value = "js_code"

            builder.create_pipeline_resolver(
                field_name="createProfileInvite",
                type_name="Mutation",
                functions=[],
                code_file=Path("/path/to/pipeline.js"),
                id_suffix="CustomPipeline",
            )

        call_args = mock_api.create_resolver.call_args
        assert call_args[0][0] == "CustomPipeline"


class TestCreatePipelineResolverOnScope:
    """Tests for scope-based pipeline resolver creation (backwards compatibility)."""

    def test_create_pipeline_resolver_on_scope_uses_resolver_construct(self, builder, mock_scope, mock_api):
        """Pipeline resolver on scope uses appsync.Resolver construct."""
        code_file = Path("/path/to/pipeline.js")
        functions = [MagicMock(), MagicMock()]

        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_resolver = MagicMock()
            mock_appsync.Resolver.return_value = mock_resolver
            mock_appsync.FunctionRuntime.JS_1_0_0 = "JS_1_0_0"
            mock_appsync.Code.from_asset.return_value = "js_code"

            result = builder.create_pipeline_resolver_on_scope(
                field_name="deleteCatalog",
                type_name="Mutation",
                functions=functions,
                code_file=code_file,
            )

        mock_appsync.Resolver.assert_called_once()
        call_args = mock_appsync.Resolver.call_args
        assert call_args[0][0] == mock_scope
        assert call_args[0][1] == "deleteCatalogPipelineResolver"
        assert call_args[1]["pipeline_config"] == functions
        assert result == mock_resolver

    def test_create_pipeline_resolver_on_scope_with_custom_id(self, builder, mock_scope, mock_api):
        """Pipeline resolver on scope respects custom ID suffix."""
        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_resolver = MagicMock()
            mock_appsync.Resolver.return_value = mock_resolver
            mock_appsync.FunctionRuntime.JS_1_0_0 = "JS_1_0_0"
            mock_appsync.Code.from_asset.return_value = "js_code"

            builder.create_pipeline_resolver_on_scope(
                field_name="deleteCatalog",
                type_name="Mutation",
                functions=[],
                code_file=Path("/path/to/pipeline.js"),
                id_suffix="DeleteCatalogPipelineResolver",
            )

        call_args = mock_appsync.Resolver.call_args
        assert call_args[0][1] == "DeleteCatalogPipelineResolver"


class TestCreateVtlPipelineResolver:
    """Tests for VTL pipeline resolver creation."""

    def test_create_vtl_pipeline_resolver_uses_resolver_construct(self, builder, mock_scope, mock_api):
        """VTL pipeline resolver uses appsync.Resolver construct."""
        functions = [MagicMock()]

        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_resolver = MagicMock()
            mock_appsync.Resolver.return_value = mock_resolver
            mock_appsync.MappingTemplate.from_file.side_effect = lambda x: f"template:{x}"

            result = builder.create_vtl_pipeline_resolver(
                field_name="getProfile",
                type_name="Query",
                functions=functions,
                request_template=Path("/path/to/request.vtl"),
                response_template=Path("/path/to/response.vtl"),
            )

        mock_appsync.Resolver.assert_called_once()
        call_kwargs = mock_appsync.Resolver.call_args[1]
        assert call_kwargs["api"] is mock_api
        assert call_kwargs["type_name"] == "Query"
        assert call_kwargs["field_name"] == "getProfile"
        assert call_kwargs["pipeline_config"] == functions
        assert result is mock_resolver


class TestCreateLambdaResolver:
    """Tests for Lambda resolver creation."""

    def test_create_lambda_resolver_calls_lambda_datasource_create_resolver(self, builder):
        """Lambda resolver uses lambda_datasource.create_resolver()."""
        builder.create_lambda_resolver(
            field_name="createCampaign",
            type_name="Mutation",
            lambda_datasource_name="campaign_operations",
        )

        builder.lambda_datasources["campaign_operations"].create_resolver.assert_called_once()
        call_args = builder.lambda_datasources["campaign_operations"].create_resolver.call_args
        assert call_args[0][0] == "createCampaignResolver"
        assert call_args[1]["type_name"] == "Mutation"
        assert call_args[1]["field_name"] == "createCampaign"

    def test_create_lambda_resolver_with_custom_id(self, builder):
        """Lambda resolver respects custom ID suffix."""
        builder.create_lambda_resolver(
            field_name="createCampaign",
            type_name="Mutation",
            lambda_datasource_name="campaign_operations",
            id_suffix="CampaignCreatorResolver",
        )

        call_args = builder.lambda_datasources["campaign_operations"].create_resolver.call_args
        assert call_args[0][0] == "CampaignCreatorResolver"


class TestCreateBatchResolvers:
    """Tests for batch resolver creation."""

    def test_create_batch_resolvers_creates_vtl_resolver(self, builder):
        """Batch creation handles VTL resolver configs."""
        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_appsync.MappingTemplate.from_file.side_effect = lambda x: f"template:{x}"

            configs = [
                {
                    "type": "vtl",
                    "field_name": "getMyAccount",
                    "type_name": "Query",
                    "datasource_name": "accounts",
                    "request_template": Path("/path/to/request.vtl"),
                    "response_template": Path("/path/to/response.vtl"),
                }
            ]

            result = builder.create_batch_resolvers(configs)

        assert len(result) == 1
        builder.datasources["accounts"].create_resolver.assert_called_once()

    def test_create_batch_resolvers_creates_js_resolver(self, builder):
        """Batch creation handles JS resolver configs."""
        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_appsync.FunctionRuntime.JS_1_0_0 = "JS_1_0_0"
            mock_appsync.Code.from_asset.return_value = "js_code"

            configs = [
                {
                    "type": "js",
                    "field_name": "listMyProfiles",
                    "type_name": "Query",
                    "datasource_name": "profiles",
                    "code_file": Path("/path/to/resolver.js"),
                }
            ]

            result = builder.create_batch_resolvers(configs)

        assert len(result) == 1
        builder.datasources["profiles"].create_resolver.assert_called_once()

    def test_create_batch_resolvers_creates_js_on_api_resolver(self, builder, mock_api):
        """Batch creation handles JS on API resolver configs."""
        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_appsync.FunctionRuntime.JS_1_0_0 = "JS_1_0_0"
            mock_appsync.Code.from_asset.return_value = "js_code"

            configs = [
                {
                    "type": "js_on_api",
                    "field_name": "listMyProfiles",
                    "type_name": "Query",
                    "datasource_name": "profiles",
                    "code_file": Path("/path/to/resolver.js"),
                }
            ]

            result = builder.create_batch_resolvers(configs)

        assert len(result) == 1
        mock_api.create_resolver.assert_called_once()

    def test_create_batch_resolvers_creates_pipeline_resolver(self, builder, mock_api):
        """Batch creation handles pipeline resolver configs."""
        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_appsync.FunctionRuntime.JS_1_0_0 = "JS_1_0_0"
            mock_appsync.Code.from_asset.return_value = "js_code"

            functions = [MagicMock()]
            configs = [
                {
                    "type": "pipeline",
                    "field_name": "createOrder",
                    "type_name": "Mutation",
                    "functions": functions,
                    "code_file": Path("/path/to/pipeline.js"),
                }
            ]

            result = builder.create_batch_resolvers(configs)

        assert len(result) == 1
        mock_api.create_resolver.assert_called_once()

    def test_create_batch_resolvers_creates_lambda_resolver(self, builder):
        """Batch creation handles Lambda resolver configs."""
        configs = [
            {
                "type": "lambda",
                "field_name": "createCampaign",
                "type_name": "Mutation",
                "lambda_datasource_name": "campaign_operations",
            }
        ]

        result = builder.create_batch_resolvers(configs)

        assert len(result) == 1
        builder.lambda_datasources["campaign_operations"].create_resolver.assert_called_once()

    def test_create_batch_resolvers_raises_on_unknown_type(self, builder):
        """Batch creation raises ValueError for unknown resolver types."""
        configs = [
            {
                "type": "unknown",
                "field_name": "test",
                "type_name": "Query",
            }
        ]

        with pytest.raises(ValueError, match="Unknown resolver type: unknown"):
            builder.create_batch_resolvers(configs)

    def test_create_batch_resolvers_creates_multiple(self, builder, mock_api):
        """Batch creation handles multiple resolver configs."""
        with patch("cdk.appsync.resolver_builder.appsync") as mock_appsync:
            mock_appsync.MappingTemplate.from_file.side_effect = lambda x: f"template:{x}"
            mock_appsync.FunctionRuntime.JS_1_0_0 = "JS_1_0_0"
            mock_appsync.Code.from_asset.return_value = "js_code"

            configs = [
                {
                    "type": "vtl",
                    "field_name": "getMyAccount",
                    "type_name": "Query",
                    "datasource_name": "accounts",
                    "request_template": Path("/path/to/request.vtl"),
                    "response_template": Path("/path/to/response.vtl"),
                },
                {
                    "type": "lambda",
                    "field_name": "createCampaign",
                    "type_name": "Mutation",
                    "lambda_datasource_name": "campaign_operations",
                },
            ]

            result = builder.create_batch_resolvers(configs)

        assert len(result) == 2
        builder.datasources["accounts"].create_resolver.assert_called_once()
        builder.lambda_datasources["campaign_operations"].create_resolver.assert_called_once()

    def test_create_batch_resolvers_with_custom_id_suffix(self, builder):
        """Batch creation respects custom ID suffix in config."""
        configs = [
            {
                "type": "lambda",
                "field_name": "createCampaign",
                "type_name": "Mutation",
                "lambda_datasource_name": "campaign_operations",
                "id_suffix": "CustomCampaignResolver",
            }
        ]

        builder.create_batch_resolvers(configs)

        call_args = builder.lambda_datasources["campaign_operations"].create_resolver.call_args
        assert call_args[0][0] == "CustomCampaignResolver"
