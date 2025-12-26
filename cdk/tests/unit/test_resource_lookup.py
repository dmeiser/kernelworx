"""Tests for the resource_lookup module."""

from unittest.mock import MagicMock, patch

import pytest

from cdk import resource_lookup


class TestGetClient:
    """Tests for get_client function."""

    def test_caches_clients(self):
        """Should return the same client for the same service."""
        # Clear the cache first
        resource_lookup._clients.clear()

        with patch("boto3.client") as mock_boto_client:
            mock_client = MagicMock()
            mock_boto_client.return_value = mock_client

            client1 = resource_lookup.get_client("dynamodb")
            client2 = resource_lookup.get_client("dynamodb")

            # Should only create one client
            assert mock_boto_client.call_count == 1
            assert client1 is client2

    def test_creates_different_clients_for_different_services(self):
        """Should create different clients for different services."""
        resource_lookup._clients.clear()

        with patch("boto3.client") as mock_boto_client:
            mock_client1 = MagicMock()
            mock_client2 = MagicMock()
            mock_boto_client.side_effect = [mock_client1, mock_client2]

            client1 = resource_lookup.get_client("dynamodb")
            client2 = resource_lookup.get_client("s3")

            assert mock_boto_client.call_count == 2
            assert client1 is not client2


class TestLookupUserPoolByName:
    """Tests for lookup_user_pool_by_name function."""

    def test_returns_pool_when_found(self):
        """Should return pool info when found."""
        resource_lookup.lookup_user_pool_by_name.cache_clear()
        resource_lookup._clients.clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"UserPools": [{"Id": "us-east-1_abc123", "Name": "test-pool"}]}]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_by_name("test")

        assert result == {"user_pool_id": "us-east-1_abc123", "user_pool_name": "test-pool"}

    def test_returns_none_when_not_found(self):
        """Should return None when pool not found."""
        resource_lookup.lookup_user_pool_by_name.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"UserPools": []}]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_by_name("nonexistent")

        assert result is None

    def test_returns_none_on_exception(self):
        """Should return None on exception."""
        resource_lookup.lookup_user_pool_by_name.cache_clear()

        mock_client = MagicMock()
        mock_client.get_paginator.side_effect = Exception("API Error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_by_name("test")

        assert result is None


class TestLookupUserPoolClient:
    """Tests for lookup_user_pool_client function."""

    def test_returns_client_when_found(self):
        """Should return client info when found."""
        resource_lookup.lookup_user_pool_client.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"UserPoolClients": [{"ClientId": "abc123", "ClientName": "test-client"}]}
        ]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_client("us-east-1_pool", "test")

        assert result == {"client_id": "abc123", "client_name": "test-client"}

    def test_returns_first_client_when_no_prefix(self):
        """Should return first client when no prefix specified."""
        resource_lookup.lookup_user_pool_client.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"UserPoolClients": [{"ClientId": "first", "ClientName": "first-client"}]}
        ]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_client("us-east-1_pool", "")

        assert result == {"client_id": "first", "client_name": "first-client"}


class TestLookupDynamodbTable:
    """Tests for lookup_dynamodb_table function."""

    def test_returns_table_when_found(self):
        """Should return table info when found."""
        resource_lookup.lookup_dynamodb_table.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_table.return_value = {
            "Table": {
                "TableName": "test-table",
                "TableArn": "arn:aws:dynamodb:us-east-1:123:table/test-table",
            }
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_dynamodb_table("test-table")

        assert result == {
            "table_name": "test-table",
            "table_arn": "arn:aws:dynamodb:us-east-1:123:table/test-table",
        }

    def test_returns_none_when_not_found(self):
        """Should return None when table not found."""
        resource_lookup.lookup_dynamodb_table.cache_clear()

        mock_client = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = Exception
        mock_client.describe_table.side_effect = mock_client.exceptions.ResourceNotFoundException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_dynamodb_table("nonexistent")

        assert result is None


class TestLookupS3Bucket:
    """Tests for lookup_s3_bucket function."""

    def test_returns_true_when_found(self):
        """Should return True when bucket exists."""
        resource_lookup.lookup_s3_bucket.cache_clear()

        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_s3_bucket("test-bucket")

        assert result is True

    def test_returns_false_when_not_found(self):
        """Should return False when bucket doesn't exist."""
        resource_lookup.lookup_s3_bucket.cache_clear()

        mock_client = MagicMock()
        mock_client.head_bucket.side_effect = Exception("Not Found")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_s3_bucket("nonexistent")

        assert result is False


class TestLookupS3BucketPolicy:
    """Tests for lookup_s3_bucket_policy function."""

    def test_returns_true_when_policy_exists(self):
        """Should return True when policy exists."""
        resource_lookup.lookup_s3_bucket_policy.cache_clear()

        mock_client = MagicMock()
        mock_client.get_bucket_policy.return_value = {"Policy": "{}"}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_s3_bucket_policy("test-bucket")

        assert result is True

    def test_returns_false_when_no_policy(self):
        """Should return False when no policy exists."""
        resource_lookup.lookup_s3_bucket_policy.cache_clear()

        mock_client = MagicMock()
        mock_client.exceptions.NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_client.get_bucket_policy.side_effect = Exception("NoSuchBucketPolicy")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_s3_bucket_policy("test-bucket")

        assert result is False


class TestLookupCloudfrontDistribution:
    """Tests for lookup_cloudfront_distribution function."""

    def test_returns_distribution_when_found(self):
        """Should return distribution info when found."""
        resource_lookup.lookup_cloudfront_distribution.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E123",
                            "DomainName": "d123.cloudfront.net",
                            "Aliases": {"Items": ["test.example.com"]},
                        }
                    ]
                }
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_cloudfront_distribution("test.example.com")

        assert result == {"distribution_id": "E123", "domain_name": "d123.cloudfront.net"}

    def test_returns_none_when_not_found(self):
        """Should return None when distribution not found."""
        resource_lookup.lookup_cloudfront_distribution.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"DistributionList": {"Items": []}}]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_cloudfront_distribution("nonexistent.com")

        assert result is None


class TestLookupOai:
    """Tests for lookup_oai function."""

    def test_returns_oai_when_found(self):
        """Should return OAI info when found."""
        resource_lookup.lookup_oai.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "CloudFrontOriginAccessIdentityList": {
                    "Items": [{"Id": "OAI123", "Comment": "test-oai", "S3CanonicalUserId": "canonical123"}]
                }
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_oai("test")

        assert result == {"oai_id": "OAI123", "s3_canonical_user_id": "canonical123"}


class TestLookupCertificate:
    """Tests for lookup_certificate function."""

    def test_returns_certificate_arn_when_found(self):
        """Should return certificate ARN when found."""
        resource_lookup.lookup_certificate.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "CertificateSummaryList": [
                    {
                        "DomainName": "test.example.com",
                        "CertificateArn": "arn:aws:acm:us-east-1:123:cert/abc",
                    }
                ]
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        with patch("boto3.client", return_value=mock_client):
            result = resource_lookup.lookup_certificate("test.example.com")

        assert result == "arn:aws:acm:us-east-1:123:cert/abc"

    def test_returns_none_when_not_found(self):
        """Should return None when certificate not found."""
        resource_lookup.lookup_certificate.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"CertificateSummaryList": []}]
        mock_client.get_paginator.return_value = mock_paginator

        with patch("boto3.client", return_value=mock_client):
            result = resource_lookup.lookup_certificate("nonexistent.com")

        assert result is None


class TestLookupAppsyncApi:
    """Tests for lookup_appsync_api function."""

    def test_returns_api_when_found(self):
        """Should return API info when found."""
        resource_lookup.lookup_appsync_api.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "graphqlApis": [
                    {
                        "apiId": "api123",
                        "name": "test-api",
                        "arn": "arn:aws:appsync:us-east-1:123:apis/api123",
                    }
                ]
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_api("test-api")

        assert result == {
            "api_id": "api123",
            "api_name": "test-api",
            "arn": "arn:aws:appsync:us-east-1:123:apis/api123",
        }


class TestLookupAppsyncDatasource:
    """Tests for lookup_appsync_datasource function."""

    def test_returns_datasource_when_found(self):
        """Should return datasource info when found."""
        resource_lookup.lookup_appsync_datasource.cache_clear()

        mock_client = MagicMock()
        mock_client.get_data_source.return_value = {
            "dataSource": {
                "name": "test-ds",
                "type": "AMAZON_DYNAMODB",
                "dataSourceArn": "arn:aws:appsync:us-east-1:123:apis/api123/datasources/test-ds",
            }
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_datasource("api123", "test-ds")

        assert result == {
            "name": "test-ds",
            "type": "AMAZON_DYNAMODB",
            "datasource_arn": "arn:aws:appsync:us-east-1:123:apis/api123/datasources/test-ds",
        }

    def test_returns_none_when_not_found(self):
        """Should return None when datasource not found."""
        resource_lookup.lookup_appsync_datasource.cache_clear()

        mock_client = MagicMock()
        mock_client.exceptions.NotFoundException = type("NotFoundException", (Exception,), {})
        mock_client.get_data_source.side_effect = mock_client.exceptions.NotFoundException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_datasource("api123", "nonexistent")

        assert result is None


class TestLookupIamRole:
    """Tests for lookup_iam_role function."""

    def test_returns_role_arn_when_found(self):
        """Should return role ARN when found."""
        resource_lookup.lookup_iam_role.cache_clear()

        mock_client = MagicMock()
        mock_client.get_role.return_value = {"Role": {"Arn": "arn:aws:iam::123:role/test-role"}}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_iam_role("test-role")

        assert result == "arn:aws:iam::123:role/test-role"

    def test_returns_none_when_not_found(self):
        """Should return None when role not found."""
        resource_lookup.lookup_iam_role.cache_clear()

        mock_client = MagicMock()
        mock_client.exceptions.NoSuchEntityException = type("NoSuchEntityException", (Exception,), {})
        mock_client.get_role.side_effect = mock_client.exceptions.NoSuchEntityException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_iam_role("nonexistent")

        assert result is None


class TestLookupLambdaFunction:
    """Tests for lookup_lambda_function function."""

    def test_returns_function_when_found(self):
        """Should return function info when found."""
        resource_lookup.lookup_lambda_function.cache_clear()

        mock_client = MagicMock()
        mock_client.get_function.return_value = {
            "Configuration": {
                "FunctionName": "test-fn",
                "FunctionArn": "arn:aws:lambda:us-east-1:123:function:test-fn",
            }
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_lambda_function("test-fn")

        assert result == {
            "function_name": "test-fn",
            "function_arn": "arn:aws:lambda:us-east-1:123:function:test-fn",
        }

    def test_returns_none_when_not_found(self):
        """Should return None when function not found."""
        resource_lookup.lookup_lambda_function.cache_clear()

        mock_client = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.get_function.side_effect = mock_client.exceptions.ResourceNotFoundException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_lambda_function("nonexistent")

        assert result is None


class TestLookupLambdaLayer:
    """Tests for lookup_lambda_layer function."""

    def test_returns_layer_when_found(self):
        """Should return layer info when found."""
        resource_lookup.lookup_lambda_layer.cache_clear()

        mock_client = MagicMock()
        mock_client.list_layer_versions.return_value = {
            "LayerVersions": [{"LayerVersionArn": "arn:aws:lambda:us-east-1:123:layer:test:1", "Version": 1}]
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_lambda_layer("test")

        assert result == {
            "layer_name": "test",
            "layer_arn": "arn:aws:lambda:us-east-1:123:layer:test:1",
            "version": 1,
        }

    def test_returns_none_when_not_found(self):
        """Should return None when layer not found."""
        resource_lookup.lookup_lambda_layer.cache_clear()

        mock_client = MagicMock()
        mock_client.list_layer_versions.return_value = {"LayerVersions": []}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_lambda_layer("nonexistent")

        assert result is None


class TestLookupUserPoolDomain:
    """Tests for lookup_user_pool_domain function."""

    def test_returns_custom_domain_when_found(self):
        """Should return custom domain when found."""
        resource_lookup.lookup_user_pool_domain.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_user_pool.return_value = {"UserPool": {"CustomDomain": "login.example.com"}}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_domain("us-east-1_abc123")

        assert result == "login.example.com"

    def test_returns_regular_domain_when_no_custom(self):
        """Should return regular domain when no custom domain."""
        resource_lookup.lookup_user_pool_domain.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_user_pool.return_value = {"UserPool": {"Domain": "my-domain"}}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_domain("us-east-1_abc123")

        assert result == "my-domain"


class TestLookupCognitoDomainCloudfront:
    """Tests for lookup_cognito_domain_cloudfront function."""

    def test_returns_cloudfront_distribution(self):
        """Should return CloudFront distribution domain."""
        resource_lookup.lookup_cognito_domain_cloudfront.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_user_pool_domain.return_value = {
            "DomainDescription": {"CloudFrontDistribution": "d123.cloudfront.net"}
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_cognito_domain_cloudfront("login.example.com")

        assert result == "d123.cloudfront.net"


class TestLookupUserPoolById:
    """Tests for lookup_user_pool_by_id function."""

    def test_returns_pool_when_found(self):
        """Should return pool info when found."""
        resource_lookup.lookup_user_pool_by_id.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_user_pool.return_value = {
            "UserPool": {
                "Id": "us-east-1_abc123",
                "Name": "test-pool",
                "CustomDomain": "login.example.com",
            }
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_by_id("us-east-1_abc123")

        assert result == {
            "user_pool_id": "us-east-1_abc123",
            "user_pool_name": "test-pool",
            "custom_domain": "login.example.com",
        }


class TestLookupAppsyncDomain:
    """Tests for lookup_appsync_domain function."""

    def test_returns_domain_when_found(self):
        """Should return domain info when found."""
        resource_lookup.lookup_appsync_domain.cache_clear()

        mock_client = MagicMock()
        mock_client.get_domain_name.return_value = {
            "domainNameConfig": {
                "domainName": "api.example.com",
                "appsyncDomainName": "abc123.appsync-api.us-east-1.amazonaws.com",
                "certificateArn": "arn:aws:acm:us-east-1:123:cert/abc",
                "hostedZoneId": "Z123",
            }
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_domain("api.example.com")

        assert result == {
            "domain_name": "api.example.com",
            "appsync_domain_name": "abc123.appsync-api.us-east-1.amazonaws.com",
            "certificate_arn": "arn:aws:acm:us-east-1:123:cert/abc",
            "hosted_zone_id": "Z123",
        }


class TestLookupRoute53Record:
    """Tests for lookup_route53_record function."""

    def test_returns_record_when_found(self):
        """Should return record info when found."""
        resource_lookup.lookup_route53_record.cache_clear()

        mock_client = MagicMock()
        mock_client.list_resource_record_sets.return_value = {
            "ResourceRecordSets": [
                {
                    "Name": "test.example.com.",
                    "Type": "A",
                    "AliasTarget": {"DNSName": "d123.cloudfront.net"},
                    "TTL": 300,
                }
            ]
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_route53_record("Z123", "test.example.com.", "A")

        assert result is not None
        assert result["name"] == "test.example.com."
        assert result["type"] == "A"

    def test_returns_none_when_not_found(self):
        """Should return None when record not found."""
        resource_lookup.lookup_route53_record.cache_clear()

        mock_client = MagicMock()
        mock_client.list_resource_record_sets.return_value = {"ResourceRecordSets": []}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_route53_record("Z123", "nonexistent.com", "A")

        assert result is None


class TestLookupIdentityProvider:
    """Tests for lookup_identity_provider function."""

    def test_returns_provider_when_found(self):
        """Should return provider info when found."""
        resource_lookup.lookup_identity_provider.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_identity_provider.return_value = {
            "IdentityProvider": {
                "ProviderName": "Google",
                "ProviderType": "Google",
                "CreationDate": "2024-01-01",
                "LastModifiedDate": "2024-01-01",
            }
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_identity_provider("us-east-1_abc123", "Google")

        assert result == {
            "provider_name": "Google",
            "provider_type": "Google",
            "creation_date": "2024-01-01",
            "last_modified_date": "2024-01-01",
        }

    def test_returns_none_on_resource_not_found(self):
        """Should return None when provider not found."""
        resource_lookup.lookup_identity_provider.cache_clear()

        mock_client = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_client.describe_identity_provider.side_effect = ResourceNotFoundException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_identity_provider("us-east-1_abc123", "Google")

        assert result is None

    def test_returns_none_on_general_exception(self):
        """Should return None on general exception."""
        resource_lookup.lookup_identity_provider.cache_clear()

        mock_client = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_client.describe_identity_provider.side_effect = Exception("API Error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_identity_provider("us-east-1_abc123", "Google")

        assert result is None


class TestLookupDynamodbTableEdgeCases:
    """Edge case tests for lookup_dynamodb_table function."""

    def test_returns_none_on_resource_not_found(self):
        """Should return None when table not found."""
        resource_lookup.lookup_dynamodb_table.cache_clear()

        mock_client = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_client.describe_table.side_effect = ResourceNotFoundException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_dynamodb_table("nonexistent-table")

        assert result is None

    def test_returns_none_on_general_exception(self):
        """Should return None on general exception."""
        resource_lookup.lookup_dynamodb_table.cache_clear()

        mock_client = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_client.describe_table.side_effect = Exception("Access denied")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_dynamodb_table("test-table")

        assert result is None


class TestLookupUserPoolClientEdgeCases:
    """Edge case tests for lookup_user_pool_client function."""

    def test_returns_client_with_matching_prefix(self):
        """Should return client matching prefix."""
        resource_lookup.lookup_user_pool_client.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "UserPoolClients": [
                    {"ClientId": "abc", "ClientName": "other-client"},
                    {"ClientId": "def", "ClientName": "test-client"},
                ]
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_client("us-east-1_pool", "test")

        assert result == {"client_id": "def", "client_name": "test-client"}


class TestLookupS3BucketEdgeCases:
    """Edge case tests for lookup_s3_bucket function."""

    def test_returns_false_on_general_exception(self):
        """Should return False on general exception."""
        resource_lookup.lookup_s3_bucket.cache_clear()

        mock_client = MagicMock()
        NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NoSuchBucket = NoSuchBucket
        mock_client.head_bucket.side_effect = Exception("Access denied")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_s3_bucket("test-bucket")

        assert result is False


class TestLookupCloudfrontDistributionEdgeCases:
    """Edge case tests for lookup_cloudfront_distribution function."""

    def test_returns_none_when_no_distributions(self):
        """Should return None when no distributions exist."""
        resource_lookup.lookup_cloudfront_distribution.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"DistributionList": {}}]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_cloudfront_distribution("test.example.com")

        assert result is None

    def test_returns_none_on_exception(self):
        """Should return None on exception."""
        resource_lookup.lookup_cloudfront_distribution.cache_clear()

        mock_client = MagicMock()
        mock_client.get_paginator.side_effect = Exception("API Error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_cloudfront_distribution("test.example.com")

        assert result is None


class TestLookupCertificateEdgeCases:
    """Edge case tests for lookup_certificate function."""

    def test_returns_none_when_not_found(self):
        """Should return None when certificate not found."""
        resource_lookup.lookup_certificate.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"CertificateSummaryList": []}]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_certificate("nonexistent.example.com")

        assert result is None


class TestLookupAppsyncApiEdgeCases:
    """Edge case tests for lookup_appsync_api function."""

    def test_returns_none_on_not_found_exception(self):
        """Should return None when API not found."""
        resource_lookup.lookup_appsync_api.cache_clear()

        mock_client = MagicMock()
        NotFoundException = type("NotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NotFoundException = NotFoundException
        mock_client.get_graphql_api.side_effect = NotFoundException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_api("api123")

        assert result is None

    def test_returns_none_on_general_exception(self):
        """Should return None on general exception."""
        resource_lookup.lookup_appsync_api.cache_clear()

        mock_client = MagicMock()
        NotFoundException = type("NotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NotFoundException = NotFoundException
        mock_client.get_graphql_api.side_effect = Exception("API Error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_api("api123")

        assert result is None


class TestLookupAppsyncDomainNameEdgeCases:
    """Edge case tests for lookup_appsync_domain_name function."""

    def test_returns_domain_when_found(self):
        """Should return domain info when found."""
        resource_lookup.lookup_appsync_domain_name.cache_clear()

        mock_client = MagicMock()
        mock_client.list_domain_names.return_value = {
            "domainNameConfigs": [
                {
                    "domainName": "api.example.com",
                    "domainNameArn": "arn:aws:appsync:us-east-1:123:domainname/api.example.com",
                    "appsyncDomainName": "abc123.appsync-api.us-east-1.amazonaws.com",
                    "certificateArn": "arn:aws:acm:us-east-1:123:cert/abc",
                    "hostedZoneId": "Z123",
                }
            ]
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_domain_name("api.example.com")

        assert result is not None
        assert result["domain_name"] == "api.example.com"
        assert result["appsync_domain_name"] == "abc123.appsync-api.us-east-1.amazonaws.com"

    def test_returns_none_when_not_found(self):
        """Should return None when domain not found."""
        resource_lookup.lookup_appsync_domain_name.cache_clear()

        mock_client = MagicMock()
        mock_client.list_domain_names.return_value = {"domainNameConfigs": []}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_domain_name("nonexistent.example.com")

        assert result is None

    def test_returns_none_on_exception(self):
        """Should return None on exception."""
        resource_lookup.lookup_appsync_domain_name.cache_clear()

        mock_client = MagicMock()
        mock_client.list_domain_names.side_effect = Exception("API Error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_domain_name("test.example.com")

        assert result is None


class TestLookupIamRoleEdgeCases:
    """Edge case tests for lookup_iam_role function."""

    def test_returns_none_on_no_such_entity(self):
        """Should return None when role not found."""
        resource_lookup.lookup_iam_role.cache_clear()

        mock_client = MagicMock()
        NoSuchEntityException = type("NoSuchEntityException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NoSuchEntityException = NoSuchEntityException
        mock_client.get_role.side_effect = NoSuchEntityException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_iam_role("nonexistent-role")

        assert result is None

    def test_returns_none_on_general_exception(self):
        """Should return None on general exception."""
        resource_lookup.lookup_iam_role.cache_clear()

        mock_client = MagicMock()
        NoSuchEntityException = type("NoSuchEntityException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NoSuchEntityException = NoSuchEntityException
        mock_client.get_role.side_effect = Exception("Access denied")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_iam_role("test-role")

        assert result is None


class TestLookupLambdaFunctionEdgeCases:
    """Edge case tests for lookup_lambda_function function."""

    def test_returns_none_on_resource_not_found(self):
        """Should return None when function not found."""
        resource_lookup.lookup_lambda_function.cache_clear()

        mock_client = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_client.get_function.side_effect = ResourceNotFoundException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_lambda_function("nonexistent-function")

        assert result is None

    def test_returns_none_on_general_exception(self):
        """Should return None on general exception."""
        resource_lookup.lookup_lambda_function.cache_clear()

        mock_client = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_client.get_function.side_effect = Exception("Access denied")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_lambda_function("test-function")

        assert result is None


class TestLookupRoute53RecordEdgeCases:
    """Edge case tests for lookup_route53_record function."""

    def test_returns_none_on_exception(self):
        """Should return None on exception."""
        resource_lookup.lookup_route53_record.cache_clear()

        mock_client = MagicMock()
        mock_client.get_paginator.side_effect = Exception("API Error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_route53_record("Z123", "test.example.com", "A")

        assert result is None


class TestLookupS3BucketPolicyEdgeCases:
    """Edge case tests for lookup_s3_bucket_policy function."""

    def test_returns_true_when_policy_exists(self):
        """Should return True when bucket has policy."""
        resource_lookup.lookup_s3_bucket_policy.cache_clear()

        mock_client = MagicMock()
        mock_client.get_bucket_policy.return_value = {"Policy": "{}"}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_s3_bucket_policy("test-bucket")

        assert result is True

    def test_returns_false_on_no_such_bucket(self):
        """Should return False when bucket doesn't exist."""
        resource_lookup.lookup_s3_bucket_policy.cache_clear()

        mock_client = MagicMock()
        NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NoSuchBucket = NoSuchBucket
        mock_client.get_bucket_policy.side_effect = NoSuchBucket()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_s3_bucket_policy("nonexistent")

        assert result is False

    def test_returns_false_on_no_bucket_policy(self):
        """Should return False when bucket has no policy."""
        resource_lookup.lookup_s3_bucket_policy.cache_clear()

        mock_client = MagicMock()
        NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NoSuchBucket = NoSuchBucket
        mock_client.get_bucket_policy.side_effect = Exception("NoSuchBucketPolicy")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_s3_bucket_policy("test-bucket")

        assert result is False

    def test_reraises_unexpected_exception(self):
        """Should re-raise exceptions that aren't NoSuchBucket or NoSuchBucketPolicy."""
        resource_lookup.lookup_s3_bucket_policy.cache_clear()

        mock_client = MagicMock()
        NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NoSuchBucket = NoSuchBucket
        mock_client.get_bucket_policy.side_effect = Exception("AccessDenied")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            with pytest.raises(Exception, match="AccessDenied"):
                resource_lookup.lookup_s3_bucket_policy("test-bucket")


class TestLookupOaiEdgeCases:
    """Edge case tests for lookup_oai function."""

    def test_returns_oai_when_found(self):
        """Should return OAI when found with matching prefix."""
        resource_lookup.lookup_oai.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "CloudFrontOriginAccessIdentityList": {
                    "Items": [{"Id": "OAI123", "Comment": "test-oai", "S3CanonicalUserId": "canonical123"}]
                }
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_oai("test")

        assert result == {"oai_id": "OAI123", "s3_canonical_user_id": "canonical123"}

    def test_returns_none_when_not_found(self):
        """Should return None when no matching OAI found."""
        resource_lookup.lookup_oai.cache_clear()

        mock_client = MagicMock()
        mock_client.list_cloud_front_origin_access_identities.return_value = {
            "CloudFrontOriginAccessIdentityList": {"Items": []}
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_oai("nonexistent")

        assert result is None

    def test_returns_none_on_exception(self):
        """Should return None on exception."""
        resource_lookup.lookup_oai.cache_clear()

        mock_client = MagicMock()
        mock_client.list_cloud_front_origin_access_identities.side_effect = Exception("Error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_oai("test")

        assert result is None


class TestLookupCertificateMoreEdgeCases:
    """More edge case tests for lookup_certificate function."""

    @patch("boto3.client")
    def test_returns_arn_when_found(self, mock_boto_client):
        """Should return certificate ARN when found."""
        resource_lookup.lookup_certificate.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "CertificateSummaryList": [
                    {
                        "DomainName": "test.example.com",
                        "CertificateArn": "arn:aws:acm:us-east-1:123:cert/abc",
                    }
                ]
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator
        mock_boto_client.return_value = mock_client

        result = resource_lookup.lookup_certificate("test.example.com")

        assert result == "arn:aws:acm:us-east-1:123:cert/abc"

    @patch("boto3.client")
    def test_returns_none_on_exception(self, mock_boto_client):
        """Should return None on exception."""
        resource_lookup.lookup_certificate.cache_clear()

        mock_client = MagicMock()
        mock_client.get_paginator.side_effect = Exception("Error")
        mock_boto_client.return_value = mock_client

        result = resource_lookup.lookup_certificate("test.example.com")

        assert result is None


class TestLookupAppsyncDatasourceEdgeCases:
    """Edge case tests for lookup_appsync_datasource function."""

    def test_returns_datasource_when_found(self):
        """Should return datasource when found."""
        resource_lookup.lookup_appsync_datasource.cache_clear()

        mock_client = MagicMock()
        mock_client.get_data_source.return_value = {
            "dataSource": {
                "dataSourceArn": "arn:aws:appsync:us-east-1:123:apis/api/datasources/ds",
                "name": "test-ds",
                "type": "AMAZON_DYNAMODB",
            }
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_datasource("api123", "test-ds")

        assert result["datasource_arn"] == "arn:aws:appsync:us-east-1:123:apis/api/datasources/ds"
        assert result["name"] == "test-ds"

    def test_returns_none_on_not_found(self):
        """Should return None when datasource not found."""
        resource_lookup.lookup_appsync_datasource.cache_clear()

        mock_client = MagicMock()
        NotFoundException = type("NotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NotFoundException = NotFoundException
        mock_client.get_data_source.side_effect = NotFoundException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_datasource("api123", "nonexistent")

        assert result is None

    def test_returns_none_on_general_exception(self):
        """Should return None on general exception."""
        resource_lookup.lookup_appsync_datasource.cache_clear()

        mock_client = MagicMock()
        NotFoundException = type("NotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NotFoundException = NotFoundException
        mock_client.get_data_source.side_effect = Exception("Error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_datasource("api123", "test")

        assert result is None


class TestLookupLambdaLayerEdgeCases:
    """Edge case tests for lookup_lambda_layer function."""

    def test_returns_layer_when_found(self):
        """Should return layer when found."""
        resource_lookup.lookup_lambda_layer.cache_clear()

        mock_client = MagicMock()
        mock_client.list_layer_versions.return_value = {
            "LayerVersions": [
                {
                    "LayerVersionArn": "arn:aws:lambda:us-east-1:123:layer:test:1",
                    "Version": 1,
                    "Description": "Test layer",
                }
            ]
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_lambda_layer("test")

        assert result["version"] == 1
        assert result["layer_arn"] == "arn:aws:lambda:us-east-1:123:layer:test:1"
        assert result["layer_name"] == "test"

    def test_returns_none_when_not_found(self):
        """Should return None when no layer versions exist."""
        resource_lookup.lookup_lambda_layer.cache_clear()

        mock_client = MagicMock()
        mock_client.list_layer_versions.return_value = {"LayerVersions": []}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_lambda_layer("nonexistent")

        assert result is None

    def test_returns_none_on_exception(self):
        """Should return None on exception."""
        resource_lookup.lookup_lambda_layer.cache_clear()

        mock_client = MagicMock()
        mock_client.list_layer_versions.side_effect = Exception("Error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_lambda_layer("test")

        assert result is None


class TestLookupUserPoolDomainEdgeCases:
    """Edge case tests for lookup_user_pool_domain function."""

    def test_returns_domain_when_found(self):
        """Should return domain when found."""
        resource_lookup.lookup_user_pool_domain.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_user_pool.return_value = {"UserPool": {"Domain": "test-domain"}}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_domain("us-east-1_abc123")

        assert result == "test-domain"

    def test_returns_none_when_no_domain(self):
        """Should return None when user pool has no domain."""
        resource_lookup.lookup_user_pool_domain.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_user_pool.return_value = {"UserPool": {}}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_domain("us-east-1_abc123")

        assert result is None

    def test_returns_none_on_exception(self):
        """Should return None on exception."""
        resource_lookup.lookup_user_pool_domain.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_user_pool.side_effect = Exception("Error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_domain("us-east-1_abc123")

        assert result is None


class TestLookupCognitoDomainCloudfrontEdgeCases:
    """Edge case tests for lookup_cognito_domain_cloudfront function."""

    def test_returns_cloudfront_domain_when_found(self):
        """Should return CloudFront domain when found."""
        resource_lookup.lookup_cognito_domain_cloudfront.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_user_pool_domain.return_value = {
            "DomainDescription": {"CloudFrontDistribution": "d123.cloudfront.net"}
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_cognito_domain_cloudfront("test-domain")

        assert result == "d123.cloudfront.net"

    def test_returns_none_when_no_cloudfront(self):
        """Should return None when domain has no CloudFront distribution."""
        resource_lookup.lookup_cognito_domain_cloudfront.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_user_pool_domain.return_value = {"DomainDescription": {}}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_cognito_domain_cloudfront("test-domain")

        assert result is None

    def test_returns_none_on_exception(self):
        """Should return None on exception."""
        resource_lookup.lookup_cognito_domain_cloudfront.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_user_pool_domain.side_effect = Exception("Error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_cognito_domain_cloudfront("test-domain")

        assert result is None


class TestLookupUserPoolByIdEdgeCases:
    """Edge case tests for lookup_user_pool_by_id function."""

    def test_returns_pool_when_found(self):
        """Should return user pool when found."""
        resource_lookup.lookup_user_pool_by_id.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_user_pool.return_value = {
            "UserPool": {
                "Id": "us-east-1_abc123",
                "Name": "test-pool",
                "Domain": "test-domain",
                "CustomDomain": "auth.example.com",
            }
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_by_id("us-east-1_abc123")

        assert result["user_pool_id"] == "us-east-1_abc123"
        assert result["user_pool_name"] == "test-pool"

    def test_returns_none_on_resource_not_found(self):
        """Should return None on ResourceNotFoundException."""
        resource_lookup.lookup_user_pool_by_id.cache_clear()

        mock_client = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_client.describe_user_pool.side_effect = ResourceNotFoundException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_by_id("us-east-1_nonexistent")

        assert result is None

    def test_returns_none_on_generic_exception(self):
        """Should return None on generic exception (not ResourceNotFoundException)."""
        resource_lookup.lookup_user_pool_by_id.cache_clear()

        mock_client = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_client.describe_user_pool.side_effect = Exception("API error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_by_id("us-east-1_abc123")

        assert result is None


class TestLookupAppsyncDomainEdgeCases:
    """Edge case tests for lookup_appsync_domain function."""

    def test_returns_domain_when_found(self):
        """Should return domain when found."""
        resource_lookup.lookup_appsync_domain.cache_clear()

        mock_client = MagicMock()
        mock_client.get_domain_name.return_value = {
            "domainNameConfig": {
                "domainName": "api.example.com",
                "appsyncDomainName": "abc123.appsync-api.us-east-1.amazonaws.com",
                "hostedZoneId": "Z123",
                "certificateArn": "arn:aws:acm:us-east-1:123:cert/abc",
            }
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_domain("api.example.com")

        assert result["domain_name"] == "api.example.com"

    def test_returns_none_on_not_found(self):
        """Should return None on NotFoundException."""
        resource_lookup.lookup_appsync_domain.cache_clear()

        mock_client = MagicMock()
        NotFoundException = type("NotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NotFoundException = NotFoundException
        mock_client.get_domain_name.side_effect = NotFoundException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_domain("api.example.com")

        assert result is None

    def test_returns_none_on_generic_exception(self):
        """Should return None on generic Exception."""
        resource_lookup.lookup_appsync_domain.cache_clear()

        mock_client = MagicMock()
        NotFoundException = type("NotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NotFoundException = NotFoundException
        mock_client.get_domain_name.side_effect = Exception("API error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_domain("api.example.com")

        assert result is None


class TestLookupUserPoolClientEdgeCases:
    """Edge case tests for lookup_user_pool_client function."""

    def test_returns_none_on_exception(self):
        """Should return None on generic exception."""
        resource_lookup.lookup_user_pool_client.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = Exception("API error")
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_client("us-east-1_abc123")

        assert result is None

    def test_returns_first_client_when_no_prefix(self):
        """Should return the first client when no prefix is specified."""
        resource_lookup.lookup_user_pool_client.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"UserPoolClients": [{"ClientId": "client-123", "ClientName": "AppClient"}]}
        ]
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_user_pool_client("us-east-1_abc123", "")

        assert result is not None
        assert result["client_id"] == "client-123"


class TestLookupOaiEdgeCases:
    """Edge case tests for lookup_oai function."""

    def test_returns_none_on_exception(self):
        """Should return None on generic exception."""
        resource_lookup.lookup_oai.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = Exception("API error")
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_oai("SomePrefix")

        assert result is None


class TestLookupAppsyncApiEdgeCases:
    """Edge case tests for lookup_appsync_api function."""

    def test_returns_none_on_exception(self):
        """Should return None on generic exception."""
        resource_lookup.lookup_appsync_api.cache_clear()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = Exception("API error")
        mock_client.get_paginator.return_value = mock_paginator

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_api("TestApi")

        assert result is None


class TestLookupAppsyncDatasourceEdgeCases:
    """Edge case tests for lookup_appsync_datasource function."""

    def test_returns_none_on_exception(self):
        """Should return None on generic exception."""
        resource_lookup.lookup_appsync_datasource.cache_clear()

        mock_client = MagicMock()
        NotFoundException = type("NotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NotFoundException = NotFoundException
        mock_client.get_data_source.side_effect = Exception("API error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_appsync_datasource("api-123", "TestDataSource")

        assert result is None


class TestLookupRoute53RecordEdgeCases:
    """Edge case tests for lookup_route53_record function."""

    def test_returns_none_on_exception(self):
        """Should return None on generic exception."""
        resource_lookup.lookup_route53_record.cache_clear()

        mock_client = MagicMock()
        mock_client.list_resource_record_sets.side_effect = Exception("API error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_route53_record("Z123", "www.example.com", "A")

        assert result is None


class TestLookupIdentityProviderEdgeCases:
    """Edge case tests for lookup_identity_provider function."""

    def test_returns_none_on_generic_exception(self):
        """Should return None on generic exception."""
        mock_client = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_client.describe_identity_provider.side_effect = Exception("API error")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_identity_provider("us-east-1_abc123", "Google")

        assert result is None

    def test_returns_none_on_resource_not_found(self):
        """Should return None on ResourceNotFoundException."""
        mock_client = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_client.describe_identity_provider.side_effect = ResourceNotFoundException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.lookup_identity_provider("us-east-1_abc123", "Google")

        assert result is None


class TestTableExists:
    """Tests for table_exists helper function."""

    def test_returns_true_when_table_exists(self):
        """Should return True when table exists."""
        resource_lookup.lookup_dynamodb_table.cache_clear()

        mock_client = MagicMock()
        mock_client.describe_table.return_value = {
            "Table": {
                "TableName": "test-table",
                "TableArn": "arn:aws:dynamodb:us-east-1:123:table/test-table",
            }
        }

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.table_exists("test-table")

        assert result is True

    def test_returns_false_when_table_not_exists(self):
        """Should return False when table doesn't exist."""
        resource_lookup.lookup_dynamodb_table.cache_clear()

        mock_client = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_client.describe_table.side_effect = ResourceNotFoundException()

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.table_exists("nonexistent-table")

        assert result is False


class TestBucketExists:
    """Tests for bucket_exists helper function."""

    def test_returns_true_when_bucket_exists(self):
        """Should return True when bucket exists."""
        resource_lookup.lookup_s3_bucket.cache_clear()

        mock_client = MagicMock()
        # head_bucket returns nothing on success (no exception)
        mock_client.head_bucket.return_value = {}

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.bucket_exists("test-bucket")

        assert result is True

    def test_returns_false_when_bucket_not_exists(self):
        """Should return False when bucket doesn't exist."""
        resource_lookup.lookup_s3_bucket.cache_clear()

        mock_client = MagicMock()
        mock_client.head_bucket.side_effect = Exception("NoSuchBucket")

        with patch.object(resource_lookup, "get_client", return_value=mock_client):
            result = resource_lookup.bucket_exists("nonexistent-bucket")

        assert result is False
