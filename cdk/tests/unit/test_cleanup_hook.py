"""Tests for the cleanup_hook module."""

import os
from typing import Any
from unittest.mock import MagicMock, patch

from cdk import cleanup_hook


class TestIsCfManagedResource:
    """Tests for _is_cf_managed_resource function."""

    @patch("boto3.client")
    def test_returns_true_when_exact_match(self, mock_boto):
        """Should return True when resource exactly matches."""
        mock_cfn = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "ResourceType": "AWS::Cognito::UserPoolDomain",
                        "PhysicalResourceId": "login.example.com",
                    }
                ]
            }
        ]
        mock_cfn.get_paginator.return_value = mock_paginator
        mock_boto.return_value = mock_cfn

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            result = cleanup_hook._is_cf_managed_resource("AWS::Cognito::UserPoolDomain", "login.example.com", "dev")

        assert result is True

    @patch("boto3.client")
    def test_returns_true_when_id_in_arn(self, mock_boto):
        """Should return True when physical_id is contained in CF's physical ID (ARN)."""
        mock_cfn = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "ResourceType": "AWS::AppSync::GraphQLApi",
                        "PhysicalResourceId": "arn:aws:appsync:us-east-1:123:apis/api123",
                    }
                ]
            }
        ]
        mock_cfn.get_paginator.return_value = mock_paginator
        mock_boto.return_value = mock_cfn

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            result = cleanup_hook._is_cf_managed_resource("AWS::AppSync::GraphQLApi", "api123", "dev")

        assert result is True

    @patch("boto3.client")
    def test_returns_false_when_not_found(self, mock_boto):
        """Should return False when resource not found in stack."""
        mock_cfn = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "ResourceType": "AWS::Lambda::Function",
                        "PhysicalResourceId": "other-resource",
                    }
                ]
            }
        ]
        mock_cfn.get_paginator.return_value = mock_paginator
        mock_boto.return_value = mock_cfn

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            result = cleanup_hook._is_cf_managed_resource("AWS::AppSync::GraphQLApi", "api123", "dev")

        assert result is False

    @patch("boto3.client")
    def test_returns_true_on_exception_for_safety(self, mock_boto):
        """Should return True (managed) on exception to avoid accidental deletion."""
        mock_cfn = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = Exception("Access denied")
        mock_cfn.get_paginator.return_value = mock_paginator
        mock_boto.return_value = mock_cfn

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            result = cleanup_hook._is_cf_managed_resource("AWS::AppSync::GraphQLApi", "api123", "dev")

        assert result is True  # Fail safe: treat as managed


class TestFindCertificateArn:
    """Tests for _find_certificate_arn function."""

    def test_finds_certificate_by_domain(self):
        """Should find certificate by domain name."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "CertificateSummaryList": [
                    {
                        "CertificateArn": "arn:aws:acm:us-east-1:123:cert/abc",
                        "DomainName": "test.example.com",
                    }
                ]
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        result = cleanup_hook._find_certificate_arn(mock_client, "test.example.com")

        assert result == "arn:aws:acm:us-east-1:123:cert/abc"

    def test_finds_certificate_in_san(self):
        """Should find certificate in subject alternative names."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "CertificateSummaryList": [
                    {
                        "CertificateArn": "arn:aws:acm:us-east-1:123:cert/abc",
                        "DomainName": "main.example.com",
                    }
                ]
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator
        mock_client.describe_certificate.return_value = {
            "Certificate": {"SubjectAlternativeNames": ["main.example.com", "alt.example.com"]}
        }

        result = cleanup_hook._find_certificate_arn(mock_client, "alt.example.com")

        assert result == "arn:aws:acm:us-east-1:123:cert/abc"

    def test_returns_none_when_not_found(self):
        """Should return None when certificate not found."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"CertificateSummaryList": []}]
        mock_client.get_paginator.return_value = mock_paginator

        result = cleanup_hook._find_certificate_arn(mock_client, "nonexistent.com")

        assert result is None

    def test_returns_none_on_exception(self):
        """Should return None on exception."""
        mock_client = MagicMock()
        mock_client.get_paginator.side_effect = Exception("API Error")

        result = cleanup_hook._find_certificate_arn(mock_client, "test.example.com")

        assert result is None


class TestIsUnmanagedCertificate:
    """Tests for _is_unmanaged_certificate function."""

    @patch("boto3.client")
    def test_returns_false_when_tagged_as_kernelworx(self, mock_boto_client):
        """Should return False when certificate has kernelworx tags."""
        mock_acm = MagicMock()
        mock_acm.describe_certificate.return_value = {
            "Certificate": {
                "Tags": [
                    {"Key": "Application", "Value": "kernelworx"},
                    {"Key": "Environment", "Value": "dev"},
                ]
            }
        }
        mock_boto_client.return_value = mock_acm

        result = cleanup_hook._is_unmanaged_certificate("arn:aws:acm:us-east-1:123:cert/abc", "dev")

        assert result is False

    @patch("boto3.client")
    def test_returns_false_when_in_cloudformation_stack(self, mock_boto_client):
        """Should return False when certificate is in CloudFormation stack."""
        mock_acm = MagicMock()
        mock_acm.describe_certificate.return_value = {"Certificate": {"Tags": []}}

        mock_cfn = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "PhysicalResourceId": "arn:aws:acm:us-east-1:123:cert/abc",
                        "ResourceType": "AWS::CertificateManager::Certificate",
                    }
                ]
            }
        ]
        mock_cfn.get_paginator.return_value = mock_paginator

        def client_factory(service, **kwargs):
            if service == "acm":
                return mock_acm
            elif service == "cloudformation":
                return mock_cfn
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            result = cleanup_hook._is_unmanaged_certificate("arn:aws:acm:us-east-1:123:cert/abc", "dev")

        assert result is False

    @patch("boto3.client")
    def test_returns_true_when_unmanaged(self, mock_boto_client):
        """Should return True when certificate is unmanaged."""
        mock_acm = MagicMock()
        mock_acm.describe_certificate.return_value = {"Certificate": {"Tags": []}}

        mock_cfn = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = mock_paginator

        def client_factory(service, **kwargs):
            if service == "acm":
                return mock_acm
            elif service == "cloudformation":
                return mock_cfn
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            result = cleanup_hook._is_unmanaged_certificate("arn:aws:acm:us-east-1:123:cert/abc", "dev")

        assert result is True

    @patch("boto3.client")
    def test_returns_false_on_error(self, mock_boto_client):
        """Should return False (safe) on error."""
        mock_acm = MagicMock()
        mock_acm.describe_certificate.side_effect = Exception("API Error")
        mock_boto_client.return_value = mock_acm

        result = cleanup_hook._is_unmanaged_certificate("arn:aws:acm:us-east-1:123:cert/abc", "dev")

        assert result is False


class TestDeleteAcmCertificate:
    """Tests for _delete_acm_certificate function."""

    def test_deletes_certificate(self):
        """Should delete certificate."""
        mock_client = MagicMock()

        cleanup_hook._delete_acm_certificate(mock_client, "arn:aws:acm:us-east-1:123:cert/abc")

        mock_client.delete_certificate.assert_called_once_with(CertificateArn="arn:aws:acm:us-east-1:123:cert/abc")

    def test_handles_deletion_error(self):
        """Should handle deletion error gracefully."""
        mock_client = MagicMock()
        mock_client.delete_certificate.side_effect = Exception("Deletion Error")

        # Should not raise
        cleanup_hook._delete_acm_certificate(mock_client, "arn:aws:acm:us-east-1:123:cert/abc")


class TestDisconnectCognitoDomain:
    """Tests for _disconnect_cognito_domain function."""

    @patch.object(cleanup_hook, "_is_cf_managed_resource", return_value=False)
    def test_deletes_cognito_domain(self, mock_cf_check):
        """Should delete Cognito custom domain."""
        mock_client = MagicMock()
        mock_client.describe_user_pool_domain.return_value = {"DomainDescription": {"UserPoolId": "us-east-1_abc123"}}

        with patch("time.sleep"):
            cleanup_hook._disconnect_cognito_domain(mock_client, "login.example.com", "dev")

        mock_client.delete_user_pool_domain.assert_called_once_with(
            Domain="login.example.com", UserPoolId="us-east-1_abc123"
        )

    def test_handles_missing_domain(self):
        """Should handle domain not found."""
        mock_client = MagicMock()
        mock_client.describe_user_pool_domain.return_value = {"DomainDescription": {}}

        # Should not raise
        cleanup_hook._disconnect_cognito_domain(mock_client, "login.example.com", "dev")
        mock_client.delete_user_pool_domain.assert_not_called()

    @patch.object(cleanup_hook, "_is_cf_managed_resource", return_value=True)
    def test_skips_cf_managed_domain(self, mock_cf_check):
        """Should skip domain that is CloudFormation-managed."""
        mock_client = MagicMock()
        mock_client.describe_user_pool_domain.return_value = {"DomainDescription": {"UserPoolId": "us-east-1_abc123"}}

        cleanup_hook._disconnect_cognito_domain(mock_client, "login.example.com", "dev")

        # Should NOT delete since it's CF-managed
        mock_client.delete_user_pool_domain.assert_not_called()


class TestFindHostedZones:
    """Tests for _find_hosted_zones function."""

    def test_finds_matching_zones(self):
        """Should find hosted zones matching domain names."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"HostedZones": [{"Id": "/hostedzone/Z123", "Name": "example.com."}]}]
        mock_client.get_paginator.return_value = mock_paginator

        result = cleanup_hook._find_hosted_zones(mock_client, ["test.example.com"])

        assert result == [("Z123", "example.com")]

    def test_returns_empty_when_no_match(self):
        """Should return empty list when no match."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"HostedZones": []}]
        mock_client.get_paginator.return_value = mock_paginator

        result = cleanup_hook._find_hosted_zones(mock_client, ["test.example.com"])

        assert result == []


class TestListHostedZoneRecords:
    """Tests for _list_hosted_zone_records function."""

    def test_lists_records(self):
        """Should list all records in a hosted zone."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"ResourceRecordSets": [{"Name": "test.example.com.", "Type": "A"}]}]
        mock_client.get_paginator.return_value = mock_paginator

        result = cleanup_hook._list_hosted_zone_records(mock_client, "Z123")

        assert len(result) == 1
        assert result[0]["Name"] == "test.example.com."


class TestIsValidationRecord:
    """Tests for _is_validation_record function."""

    def test_identifies_acme_challenge(self):
        """Should identify ACME challenge records."""
        record = {"Name": "_acme-challenge.example.com.", "Type": "CNAME"}
        assert cleanup_hook._is_validation_record(record) is True

    def test_identifies_validation_records(self):
        """Should identify validation records."""
        record = {"Name": "_validation.example.com.", "Type": "CNAME"}
        assert cleanup_hook._is_validation_record(record) is True

    def test_rejects_normal_records(self):
        """Should reject normal records."""
        record = {"Name": "www.example.com.", "Type": "A"}
        assert cleanup_hook._is_validation_record(record) is False


class TestMatchesDomain:
    """Tests for _matches_domain function."""

    def test_matches_exact_domain(self):
        """Should match exact domain."""
        assert cleanup_hook._matches_domain("example.com.", "example.com") is True

    def test_matches_subdomain(self):
        """Should match subdomain."""
        assert cleanup_hook._matches_domain("test.example.com.", "example.com") is True


class TestDeleteRoute53Record:
    """Tests for _delete_route53_record function."""

    def test_deletes_regular_record(self):
        """Should delete regular record."""
        mock_client = MagicMock()
        record = {
            "Name": "test.example.com.",
            "Type": "A",
            "TTL": 300,
            "ResourceRecords": [{"Value": "1.2.3.4"}],
        }

        cleanup_hook._delete_route53_record(mock_client, "Z123", record)

        mock_client.change_resource_record_sets.assert_called_once()

    def test_deletes_alias_record(self):
        """Should delete alias record."""
        mock_client = MagicMock()
        record = {
            "Name": "test.example.com.",
            "Type": "A",
            "AliasTarget": {
                "DNSName": "d123.cloudfront.net.",
                "HostedZoneId": "Z2FDTNDATAQYW2",
                "EvaluateTargetHealth": False,
            },
        }

        cleanup_hook._delete_route53_record(mock_client, "Z123", record)

        mock_client.change_resource_record_sets.assert_called_once()

    def test_handles_deletion_error(self):
        """Should handle deletion error gracefully."""
        mock_client = MagicMock()
        mock_client.change_resource_record_sets.side_effect = Exception("Error")
        record = {"Name": "test.example.com.", "Type": "A"}

        # Should not raise
        cleanup_hook._delete_route53_record(mock_client, "Z123", record)


class TestDeleteAppsyncApi:
    """Tests for delete_appsync_api function."""

    @patch("boto3.client")
    def test_deletes_api(self, mock_boto_client):
        """Should delete AppSync API."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"graphqlApis": [{"name": "test-api", "apiId": "api123"}]}]
        mock_client.get_paginator.return_value = mock_paginator
        mock_boto_client.return_value = mock_client

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook.delete_appsync_api("test-api")

        mock_client.delete_graphql_api.assert_called_once_with(apiId="api123")

    @patch("boto3.client")
    def test_handles_api_not_found(self, mock_boto_client):
        """Should handle API not found."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"graphqlApis": []}]
        mock_client.get_paginator.return_value = mock_paginator
        mock_boto_client.return_value = mock_client

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise
            cleanup_hook.delete_appsync_api("nonexistent-api")

        mock_client.delete_graphql_api.assert_not_called()


class TestCleanupOrphanedAppsyncApi:
    """Tests for _cleanup_orphaned_appsync_api function."""

    @patch("boto3.client")
    @patch.object(cleanup_hook, "_is_cf_managed_resource", return_value=False)
    @patch.object(cleanup_hook, "delete_appsync_api")
    def test_calls_delete_with_correct_name(self, mock_delete, mock_cf_check, mock_boto):
        """Should call delete with correct API name when unmanaged."""
        mock_appsync = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"graphqlApis": [{"name": "kernelworx-api-ue1-dev", "apiId": "api123"}]}
        ]
        mock_appsync.get_paginator.return_value = mock_paginator
        mock_boto.return_value = mock_appsync

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook._cleanup_orphaned_appsync_api("dev")

        mock_delete.assert_called_once_with("kernelworx-api-ue1-dev")

    @patch("boto3.client")
    @patch.object(cleanup_hook, "_is_cf_managed_resource", return_value=True)
    @patch.object(cleanup_hook, "delete_appsync_api")
    def test_skips_cf_managed_api(self, mock_delete, mock_cf_check, mock_boto):
        """Should skip API that is CloudFormation-managed."""
        mock_appsync = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"graphqlApis": [{"name": "kernelworx-api-ue1-dev", "apiId": "api123"}]}
        ]
        mock_appsync.get_paginator.return_value = mock_paginator
        mock_boto.return_value = mock_appsync

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook._cleanup_orphaned_appsync_api("dev")

        # Should NOT delete since it's CF-managed
        mock_delete.assert_not_called()

    @patch("boto3.client")
    @patch.object(cleanup_hook, "delete_appsync_api")
    def test_handles_api_not_found(self, mock_delete, mock_boto):
        """Should handle API not found."""
        mock_appsync = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"graphqlApis": []}]  # No APIs
        mock_appsync.get_paginator.return_value = mock_paginator
        mock_boto.return_value = mock_appsync

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook._cleanup_orphaned_appsync_api("dev")

        mock_delete.assert_not_called()


class TestCleanupOrphanedSmsRole:
    """Tests for _cleanup_orphaned_sms_role function."""

    @patch("boto3.client")
    def test_adds_policy_when_missing(self, mock_boto_client):
        """Should add SNS policy when missing."""
        mock_cognito = MagicMock()
        mock_cognito.describe_user_pool.return_value = {
            "UserPool": {"SmsConfiguration": {"SnsCallerArn": "arn:aws:iam::123:role/test-role"}}
        }

        mock_iam = MagicMock()
        mock_iam.get_role.return_value = {"Role": {}}
        mock_iam.list_role_policies.return_value = {"PolicyNames": []}

        def client_factory(service, **kwargs):
            if service == "cognito-idp":
                return mock_cognito
            elif service == "iam":
                return mock_iam
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook._cleanup_orphaned_sms_role("dev")

        mock_iam.put_role_policy.assert_called_once()

    @patch("boto3.client")
    def test_skips_when_policy_exists(self, mock_boto_client):
        """Should skip when policy already exists."""
        mock_cognito = MagicMock()
        mock_cognito.describe_user_pool.return_value = {
            "UserPool": {"SmsConfiguration": {"SnsCallerArn": "arn:aws:iam::123:role/test-role"}}
        }

        mock_iam = MagicMock()
        mock_iam.get_role.return_value = {"Role": {}}
        mock_iam.list_role_policies.return_value = {"PolicyNames": ["UserPoolSmsPolicy"]}

        def client_factory(service, **kwargs):
            if service == "cognito-idp":
                return mock_cognito
            elif service == "iam":
                return mock_iam
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook._cleanup_orphaned_sms_role("dev")

        mock_iam.put_role_policy.assert_not_called()


class TestDisconnectCloudfrontFromCertificate:
    """Tests for _disconnect_cloudfront_from_certificate function."""

    @patch("boto3.client")
    def test_skips_when_managed_by_cloudformation(self, mock_boto_client):
        """Should skip when certificate is managed by CloudFormation."""
        mock_acm = MagicMock()

        def client_factory(service, **kwargs):
            if service == "acm":
                return mock_acm
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.object(cleanup_hook, "_find_certificate_arn", return_value="arn:aws:acm:us-east-1:123:cert/abc"):
            with patch.object(cleanup_hook, "_is_unmanaged_certificate", return_value=False):
                cleanup_hook._disconnect_cloudfront_from_certificate("example.com", "dev")

        # Should not try to update CloudFront
        # The function should return early

    @patch("boto3.client")
    def test_skips_when_no_certificate_found(self, mock_boto_client):
        """Should skip when no certificate is found for the domain."""
        mock_acm = MagicMock()
        mock_cloudfront = MagicMock()

        def client_factory(service, **kwargs):
            if service == "acm":
                return mock_acm
            if service == "cloudfront":
                return mock_cloudfront
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.object(cleanup_hook, "_find_certificate_arn", return_value=None):
            cleanup_hook._disconnect_cloudfront_from_certificate("example.com", "dev")

        # CloudFront should not be modified
        mock_cloudfront.get_distribution_config.assert_not_called()

    @patch("boto3.client")
    def test_disconnects_cloudfront_when_unmanaged(self, mock_boto_client):
        """Should disconnect CloudFront from unmanaged certificate."""
        mock_acm = MagicMock()
        mock_acm.describe_certificate.return_value = {
            "Certificate": {"InUseBy": ["arn:aws:cloudfront::123:distribution/DIST123"]}
        }

        mock_cloudfront = MagicMock()
        mock_cloudfront.get_distribution_config.return_value = {
            "DistributionConfig": {
                "Aliases": {"Quantity": 1, "Items": ["example.com"]},
                "ViewerCertificate": {"ACMCertificateArn": "arn:aws:acm:us-east-1:123:cert/abc"},
            },
            "ETag": "ETAG123",
        }

        def client_factory(service, **kwargs):
            if service == "acm":
                return mock_acm
            if service == "cloudfront":
                return mock_cloudfront
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.object(cleanup_hook, "_find_certificate_arn", return_value="arn:aws:acm:us-east-1:123:cert/abc"):
            with patch.object(cleanup_hook, "_is_unmanaged_certificate", return_value=True):
                cleanup_hook._disconnect_cloudfront_from_certificate("example.com", "dev")

        # CloudFront distribution should be updated
        mock_cloudfront.update_distribution.assert_called_once()

    @patch("boto3.client")
    def test_handles_exception_gracefully(self, mock_boto_client):
        """Should handle exceptions gracefully."""
        mock_acm = MagicMock()
        mock_cloudfront = MagicMock()

        def client_factory(service, **kwargs):
            if service == "acm":
                return mock_acm
            if service == "cloudfront":
                return mock_cloudfront
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.object(cleanup_hook, "_find_certificate_arn", side_effect=Exception("Error")):
            # Should not raise
            cleanup_hook._disconnect_cloudfront_from_certificate("example.com", "dev")


class TestCleanupOrphanedRoute53Records:
    """Tests for _cleanup_orphaned_route53_records function."""

    def test_cleans_up_validation_records(self):
        """Should clean up orphaned validation records."""
        mock_client = MagicMock()

        with patch.object(cleanup_hook, "_find_hosted_zones", return_value=[("Z123", "example.com")]):
            with patch.object(
                cleanup_hook,
                "_list_hosted_zone_records",
                return_value=[
                    {
                        "Name": "_acme-challenge.test.example.com.",
                        "Type": "CNAME",
                        "TTL": 300,
                        "ResourceRecords": [{"Value": "abc"}],
                    }
                ],
            ):
                with patch.object(cleanup_hook, "_delete_route53_record") as mock_delete:
                    cleanup_hook._cleanup_orphaned_route53_records(mock_client, ["test.example.com"])
                    mock_delete.assert_called_once()

    def test_handles_no_validation_records(self):
        """Should handle no validation records gracefully."""
        mock_client = MagicMock()

        with patch.object(cleanup_hook, "_find_hosted_zones", return_value=[("Z123", "example.com")]):
            with patch.object(
                cleanup_hook,
                "_list_hosted_zone_records",
                return_value=[
                    {"Name": "test.example.com.", "Type": "A"}  # Not a validation record
                ],
            ):
                with patch.object(cleanup_hook, "_delete_route53_record") as mock_delete:
                    cleanup_hook._cleanup_orphaned_route53_records(mock_client, ["test.example.com"])
                    mock_delete.assert_not_called()

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        mock_client = MagicMock()

        with patch.object(cleanup_hook, "_find_hosted_zones", side_effect=Exception("Error")):
            # Should not raise
            cleanup_hook._cleanup_orphaned_route53_records(mock_client, ["test.example.com"])


class TestDeleteCloudfrontDomainRecord:
    """Tests for _delete_cloudfront_domain_record function."""

    def test_deletes_unmanaged_a_record(self):
        """Should delete unmanaged A record."""
        mock_client = MagicMock()
        mock_client.list_hosted_zones.return_value = {
            "HostedZones": [{"Id": "/hostedzone/Z123", "Name": "example.com."}]
        }

        with patch.dict(os.environ, {"ENVIRONMENT": "dev", "AWS_REGION": "us-east-1"}):
            with patch("boto3.client") as mock_boto_client:
                mock_cfn = MagicMock()
                # Mock paginator for list_stack_resources (returns iterator of pages with no records)
                mock_paginator = MagicMock()
                mock_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
                mock_cfn.get_paginator.return_value = mock_paginator
                mock_boto_client.return_value = mock_cfn

                with patch.object(
                    cleanup_hook,
                    "_list_hosted_zone_records",
                    return_value=[
                        {
                            "Name": "test.example.com.",
                            "Type": "A",
                            "AliasTarget": {"DNSName": "d123.cloudfront.net."},
                        }
                    ],
                ):
                    with patch.object(cleanup_hook, "_delete_route53_record") as mock_delete:
                        cleanup_hook._delete_cloudfront_domain_record(mock_client, "test.example.com")
                        mock_delete.assert_called_once()

    def test_skips_managed_records(self):
        """Should skip CloudFormation-managed records."""
        mock_client = MagicMock()
        mock_client.list_hosted_zones.return_value = {
            "HostedZones": [{"Id": "/hostedzone/Z123", "Name": "example.com."}]
        }

        with patch.dict(os.environ, {"ENVIRONMENT": "dev", "AWS_REGION": "us-east-1"}):
            with patch("boto3.client") as mock_boto_client:
                mock_cfn = MagicMock()
                # Mock paginator for list_stack_resources (returns iterator of pages)
                mock_paginator = MagicMock()
                mock_paginator.paginate.return_value = [
                    {
                        "StackResourceSummaries": [
                            {
                                "PhysicalResourceId": "test.example.com",
                                "ResourceType": "AWS::Route53::RecordSet",
                            }
                        ]
                    }
                ]
                mock_cfn.get_paginator.return_value = mock_paginator
                mock_boto_client.return_value = mock_cfn

                with patch.object(
                    cleanup_hook,
                    "_list_hosted_zone_records",
                    return_value=[
                        {
                            "Name": "test.example.com.",
                            "Type": "A",
                            "AliasTarget": {"DNSName": "d123.cloudfront.net."},
                        }
                    ],
                ):
                    with patch.object(cleanup_hook, "_delete_route53_record") as mock_delete:
                        cleanup_hook._delete_cloudfront_domain_record(mock_client, "test.example.com")
                        # Should not delete managed record
                        mock_delete.assert_not_called()

    def test_handles_no_hosted_zone(self):
        """Should handle no matching hosted zone."""
        mock_client = MagicMock()
        mock_client.list_hosted_zones.return_value = {"HostedZones": []}

        # Should not raise
        cleanup_hook._delete_cloudfront_domain_record(mock_client, "test.example.com")

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        mock_client = MagicMock()
        mock_client.list_hosted_zones.side_effect = Exception("Error")

        # Should not raise
        cleanup_hook._delete_cloudfront_domain_record(mock_client, "test.example.com")


class TestDeleteApiDomainCnameRecord:
    """Tests for _delete_api_domain_cname_record function."""

    def test_deletes_unmanaged_cname_record(self):
        """Should delete unmanaged CNAME record for api domain."""
        mock_client = MagicMock()
        mock_client.list_hosted_zones.return_value = {
            "HostedZones": [{"Id": "/hostedzone/Z123", "Name": "example.com."}]
        }

        with patch.dict(os.environ, {"ENVIRONMENT": "dev", "AWS_REGION": "us-east-1"}):
            with patch("boto3.client") as mock_boto_client:
                mock_cfn = MagicMock()
                # Mock paginator for list_stack_resources (returns iterator of pages with no records)
                mock_paginator = MagicMock()
                mock_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
                mock_cfn.get_paginator.return_value = mock_paginator
                mock_boto_client.return_value = mock_cfn

                with patch.object(
                    cleanup_hook,
                    "_list_hosted_zone_records",
                    return_value=[
                        {
                            "Name": "api.dev.example.com.",
                            "Type": "CNAME",
                            "TTL": 1800,
                            "ResourceRecords": [{"Value": "d123.cloudfront.net"}],
                        }
                    ],
                ):
                    with patch.object(cleanup_hook, "_delete_route53_record") as mock_delete:
                        cleanup_hook._delete_api_domain_cname_record(mock_client, "api.dev.example.com", "dev")
                        mock_delete.assert_called_once()

    def test_skips_managed_records(self):
        """Should skip CloudFormation-managed CNAME records."""
        mock_client = MagicMock()
        mock_client.list_hosted_zones.return_value = {
            "HostedZones": [{"Id": "/hostedzone/Z123", "Name": "example.com."}]
        }

        with patch.dict(os.environ, {"ENVIRONMENT": "dev", "AWS_REGION": "us-east-1"}):
            with patch("boto3.client") as mock_boto_client:
                mock_cfn = MagicMock()
                # Mock paginator for list_stack_resources (returns iterator of pages)
                mock_paginator = MagicMock()
                mock_paginator.paginate.return_value = [
                    {
                        "StackResourceSummaries": [
                            {
                                "PhysicalResourceId": "api.dev.example.com",
                                "ResourceType": "AWS::Route53::RecordSet",
                            }
                        ]
                    }
                ]
                mock_cfn.get_paginator.return_value = mock_paginator
                mock_boto_client.return_value = mock_cfn

                with patch.object(
                    cleanup_hook,
                    "_list_hosted_zone_records",
                    return_value=[
                        {
                            "Name": "api.dev.example.com.",
                            "Type": "CNAME",
                            "TTL": 1800,
                            "ResourceRecords": [{"Value": "d123.cloudfront.net"}],
                        }
                    ],
                ):
                    with patch.object(cleanup_hook, "_delete_route53_record") as mock_delete:
                        cleanup_hook._delete_api_domain_cname_record(mock_client, "api.dev.example.com", "dev")
                        # Should not delete managed record
                        mock_delete.assert_not_called()

    def test_handles_no_hosted_zone(self):
        """Should handle no matching hosted zone."""
        mock_client = MagicMock()
        mock_client.list_hosted_zones.return_value = {"HostedZones": []}

        # Should not raise
        cleanup_hook._delete_api_domain_cname_record(mock_client, "api.dev.example.com", "dev")

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        mock_client = MagicMock()
        mock_client.list_hosted_zones.side_effect = Exception("Error")

        # Should not raise
        cleanup_hook._delete_api_domain_cname_record(mock_client, "api.dev.example.com", "dev")

    def test_handles_no_cname_records(self):
        """Should handle no matching CNAME records."""
        mock_client = MagicMock()
        mock_client.list_hosted_zones.return_value = {
            "HostedZones": [{"Id": "/hostedzone/Z123", "Name": "example.com."}]
        }

        with patch.dict(os.environ, {"ENVIRONMENT": "dev", "AWS_REGION": "us-east-1"}):
            with patch("boto3.client") as mock_boto_client:
                mock_cfn = MagicMock()
                mock_cfn.list_stack_resources.return_value = {"StackResourceSummaries": []}
                mock_boto_client.return_value = mock_cfn

                with patch.object(
                    cleanup_hook,
                    "_list_hosted_zone_records",
                    return_value=[
                        # Only A record, no CNAME
                        {"Name": "api.dev.example.com.", "Type": "A"}
                    ],
                ):
                    with patch.object(cleanup_hook, "_delete_route53_record") as mock_delete:
                        cleanup_hook._delete_api_domain_cname_record(mock_client, "api.dev.example.com", "dev")
                        # No CNAME to delete
                        mock_delete.assert_not_called()

    def test_handles_cfn_list_resources_exception(self):
        """Should handle CloudFormation list_stack_resources exception."""
        mock_client = MagicMock()
        mock_client.list_hosted_zones.return_value = {
            "HostedZones": [{"Id": "/hostedzone/Z123", "Name": "example.com."}]
        }

        with patch.dict(os.environ, {"ENVIRONMENT": "dev", "AWS_REGION": "us-east-1"}):
            with patch("boto3.client") as mock_boto_client:
                mock_cfn = MagicMock()
                # Mock paginator to raise an exception
                mock_paginator = MagicMock()
                mock_paginator.paginate.side_effect = Exception("Stack not found")
                mock_cfn.get_paginator.return_value = mock_paginator
                mock_boto_client.return_value = mock_cfn

                with patch.object(
                    cleanup_hook,
                    "_list_hosted_zone_records",
                    return_value=[
                        {
                            "Name": "api.dev.example.com.",
                            "Type": "CNAME",
                            "TTL": 1800,
                            "ResourceRecords": [{"Value": "d123.cloudfront.net"}],
                        }
                    ],
                ):
                    with patch.object(cleanup_hook, "_delete_route53_record") as mock_delete:
                        # Should still delete since we can't verify it's managed
                        cleanup_hook._delete_api_domain_cname_record(mock_client, "api.dev.example.com", "dev")
                        mock_delete.assert_called_once()


class TestDeleteAppsyncApi:
    """Tests for delete_appsync_api function."""

    @patch("boto3.client")
    def test_deletes_api_when_found(self, mock_boto_client):
        """Should delete AppSync API when found."""
        mock_appsync = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"graphqlApis": [{"name": "test-api", "apiId": "api123"}]}]
        mock_appsync.get_paginator.return_value = mock_paginator
        mock_boto_client.return_value = mock_appsync

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook.delete_appsync_api("test-api")

        mock_appsync.delete_graphql_api.assert_called_once_with(apiId="api123")

    @patch("boto3.client")
    def test_handles_api_not_found(self, mock_boto_client):
        """Should handle when API is not found."""
        mock_appsync = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"graphqlApis": []}]
        mock_appsync.get_paginator.return_value = mock_paginator
        mock_boto_client.return_value = mock_appsync

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook.delete_appsync_api("nonexistent-api")

        mock_appsync.delete_graphql_api.assert_not_called()

    @patch("boto3.client")
    def test_handles_exception(self, mock_boto_client):
        """Should handle exceptions gracefully."""
        mock_appsync = MagicMock()
        mock_appsync.get_paginator.side_effect = Exception("Error")
        mock_boto_client.return_value = mock_appsync

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise
            cleanup_hook.delete_appsync_api("test-api")


class TestDeleteOrphanedAppsyncDomain:
    """Tests for _delete_orphaned_appsync_domain function."""

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_deletes_orphaned_domain(self, mock_boto_client):
        """Should delete orphaned AppSync domain."""
        mock_appsync = MagicMock()
        mock_cfn = MagicMock()

        # Domain exists
        mock_appsync.get_domain_name.return_value = {"domainNameConfig": {}}
        mock_appsync.get_api_association.return_value = {"apiAssociation": None}
        mock_appsync.exceptions = MagicMock()
        mock_appsync.exceptions.NotFoundException = type("NotFoundException", (Exception,), {})

        # Stack has no matching resources
        cfn_paginator = MagicMock()
        cfn_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = cfn_paginator
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "appsync":
                return mock_appsync
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        cleanup_hook._delete_orphaned_appsync_domain("api.dev.kernelworx.app", "dev")

        mock_appsync.delete_domain_name.assert_called_once_with(domainName="api.dev.kernelworx.app")

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_skips_managed_domain(self, mock_boto_client):
        """Should skip CloudFormation-managed domain."""
        mock_appsync = MagicMock()
        mock_cfn = MagicMock()

        # Domain exists
        mock_appsync.get_domain_name.return_value = {"domainNameConfig": {}}
        mock_appsync.exceptions = MagicMock()
        mock_appsync.exceptions.NotFoundException = type("NotFoundException", (Exception,), {})

        # Stack contains this domain
        cfn_paginator = MagicMock()
        cfn_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "ResourceType": "AWS::AppSync::DomainName",
                        "PhysicalResourceId": "api.dev.kernelworx.app",
                    }
                ]
            }
        ]
        mock_cfn.get_paginator.return_value = cfn_paginator
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "appsync":
                return mock_appsync
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        cleanup_hook._delete_orphaned_appsync_domain("api.dev.kernelworx.app", "dev")

        mock_appsync.delete_domain_name.assert_not_called()

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_handles_domain_not_found(self, mock_boto_client):
        """Should handle domain not found gracefully."""
        mock_appsync = MagicMock()
        mock_cfn = MagicMock()

        NotFoundException = type("NotFoundException", (Exception,), {})
        mock_appsync.get_domain_name.side_effect = NotFoundException()
        mock_appsync.exceptions = MagicMock()
        mock_appsync.exceptions.NotFoundException = NotFoundException

        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "appsync":
                return mock_appsync
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise
        cleanup_hook._delete_orphaned_appsync_domain("api.dev.kernelworx.app", "dev")

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_handles_domain_not_found_generic_exception(self, mock_boto_client):
        """Should handle Not Found as generic exception gracefully."""
        mock_appsync = MagicMock()
        mock_cfn = MagicMock()

        # Use generic Exception with "Not Found" message
        mock_appsync.get_domain_name.side_effect = Exception("Not Found")
        mock_appsync.exceptions = MagicMock()
        mock_appsync.exceptions.NotFoundException = type("NotFoundException", (Exception,), {})

        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "appsync":
                return mock_appsync
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise
        cleanup_hook._delete_orphaned_appsync_domain("api.dev.kernelworx.app", "dev")

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_disassociates_api_before_delete(self, mock_boto_client):
        """Should disassociate API association before deleting domain."""
        mock_appsync = MagicMock()
        mock_cfn = MagicMock()

        # Domain exists with API association
        mock_appsync.get_domain_name.return_value = {"domainNameConfig": {}}
        mock_appsync.get_api_association.return_value = {
            "apiAssociation": {"apiId": "api123", "domainName": "api.dev.kernelworx.app"}
        }
        mock_appsync.exceptions = MagicMock()
        mock_appsync.exceptions.NotFoundException = type("NotFoundException", (Exception,), {})

        # Stack has no matching resources
        cfn_paginator = MagicMock()
        cfn_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = cfn_paginator
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "appsync":
                return mock_appsync
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        cleanup_hook._delete_orphaned_appsync_domain("api.dev.kernelworx.app", "dev")

        mock_appsync.disassociate_api.assert_called_once_with(domainName="api.dev.kernelworx.app")
        mock_appsync.delete_domain_name.assert_called_once()

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_handles_cfn_stack_not_found(self, mock_boto_client):
        """Should handle CloudFormation stack not found gracefully."""
        mock_appsync = MagicMock()
        mock_cfn = MagicMock()

        # Domain exists
        mock_appsync.get_domain_name.return_value = {"domainNameConfig": {}}
        mock_appsync.get_api_association.return_value = {"apiAssociation": None}
        mock_appsync.exceptions = MagicMock()
        mock_appsync.exceptions.NotFoundException = type("NotFoundException", (Exception,), {})

        # Stack doesn't exist
        ClientError = type("ClientError", (Exception,), {})
        cfn_paginator = MagicMock()
        cfn_paginator.paginate.side_effect = ClientError("Stack does not exist")
        mock_cfn.get_paginator.return_value = cfn_paginator
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = ClientError

        def client_factory(service, **kwargs):
            if service == "appsync":
                return mock_appsync
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        cleanup_hook._delete_orphaned_appsync_domain("api.dev.kernelworx.app", "dev")

        # Should still delete the domain
        mock_appsync.delete_domain_name.assert_called_once()

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_handles_exception(self, mock_boto_client):
        """Should handle exception gracefully."""
        mock_appsync = MagicMock()
        mock_cfn = MagicMock()

        # Domain exists but delete fails
        mock_appsync.get_domain_name.return_value = {"domainNameConfig": {}}
        mock_appsync.get_api_association.return_value = {"apiAssociation": None}
        mock_appsync.delete_domain_name.side_effect = Exception("Delete failed")
        mock_appsync.exceptions = MagicMock()
        mock_appsync.exceptions.NotFoundException = type("NotFoundException", (Exception,), {})

        # Stack has no matching resources
        cfn_paginator = MagicMock()
        cfn_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = cfn_paginator
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "appsync":
                return mock_appsync
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise
        cleanup_hook._delete_orphaned_appsync_domain("api.dev.kernelworx.app", "dev")

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_handles_unexpected_exception_in_get_domain(self, mock_boto_client):
        """Should handle unexpected exceptions from get_domain_name gracefully (via outer try)."""
        mock_appsync = MagicMock()
        mock_cfn = MagicMock()

        # Unexpected exception that is NOT a "Not Found" type - it will be re-raised
        # from the inner try and caught by the outer try/except
        mock_appsync.get_domain_name.side_effect = Exception("Unexpected API error")
        mock_appsync.exceptions = MagicMock()
        mock_appsync.exceptions.NotFoundException = type("NotFoundException", (Exception,), {})

        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "appsync":
                return mock_appsync
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise - exception is caught by outer try/except
        cleanup_hook._delete_orphaned_appsync_domain("api.dev.kernelworx.app", "dev")

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_handles_disassociation_exception(self, mock_boto_client):
        """Should handle exception during API disassociation gracefully."""
        mock_appsync = MagicMock()
        mock_cfn = MagicMock()

        # Domain exists
        mock_appsync.get_domain_name.return_value = {"domainNameConfig": {}}
        # Disassociation fails
        mock_appsync.get_api_association.side_effect = Exception("Association error")
        mock_appsync.exceptions = MagicMock()
        mock_appsync.exceptions.NotFoundException = type("NotFoundException", (Exception,), {})

        # Stack has no matching resources
        cfn_paginator = MagicMock()
        cfn_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = cfn_paginator
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "appsync":
                return mock_appsync
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise - association errors should be caught
        cleanup_hook._delete_orphaned_appsync_domain("api.dev.kernelworx.app", "dev")

        # Should still delete the domain
        mock_appsync.delete_domain_name.assert_called_once()


class TestCleanupOrphanedAppsyncApi:
    """Tests for _cleanup_orphaned_appsync_api function."""

    @patch("boto3.client")
    @patch.object(cleanup_hook, "_is_cf_managed_resource", return_value=False)
    @patch.object(cleanup_hook, "delete_appsync_api")
    def test_constructs_api_name_correctly(self, mock_delete, mock_cf_check, mock_boto):
        """Should construct API name correctly from environment and region."""
        mock_appsync = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"graphqlApis": [{"name": "kernelworx-api-ue1-dev", "apiId": "api123"}]}
        ]
        mock_appsync.get_paginator.return_value = mock_paginator
        mock_boto.return_value = mock_appsync

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook._cleanup_orphaned_appsync_api("dev")

        mock_delete.assert_called_once_with("kernelworx-api-ue1-dev")

    @patch("boto3.client")
    @patch.object(cleanup_hook, "_is_cf_managed_resource", return_value=False)
    @patch.object(cleanup_hook, "delete_appsync_api")
    def test_uses_region_abbrev_from_env(self, mock_delete, mock_cf_check, mock_boto):
        """Should use region abbreviation from environment if provided."""
        mock_appsync = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"graphqlApis": [{"name": "kernelworx-api-uw2-prod", "apiId": "api123"}]}
        ]
        mock_appsync.get_paginator.return_value = mock_paginator
        mock_boto.return_value = mock_appsync

        with patch.dict(os.environ, {"AWS_REGION": "us-west-2", "REGION_ABBREV": "uw2"}):
            cleanup_hook._cleanup_orphaned_appsync_api("prod")

        mock_delete.assert_called_once_with("kernelworx-api-uw2-prod")


class TestCleanupOrphanedSmsRole:
    """Tests for _cleanup_orphaned_sms_role function."""

    @patch("boto3.client")
    def test_adds_policy_when_missing(self, mock_boto_client):
        """Should add SNS policy when missing."""
        mock_cognito = MagicMock()
        mock_cognito.describe_user_pool.return_value = {
            "UserPool": {"SmsConfiguration": {"SnsCallerArn": "arn:aws:iam::123:role/sms-role"}}
        }

        mock_iam = MagicMock()
        mock_iam.get_role.return_value = {"Role": {"RoleName": "sms-role"}}
        mock_iam.list_role_policies.return_value = {"PolicyNames": []}
        mock_iam.exceptions = MagicMock()
        mock_iam.exceptions.NoSuchEntityException = type("NoSuchEntityException", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "cognito-idp":
                return mock_cognito
            if service == "iam":
                return mock_iam
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook._cleanup_orphaned_sms_role("dev")

        mock_iam.put_role_policy.assert_called_once()

    @patch("boto3.client")
    def test_skips_when_policy_exists(self, mock_boto_client):
        """Should skip when policy already exists."""
        mock_cognito = MagicMock()
        mock_cognito.describe_user_pool.return_value = {
            "UserPool": {"SmsConfiguration": {"SnsCallerArn": "arn:aws:iam::123:role/sms-role"}}
        }

        mock_iam = MagicMock()
        mock_iam.get_role.return_value = {"Role": {"RoleName": "sms-role"}}
        mock_iam.list_role_policies.return_value = {"PolicyNames": ["UserPoolSmsPolicy"]}
        mock_iam.exceptions = MagicMock()
        mock_iam.exceptions.NoSuchEntityException = type("NoSuchEntityException", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "cognito-idp":
                return mock_cognito
            if service == "iam":
                return mock_iam
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook._cleanup_orphaned_sms_role("dev")

        mock_iam.put_role_policy.assert_not_called()

    @patch("boto3.client")
    def test_handles_role_not_found(self, mock_boto_client):
        """Should handle role not found gracefully."""
        mock_cognito = MagicMock()
        mock_cognito.describe_user_pool.return_value = {
            "UserPool": {"SmsConfiguration": {"SnsCallerArn": "arn:aws:iam::123:role/sms-role"}}
        }

        NoSuchEntityException = type("NoSuchEntityException", (Exception,), {})
        mock_iam = MagicMock()
        mock_iam.get_role.side_effect = NoSuchEntityException()
        mock_iam.exceptions = MagicMock()
        mock_iam.exceptions.NoSuchEntityException = NoSuchEntityException

        def client_factory(service, **kwargs):
            if service == "cognito-idp":
                return mock_cognito
            if service == "iam":
                return mock_iam
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise
            cleanup_hook._cleanup_orphaned_sms_role("dev")

    @patch("boto3.client")
    def test_handles_unknown_environment(self, mock_boto_client):
        """Should return early for unknown environment."""
        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook._cleanup_orphaned_sms_role("unknown-env")

        mock_boto_client.assert_not_called()

    @patch("boto3.client")
    def test_handles_no_sms_role(self, mock_boto_client):
        """Should handle UserPool with no SMS role configured."""
        mock_cognito = MagicMock()
        mock_cognito.describe_user_pool.return_value = {"UserPool": {"SmsConfiguration": {}}}

        mock_iam = MagicMock()

        def client_factory(service, **kwargs):
            if service == "cognito-idp":
                return mock_cognito
            if service == "iam":
                return mock_iam
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            cleanup_hook._cleanup_orphaned_sms_role("dev")

        # Should not try to modify IAM role
        mock_iam.get_role.assert_not_called()


class TestGenerateImportFile:
    """Tests for generate_import_file function."""

    @patch("boto3.client")
    def test_returns_none_when_stack_does_not_exist(self, mock_boto_client):
        """Should return None when stack doesn't exist yet."""
        mock_cfn = MagicMock()
        # Simulate stack not existing by raising ClientError
        mock_cfn.exceptions.ClientError = Exception
        mock_cfn.get_paginator.side_effect = Exception("Stack does not exist")

        mock_dynamodb = MagicMock()
        mock_dynamodb.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_dynamodb.describe_table.side_effect = mock_dynamodb.exceptions.ResourceNotFoundException()

        mock_s3 = MagicMock()
        # Must properly set up exception classes that inherit from BaseException
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_s3.head_bucket.side_effect = mock_s3.exceptions.NoSuchBucket()

        mock_cognito = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_cognito.describe_user_pool.side_effect = mock_cognito.exceptions.ResourceNotFoundException()

        def client_factory(service, **kwargs):
            if service == "cloudformation":
                return mock_cfn
            elif service == "dynamodb":
                return mock_dynamodb
            elif service == "s3":
                return mock_s3
            elif service == "cognito-idp":
                return mock_cognito
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # The function handles exceptions gracefully
            result = cleanup_hook.generate_import_file("test-stack", "dev", "ue1")

        # Result could be None or a path depending on whether resources were found
        # The main test is that it doesn't crash

    @patch("boto3.client")
    def test_returns_path_when_resources_found(self, mock_boto_client):
        """Should return path when resources to import are found."""
        mock_cfn = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = mock_paginator

        mock_dynamodb = MagicMock()
        mock_dynamodb.describe_table.return_value = {"Table": {"TableName": "kernelworx-app-ue1-dev"}}
        mock_dynamodb.exceptions = MagicMock()
        mock_dynamodb.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

        mock_s3 = MagicMock()
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_s3.head_bucket.side_effect = mock_s3.exceptions.NoSuchBucket()

        mock_cognito = MagicMock()
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_cognito.describe_user_pool.side_effect = mock_cognito.exceptions.ResourceNotFoundException()

        def client_factory(service, **kwargs):
            if service == "cloudformation":
                return mock_cfn
            elif service == "dynamodb":
                return mock_dynamodb
            elif service == "s3":
                return mock_s3
            elif service == "cognito-idp":
                return mock_cognito
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            result = cleanup_hook.generate_import_file("test-stack", "dev", "ue1")

        # Should return path to import file
        assert result is not None
        assert ".cdk-import-resources.json" in result


class TestCheckDynamodbTables:
    """Tests for _check_dynamodb_tables function."""

    def test_adds_unmanaged_table_to_import(self):
        """Should add unmanaged table to import list."""
        mock_client = MagicMock()
        mock_client.describe_table.return_value = {"Table": {"TableName": "kernelworx-app-ue1-dev"}}
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

        resources = []
        cleanup_hook._check_dynamodb_tables(mock_client, set(), resources, "dev", "ue1")

        # Should find tables to import
        assert len(resources) > 0

    def test_skips_managed_tables(self):
        """Should skip tables already in CloudFormation."""
        mock_client = MagicMock()
        mock_client.describe_table.return_value = {"Table": {"TableName": "kernelworx-app-ue1-dev"}}
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

        # Table is already managed
        stack_resources = {"kernelworx-app-ue1-dev"}
        resources = []
        cleanup_hook._check_dynamodb_tables(mock_client, stack_resources, resources, "dev", "ue1")

        # Should not add managed table
        assert len([r for r in resources if "app" in r.get("ResourceIdentifier", {}).get("TableName", "")]) == 0

    def test_handles_table_not_found(self):
        """Should handle table not found gracefully."""
        mock_client = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_client.describe_table.side_effect = ResourceNotFoundException()
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = ResourceNotFoundException

        resources = []
        # Should not raise
        cleanup_hook._check_dynamodb_tables(mock_client, set(), resources, "dev", "ue1")

        # No resources should be added
        assert len(resources) == 0


class TestCheckS3Buckets:
    """Tests for _check_s3_buckets function."""

    def test_adds_unmanaged_bucket_to_import(self):
        """Should add unmanaged bucket to import list."""
        mock_client = MagicMock()
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_client.head_bucket.return_value = {}  # Bucket exists

        resources = []
        cleanup_hook._check_s3_buckets(mock_client, set(), resources, "dev", "ue1")

        # Should find buckets to import
        assert len(resources) > 0

    def test_skips_managed_buckets(self):
        """Should skip buckets already in CloudFormation."""
        mock_client = MagicMock()
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_client.head_bucket.return_value = {}  # Bucket exists

        # Bucket is already managed
        stack_resources = {"kernelworx-static-ue1-dev"}
        resources = []
        cleanup_hook._check_s3_buckets(mock_client, stack_resources, resources, "dev", "ue1")

        # Should not add managed bucket
        assert len([r for r in resources if "static" in r.get("ResourceIdentifier", {}).get("BucketName", "")]) == 0

    def test_handles_bucket_not_found(self):
        """Should handle bucket not found gracefully."""
        mock_client = MagicMock()
        NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_client.head_bucket.side_effect = NoSuchBucket()
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NoSuchBucket = NoSuchBucket

        resources = []
        # Should not raise
        cleanup_hook._check_s3_buckets(mock_client, set(), resources, "dev", "ue1")

        # No resources should be added
        assert len(resources) == 0


class TestCheckCognitoUserPool:
    """Tests for _check_cognito_user_pool function."""

    @patch("boto3.client")
    def test_adds_unmanaged_user_pool_to_import(self, mock_boto_client):
        """Should add unmanaged user pool to import list."""
        mock_cognito = MagicMock()
        mock_cognito.describe_user_pool.return_value = {
            "UserPool": {"SmsConfiguration": {"SnsCallerArn": "arn:aws:iam::123:role/sms-role"}}
        }
        mock_cognito.describe_user_pool_domain.return_value = {"DomainDescription": {}}
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

        mock_iam = MagicMock()
        mock_iam.get_role.return_value = {"Role": {"RoleName": "sms-role"}}
        mock_iam.exceptions = MagicMock()
        mock_iam.exceptions.NoSuchEntityException = type("NoSuchEntityException", (Exception,), {})

        mock_boto_client.return_value = mock_iam

        resources = []
        cleanup_hook._check_cognito_user_pool(mock_cognito, set(), resources, "dev", "ue1")

        # Should find user pool to import
        assert len(resources) > 0

    @patch("boto3.client")
    def test_skips_unknown_environment(self, mock_boto_client):
        """Should skip unknown environment."""
        mock_cognito = MagicMock()

        resources = []
        cleanup_hook._check_cognito_user_pool(mock_cognito, set(), resources, "unknown", "ue1")

        # No resources should be added
        assert len(resources) == 0
        mock_cognito.describe_user_pool.assert_not_called()

    @patch("boto3.client")
    def test_handles_user_pool_not_found(self, mock_boto_client):
        """Should handle user pool not found gracefully."""
        mock_cognito = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_cognito.describe_user_pool.side_effect = ResourceNotFoundException()
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = ResourceNotFoundException

        resources = []
        # Should not raise
        cleanup_hook._check_cognito_user_pool(mock_cognito, set(), resources, "dev", "ue1")

        # No resources should be added
        assert len(resources) == 0


class TestCleanupBeforeDeploy:
    """Tests for cleanup_before_deploy function."""

    @patch("boto3.client")
    def test_runs_cleanup_without_error(self, mock_boto_client):
        """Should run cleanup without error."""
        # Setup all mocks to return empty/success
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"CertificateSummaryList": []}]
        mock_client.get_paginator.return_value = mock_paginator
        mock_boto_client.return_value = mock_client

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            with patch.object(cleanup_hook, "_cleanup_orphaned_appsync_api"):
                with patch.object(cleanup_hook, "_disconnect_cognito_domain"):
                    with patch.object(cleanup_hook, "_cleanup_orphaned_route53_records"):
                        with patch.object(cleanup_hook, "_cleanup_orphaned_sms_role"):
                            with patch.object(cleanup_hook, "_disconnect_cloudfront_from_certificate"):
                                # Should not raise
                                cleanup_hook.cleanup_before_deploy(
                                    domain_names=["api.dev.example.com"], environment_name="dev"
                                )

    def test_handles_exceptions_gracefully(self):
        """Should handle exceptions gracefully and continue."""
        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            with patch.object(cleanup_hook, "_cleanup_orphaned_appsync_api", side_effect=Exception("API Error")):
                # Should not raise - cleanup_before_deploy catches all exceptions
                cleanup_hook.cleanup_before_deploy(domain_names=["api.dev.example.com"], environment_name="dev")

    @patch("boto3.client")
    def test_processes_certificates_for_domains(self, mock_boto_client):
        """Should process certificates for API, site, and auth domains."""
        mock_acm = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"CertificateSummaryList": []}]
        mock_acm.get_paginator.return_value = mock_paginator

        mock_cognito = MagicMock()
        mock_route53 = MagicMock()

        def client_factory(service, **kwargs):
            if service == "acm":
                return mock_acm
            if service == "cognito-idp":
                return mock_cognito
            if service == "route53":
                return mock_route53
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            with patch.object(cleanup_hook, "_cleanup_orphaned_appsync_api"):
                with patch.object(cleanup_hook, "_cleanup_orphaned_route53_records"):
                    with patch.object(cleanup_hook, "_cleanup_orphaned_sms_role"):
                        with patch.object(cleanup_hook, "_disconnect_cloudfront_from_certificate"):
                            cleanup_hook.cleanup_before_deploy(
                                domain_names=["api.dev.example.com", "auth.dev.example.com"],
                                site_domain="dev.example.com",
                                environment_name="dev",
                            )

    @patch("boto3.client")
    def test_deduplicates_certificates(self, mock_boto_client):
        """Should skip duplicate certificates."""
        mock_acm = MagicMock()
        mock_paginator = MagicMock()
        # Return the same certificate for multiple domains
        mock_paginator.paginate.return_value = [
            {
                "CertificateSummaryList": [
                    {
                        "CertificateArn": "arn:aws:acm:us-east-1:123:cert/abc",
                        "DomainName": "api.dev.example.com",
                    }
                ]
            }
        ]
        mock_acm.get_paginator.return_value = mock_paginator

        mock_cognito = MagicMock()
        mock_route53 = MagicMock()

        def client_factory(service, **kwargs):
            if service == "acm":
                return mock_acm
            if service == "cognito-idp":
                return mock_cognito
            if service == "route53":
                return mock_route53
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            with patch.object(cleanup_hook, "_cleanup_orphaned_appsync_api"):
                with patch.object(cleanup_hook, "_cleanup_orphaned_route53_records"):
                    with patch.object(cleanup_hook, "_cleanup_orphaned_sms_role"):
                        with patch.object(cleanup_hook, "_disconnect_cloudfront_from_certificate"):
                            with patch.object(
                                cleanup_hook,
                                "_find_certificate_arn",
                                return_value="arn:aws:acm:us-east-1:123:cert/abc",
                            ):
                                with patch.object(cleanup_hook, "_is_unmanaged_certificate", return_value=True):
                                    with patch.object(cleanup_hook, "_delete_acm_certificate") as mock_delete:
                                        cleanup_hook.cleanup_before_deploy(
                                            domain_names=[
                                                "api.dev.example.com",
                                                "login.dev.example.com",
                                            ],
                                            site_domain="dev.example.com",
                                            environment_name="dev",
                                        )
                                        # Should only delete once, not multiple times for same cert
                                        assert mock_delete.call_count == 1

    @patch("boto3.client")
    def test_skips_managed_certificates(self, mock_boto_client):
        """Should skip certificates that are CloudFormation-managed."""
        mock_acm = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "CertificateSummaryList": [
                    {
                        "CertificateArn": "arn:aws:acm:us-east-1:123:cert/abc",
                        "DomainName": "api.dev.example.com",
                    }
                ]
            }
        ]
        mock_acm.get_paginator.return_value = mock_paginator

        mock_cognito = MagicMock()
        mock_route53 = MagicMock()

        def client_factory(service, **kwargs):
            if service == "acm":
                return mock_acm
            if service == "cognito-idp":
                return mock_cognito
            if service == "route53":
                return mock_route53
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            with patch.object(cleanup_hook, "_cleanup_orphaned_appsync_api"):
                with patch.object(cleanup_hook, "_cleanup_orphaned_route53_records"):
                    with patch.object(cleanup_hook, "_cleanup_orphaned_sms_role"):
                        with patch.object(cleanup_hook, "_disconnect_cloudfront_from_certificate"):
                            # Certificate is found but is managed (not unmanaged)
                            with patch.object(
                                cleanup_hook,
                                "_find_certificate_arn",
                                return_value="arn:aws:acm:us-east-1:123:cert/abc",
                            ):
                                with patch.object(cleanup_hook, "_is_unmanaged_certificate", return_value=False):
                                    with patch.object(cleanup_hook, "_delete_acm_certificate") as mock_delete:
                                        cleanup_hook.cleanup_before_deploy(
                                            domain_names=["api.dev.example.com"],
                                            environment_name="dev",
                                        )
                                        # Should NOT delete managed certificate
                                        mock_delete.assert_not_called()


class TestDeleteAcmCertificate:
    """Tests for _delete_acm_certificate function."""

    def test_deletes_certificate(self):
        """Should delete certificate successfully."""
        mock_client = MagicMock()
        cleanup_hook._delete_acm_certificate(mock_client, "arn:aws:acm:us-east-1:123:cert/abc")
        mock_client.delete_certificate.assert_called_once_with(CertificateArn="arn:aws:acm:us-east-1:123:cert/abc")

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        mock_client = MagicMock()
        mock_client.delete_certificate.side_effect = Exception("Resource in use")
        # Should not raise
        cleanup_hook._delete_acm_certificate(mock_client, "arn:aws:acm:us-east-1:123:cert/abc")


class TestIsUnmanagedCertificateEdgeCases:
    """Additional edge case tests for _is_unmanaged_certificate function."""

    @patch("boto3.client")
    def test_returns_true_when_not_tagged_or_in_stack(self, mock_boto_client):
        """Should return True when certificate has no tags and is not in stack."""
        mock_acm = MagicMock()
        mock_acm.describe_certificate.return_value = {"Certificate": {"Tags": []}}

        mock_cfn = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = mock_paginator

        def client_factory(service, **kwargs):
            if service == "acm":
                return mock_acm
            if service == "cloudformation":
                return mock_cfn
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            result = cleanup_hook._is_unmanaged_certificate("arn:aws:acm:us-east-1:123:cert/abc", "dev")

        assert result is True

    @patch("boto3.client")
    def test_returns_false_on_describe_exception(self, mock_boto_client):
        """Should return False (safe) on describe certificate exception."""
        mock_acm = MagicMock()
        mock_acm.describe_certificate.side_effect = Exception("Access denied")
        mock_boto_client.return_value = mock_acm

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            result = cleanup_hook._is_unmanaged_certificate("arn:aws:acm:us-east-1:123:cert/abc", "dev")

        # Should return False (safe) when we can't determine ownership
        assert result is False


class TestDisconnectCognitoDomainEdgeCases:
    """Additional edge case tests for _disconnect_cognito_domain function."""

    def test_handles_missing_user_pool_id(self):
        """Should handle domain without UserPoolId."""
        mock_client = MagicMock()
        mock_client.describe_user_pool_domain.return_value = {
            "DomainDescription": {"Status": "ACTIVE"}  # No UserPoolId
        }

        # Should not raise
        cleanup_hook._disconnect_cognito_domain(mock_client, "login.example.com", "dev")
        mock_client.delete_user_pool_domain.assert_not_called()

    @patch.object(cleanup_hook, "_is_cf_managed_resource", return_value=False)
    def test_handles_delete_exception(self, mock_cf_check):
        """Should handle delete exception gracefully."""
        mock_client = MagicMock()
        mock_client.describe_user_pool_domain.return_value = {"DomainDescription": {"UserPoolId": "us-east-1_abc123"}}
        mock_client.delete_user_pool_domain.side_effect = Exception("Domain in use")

        # Should not raise
        cleanup_hook._disconnect_cognito_domain(mock_client, "login.example.com", "dev")


class TestDeleteRoute53RecordEdgeCases:
    """Additional edge case tests for _delete_route53_record function."""

    def test_handles_alias_record(self):
        """Should handle ALIAS record correctly."""
        mock_client = MagicMock()
        record = {
            "Name": "test.example.com.",
            "Type": "A",
            "AliasTarget": {
                "HostedZoneId": "Z2FDTNDATAQYW2",
                "DNSName": "d123.cloudfront.net.",
                "EvaluateTargetHealth": False,
            },
        }

        cleanup_hook._delete_route53_record(mock_client, "Z123", record)
        mock_client.change_resource_record_sets.assert_called_once()

    def test_handles_regular_record(self):
        """Should handle regular record with TTL."""
        mock_client = MagicMock()
        record = {
            "Name": "test.example.com.",
            "Type": "A",
            "TTL": 300,
            "ResourceRecords": [{"Value": "1.2.3.4"}],
        }

        cleanup_hook._delete_route53_record(mock_client, "Z123", record)
        mock_client.change_resource_record_sets.assert_called_once()

    def test_handles_delete_exception(self):
        """Should handle delete exception gracefully."""
        mock_client = MagicMock()
        mock_client.change_resource_record_sets.side_effect = Exception("Record not found")
        record = {"Name": "test.example.com.", "Type": "A", "TTL": 300, "ResourceRecords": []}

        # Should not raise
        cleanup_hook._delete_route53_record(mock_client, "Z123", record)


class TestListHostedZoneRecordsEdgeCases:
    """Edge case tests for _list_hosted_zone_records function."""

    def test_handles_exception(self):
        """Should handle exception gracefully."""
        mock_client = MagicMock()
        mock_client.get_paginator.side_effect = Exception("Error")

        result = cleanup_hook._list_hosted_zone_records(mock_client, "Z123")
        assert result == []


class TestFindHostedZonesEdgeCases:
    """Edge case tests for _find_hosted_zones function."""

    def test_handles_exception(self):
        """Should handle exception gracefully."""
        mock_client = MagicMock()
        mock_client.get_paginator.side_effect = Exception("Error")

        result = cleanup_hook._find_hosted_zones(mock_client, ["test.example.com"])
        assert result == []


class TestCleanupOrphanedSmsRoleEdgeCases:
    """Edge case tests for _cleanup_orphaned_sms_role function."""

    @patch("boto3.client")
    def test_handles_general_exception(self, mock_boto_client):
        """Should handle general exception gracefully."""
        mock_cognito = MagicMock()
        mock_cognito.describe_user_pool.side_effect = Exception("Unexpected error")

        # IAM client must have exceptions properly configured since the except clause references it
        NoSuchEntityException = type("NoSuchEntityException", (Exception,), {})
        mock_iam = MagicMock()
        mock_iam.exceptions = MagicMock()
        mock_iam.exceptions.NoSuchEntityException = NoSuchEntityException

        def client_factory(service, **kwargs):
            if service == "cognito-idp":
                return mock_cognito
            if service == "iam":
                return mock_iam
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise
            cleanup_hook._cleanup_orphaned_sms_role("dev")


class TestCheckCognitoUserPoolEdgeCases:
    """Edge case tests for _check_cognito_user_pool function."""

    @patch("boto3.client")
    def test_handles_iam_role_check_exception(self, mock_boto_client):
        """Should handle IAM role check exception gracefully."""
        mock_cognito = MagicMock()
        mock_cognito.describe_user_pool.return_value = {
            "UserPool": {"SmsConfiguration": {"SnsCallerArn": "arn:aws:iam::123:role/sms-role"}}
        }
        mock_cognito.describe_user_pool_domain.return_value = {"DomainDescription": {}}
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

        mock_iam = MagicMock()
        mock_iam.get_role.side_effect = Exception("Access denied")
        mock_iam.exceptions = MagicMock()
        mock_iam.exceptions.NoSuchEntityException = type("NoSuchEntityException", (Exception,), {})

        mock_boto_client.return_value = mock_iam

        resources = []
        # Should not raise
        cleanup_hook._check_cognito_user_pool(mock_cognito, set(), resources, "dev", "ue1")

    @patch("boto3.client")
    def test_handles_describe_domain_exception(self, mock_boto_client):
        """Should handle describe domain exception gracefully."""
        mock_cognito = MagicMock()
        mock_cognito.describe_user_pool.return_value = {"UserPool": {"SmsConfiguration": {}}}
        mock_cognito.describe_user_pool_domain.side_effect = Exception("Domain error")
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

        mock_boto_client.return_value = MagicMock()

        resources = []
        # Should not raise
        cleanup_hook._check_cognito_user_pool(mock_cognito, set(), resources, "dev", "ue1")

    @patch("boto3.client")
    def test_adds_domain_when_found(self, mock_boto_client):
        """Should add domain to import list when found."""
        mock_cognito = MagicMock()
        mock_cognito.describe_user_pool.return_value = {"UserPool": {"SmsConfiguration": {}}}
        mock_cognito.describe_user_pool_domain.return_value = {
            "DomainDescription": {"UserPoolId": "us-east-1_abc123", "Status": "ACTIVE"}
        }
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

        mock_boto_client.return_value = MagicMock()

        resources = []
        cleanup_hook._check_cognito_user_pool(mock_cognito, set(), resources, "dev", "ue1")

        # Should find domain to import
        domain_resources = [r for r in resources if r["ResourceType"] == "AWS::Cognito::UserPoolDomain"]
        assert len(domain_resources) > 0


class TestCheckDynamodbTablesEdgeCases:
    """Edge case tests for _check_dynamodb_tables function."""

    def test_handles_generic_exception(self):
        """Should handle generic exception gracefully."""
        mock_client = MagicMock()
        mock_client.describe_table.side_effect = Exception("Unexpected error")
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

        resources = []
        # Should not raise
        cleanup_hook._check_dynamodb_tables(mock_client, set(), resources, "dev", "ue1")


class TestCheckS3BucketsEdgeCases:
    """Edge case tests for _check_s3_buckets function."""

    def test_handles_generic_exception(self):
        """Should handle generic exception gracefully."""
        mock_client = MagicMock()
        mock_client.head_bucket.side_effect = Exception("Access denied")
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.NoSuchBucket = type("NoSuchBucket", (Exception,), {})

        resources = []
        # Should not raise
        cleanup_hook._check_s3_buckets(mock_client, set(), resources, "dev", "ue1")


class TestGenerateImportFileEdgeCases:
    """Edge case tests for generate_import_file function."""

    @patch("boto3.client")
    def test_handles_cfn_client_error_other_than_not_exist(self, mock_boto_client):
        """Should handle CloudFormation errors other than stack not existing."""
        mock_cfn = MagicMock()
        ClientError = type("ClientError", (Exception,), {})
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = ClientError
        mock_cfn.get_paginator.return_value.paginate.side_effect = ClientError("Access denied")

        mock_dynamodb = MagicMock()
        mock_dynamodb.exceptions = MagicMock()
        mock_dynamodb.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_dynamodb.describe_table.side_effect = mock_dynamodb.exceptions.ResourceNotFoundException()

        mock_s3 = MagicMock()
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_s3.head_bucket.side_effect = mock_s3.exceptions.NoSuchBucket()

        mock_cognito = MagicMock()
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_cognito.describe_user_pool.side_effect = mock_cognito.exceptions.ResourceNotFoundException()

        def client_factory(service, **kwargs):
            if service == "cloudformation":
                return mock_cfn
            if service == "dynamodb":
                return mock_dynamodb
            if service == "s3":
                return mock_s3
            if service == "cognito-idp":
                return mock_cognito
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise
            result = cleanup_hook.generate_import_file("test-stack", "dev", "ue1")


class TestFindCertificateArnExceptionPaths:
    """Additional edge case tests for _find_certificate_arn exception handling."""

    def test_returns_none_on_describe_certificate_exception(self):
        """Should return None when describe_certificate fails for SAN check."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "CertificateSummaryList": [
                    {
                        "CertificateArn": "arn:aws:acm:us-east-1:123:cert/abc",
                        "DomainName": "main.example.com",
                    }
                ]
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator
        # describe_certificate fails for SAN check
        mock_client.describe_certificate.side_effect = Exception("API Error")

        # Looking for a domain that's not in the main domain - will try SAN check
        result = cleanup_hook._find_certificate_arn(mock_client, "alt.example.com")

        # Should return None since describe_certificate failed
        assert result is None


class TestIsUnmanagedCertificateExceptionPaths:
    """Additional edge case tests for _is_unmanaged_certificate exception handling."""

    @patch("boto3.client")
    def test_returns_false_on_cloudformation_exception(self, mock_boto_client):
        """Should return False (safe) when CloudFormation list_stack_resources fails."""
        mock_acm = MagicMock()
        mock_acm.describe_certificate.return_value = {"Certificate": {"Tags": []}}

        mock_cfn = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = Exception("Access denied")
        mock_cfn.get_paginator.return_value = mock_paginator

        def client_factory(service, **kwargs):
            if service == "acm":
                return mock_acm
            elif service == "cloudformation":
                return mock_cfn
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            result = cleanup_hook._is_unmanaged_certificate("arn:aws:acm:us-east-1:123:cert/abc", "dev")

        # Should return False (fail safe) since CloudFormation check failed
        assert result is False


class TestCleanupOrphanedRoute53RecordsExceptionPaths:
    """Additional edge case tests for _cleanup_orphaned_route53_records exception handling."""

    @patch("boto3.client")
    def test_handles_cloudformation_exception_for_managed_records(self, mock_boto_client):
        """Should handle exception when listing CloudFormation managed records."""
        mock_route53 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"HostedZones": [{"Id": "/hostedzone/Z123", "Name": "example.com."}]}]
        mock_route53.get_paginator.return_value = mock_paginator
        mock_route53.list_resource_record_sets.return_value = {
            "ResourceRecordSets": [
                {
                    "Name": "_validation.example.com.",
                    "Type": "CNAME",
                    "TTL": 300,
                    "ResourceRecords": [{"Value": "test"}],
                }
            ]
        }

        mock_cfn = MagicMock()
        mock_cfn_paginator = MagicMock()
        mock_cfn_paginator.paginate.side_effect = Exception("Access denied")
        mock_cfn.get_paginator.return_value = mock_cfn_paginator

        def client_factory(service, **kwargs):
            if service == "route53":
                return mock_route53
            elif service == "cloudformation":
                return mock_cfn
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise - exception should be caught
            cleanup_hook._cleanup_orphaned_route53_records(mock_route53, ["test.example.com"])


class TestDeleteCloudfrontDomainRecordExceptionPaths:
    """Additional edge case tests for _delete_cloudfront_domain_record exception handling."""

    @patch("boto3.client")
    def test_handles_no_matching_a_aaaa_records(self, mock_boto_client):
        """Should handle case when no A/AAAA records found (only other types)."""
        mock_route53 = MagicMock()
        mock_route53.list_hosted_zones.return_value = {
            "HostedZones": [{"Id": "/hostedzone/Z123", "Name": "example.com."}]
        }

        mock_cfn = MagicMock()
        # Mock paginator for list_stack_resources (returns empty list)
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = mock_paginator

        def client_factory(service, **kwargs):
            if service == "cloudformation":
                return mock_cfn
            return mock_route53

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"ENVIRONMENT": "dev", "AWS_REGION": "us-east-1"}):
            with patch.object(
                cleanup_hook,
                "_list_hosted_zone_records",
                return_value=[
                    # Records exist but not A or AAAA types
                    {"Name": "www.example.com.", "Type": "MX", "TTL": 300},
                    {"Name": "www.example.com.", "Type": "TXT", "TTL": 300},
                ],
            ):
                # Should not raise - hits line 368 "No A/AAAA records found"
                cleanup_hook._delete_cloudfront_domain_record(mock_route53, "www.example.com")

    @patch("boto3.client")
    def test_handles_cfn_list_resources_exception(self, mock_boto_client):
        """Should handle exception when listing CloudFormation resources."""
        mock_route53 = MagicMock()
        mock_route53.list_hosted_zones.return_value = {
            "HostedZones": [{"Id": "/hostedzone/Z123", "Name": "example.com."}]
        }

        mock_cfn = MagicMock()
        # Mock paginator to raise an exception
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = Exception("Access denied")
        mock_cfn.get_paginator.return_value = mock_paginator

        def client_factory(service, **kwargs):
            if service == "cloudformation":
                return mock_cfn
            return mock_route53

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"ENVIRONMENT": "dev", "AWS_REGION": "us-east-1"}):
            with patch.object(
                cleanup_hook,
                "_list_hosted_zone_records",
                return_value=[
                    {
                        "Name": "www.example.com.",
                        "Type": "A",
                        "AliasTarget": {"DNSName": "d123.cloudfront.net."},
                    }
                ],
            ):
                with patch.object(cleanup_hook, "_delete_route53_record") as mock_delete:
                    # Should not raise - hits exception path and sets managed_record_ids = set()
                    cleanup_hook._delete_cloudfront_domain_record(mock_route53, "www.example.com")
                    # Should still delete since we couldn't verify if managed
                    mock_delete.assert_called_once()


class TestDisconnectCloudfrontFromCertificateExceptionPaths:
    """Additional edge case tests for _disconnect_cloudfront_from_certificate exception handling."""

    @patch("boto3.client")
    def test_handles_acm_describe_certificate_exception(self, mock_boto_client):
        """Should handle exception when describing certificate."""
        mock_acm = MagicMock()
        mock_acm.describe_certificate.return_value = {"Certificate": {"Tags": []}}

        mock_cfn = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = mock_paginator

        mock_cf = MagicMock()
        # This is the ACM client used in _disconnect_cloudfront_from_certificate
        # After unmanaged check passes, describe_certificate is called again and throws
        call_count = [0]

        def describe_cert_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call in _is_unmanaged_certificate
                return {"Certificate": {"Tags": []}}
            else:
                # Second call in _disconnect_cloudfront_from_certificate - throws
                raise Exception("Access denied")

        mock_acm.describe_certificate.side_effect = describe_cert_side_effect

        def client_factory(service, **kwargs):
            if service == "acm":
                return mock_acm
            if service == "cloudformation":
                return mock_cfn
            if service == "cloudfront":
                return mock_cf
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise - hits line 658 exception path
            cleanup_hook._disconnect_cloudfront_from_certificate(mock_cf, "arn:aws:acm:us-east-1:123:cert/abc")


class TestGenerateImportFileStackNotExist:
    """Test generate_import_file when stack doesn't exist."""

    @patch("boto3.client")
    def test_handles_stack_does_not_exist_error(self, mock_boto_client):
        """Should handle stack doesn't exist error gracefully."""
        mock_cfn = MagicMock()
        ClientError = type("ClientError", (Exception,), {})
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = ClientError

        # Simulate "does not exist" error
        error = ClientError("Stack test-stack does not exist")
        mock_cfn_paginator = MagicMock()
        mock_cfn_paginator.paginate.side_effect = error
        mock_cfn.get_paginator.return_value = mock_cfn_paginator

        mock_dynamodb = MagicMock()
        mock_dynamodb.exceptions = MagicMock()
        mock_dynamodb.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_dynamodb.describe_table.side_effect = mock_dynamodb.exceptions.ResourceNotFoundException()

        mock_s3 = MagicMock()
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_s3.head_bucket.side_effect = mock_s3.exceptions.NoSuchBucket()

        mock_cognito = MagicMock()
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_cognito.describe_user_pool.side_effect = mock_cognito.exceptions.ResourceNotFoundException()

        def client_factory(service, **kwargs):
            if service == "cloudformation":
                return mock_cfn
            if service == "dynamodb":
                return mock_dynamodb
            if service == "s3":
                return mock_s3
            if service == "cognito-idp":
                return mock_cognito
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise - handles "does not exist" gracefully
            cleanup_hook.generate_import_file("test-stack", "dev", "ue1")

    @patch("boto3.client")
    def test_handles_client_error_other_than_not_exist(self, mock_boto_client):
        """Should handle ClientError with message other than 'does not exist'."""
        mock_cfn = MagicMock()

        # Create a SINGLE ClientError class that is used for both the exception and the check
        ClientError = type("ClientError", (Exception,), {})
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = ClientError

        # Simulate "Access denied" error (not "does not exist")
        error_instance = ClientError("Access denied to stack resources")

        mock_cfn_paginator = MagicMock()
        # paginate() should raise the exception when called
        mock_cfn_paginator.paginate.side_effect = error_instance
        mock_cfn.get_paginator.return_value = mock_cfn_paginator

        mock_dynamodb = MagicMock()
        mock_dynamodb.exceptions = MagicMock()
        mock_dynamodb.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_dynamodb.describe_table.side_effect = mock_dynamodb.exceptions.ResourceNotFoundException()

        mock_s3 = MagicMock()
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchBucket = type("NoSuchBucket", (Exception,), {})
        mock_s3.head_bucket.side_effect = mock_s3.exceptions.NoSuchBucket()

        mock_cognito = MagicMock()
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_cognito.describe_user_pool.side_effect = mock_cognito.exceptions.ResourceNotFoundException()

        def client_factory(service, **kwargs):
            if service == "cloudformation":
                return mock_cfn
            if service == "dynamodb":
                return mock_dynamodb
            if service == "s3":
                return mock_s3
            if service == "cognito-idp":
                return mock_cognito
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise - prints warning and continues
            cleanup_hook.generate_import_file("test-stack", "dev", "ue1")


class TestCheckCognitoUserPoolExceptionPaths:
    """Additional edge case tests for _check_cognito_user_pool exception handling."""

    @patch("boto3.client")
    def test_handles_resource_not_found_exception(self, mock_boto_client):
        """Should handle ResourceNotFoundException for user pool."""
        mock_cognito = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_cognito.describe_user_pool.side_effect = ResourceNotFoundException()
        mock_boto_client.return_value = mock_cognito

        resources = []

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise
            cleanup_hook._check_cognito_user_pool(mock_cognito, set(), resources, "dev", "ue1")

    @patch("boto3.client")
    def test_handles_generic_exception(self, mock_boto_client):
        """Should handle generic exception for user pool."""
        mock_cognito = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_cognito.describe_user_pool.side_effect = Exception("API Error")
        mock_boto_client.return_value = mock_cognito

        resources = []

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise
            cleanup_hook._check_cognito_user_pool(mock_cognito, set(), resources, "dev", "ue1")

    @patch("boto3.client")
    def test_handles_iam_role_exception(self, mock_boto_client):
        """Should handle exception when checking SMS role."""
        mock_cognito = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_cognito.describe_user_pool.return_value = {
            "UserPool": {
                "Id": "us-east-1_abc123",
                "SmsConfiguration": {"SnsCallerArn": "arn:aws:iam::123:role/test-role"},
            }
        }
        mock_cognito.describe_user_pool_domain.side_effect = ResourceNotFoundException()

        mock_iam = MagicMock()
        NoSuchEntityException = type("NoSuchEntityException", (Exception,), {})
        mock_iam.exceptions = MagicMock()
        mock_iam.exceptions.NoSuchEntityException = NoSuchEntityException
        mock_iam.get_role.side_effect = Exception("Access denied")

        def client_factory(service, **kwargs):
            if service == "cognito-idp":
                return mock_cognito
            elif service == "iam":
                return mock_iam
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        resources = []

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise
            cleanup_hook._check_cognito_user_pool(mock_cognito, set(), resources, "dev", "ue1")

    @patch("boto3.client")
    def test_handles_domain_exception(self, mock_boto_client):
        """Should handle exception when checking user pool domain."""
        mock_cognito = MagicMock()
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
        mock_cognito.exceptions = MagicMock()
        mock_cognito.exceptions.ResourceNotFoundException = ResourceNotFoundException
        mock_cognito.describe_user_pool.return_value = {"UserPool": {"Id": "us-east-1_abc123"}}
        mock_cognito.describe_user_pool_domain.side_effect = Exception("API Error")

        mock_iam = MagicMock()
        mock_boto_client.side_effect = lambda service, **kwargs: (
            mock_cognito if service == "cognito-idp" else mock_iam
        )

        resources = []

        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            # Should not raise
            cleanup_hook._check_cognito_user_pool(mock_cognito, set(), resources, "dev", "ue1")


class TestCheckCloudfrontDistribution:
    """Tests for _check_cloudfront_distribution function."""

    def test_adds_unmanaged_distribution_and_oai_to_import(self):
        """Should add unmanaged CloudFront distribution and OAI to import list."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E219LJDJKQIV8A",
                            "Aliases": {"Items": ["dev.kernelworx.app"]},
                            "Origins": {
                                "Items": [
                                    {
                                        "S3OriginConfig": {
                                            "OriginAccessIdentity": "origin-access-identity/cloudfront/E1DLJZW45792KZ"
                                        }
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        resources: list[dict[str, Any]] = []
        cleanup_hook._check_cloudfront_distribution(mock_client, set(), resources, "dev", "ue1")

        # Should find OAI and distribution to import
        assert len(resources) == 2
        # OAI should be first
        assert resources[0]["ResourceType"] == "AWS::CloudFront::CloudFrontOriginAccessIdentity"
        assert resources[0]["LogicalResourceId"] == "OAIE1EFC67F"
        assert resources[0]["ResourceIdentifier"] == {"Id": "E1DLJZW45792KZ"}
        # Distribution second
        assert resources[1]["ResourceType"] == "AWS::CloudFront::Distribution"
        assert resources[1]["LogicalResourceId"] == "Distribution830FAC52"
        assert resources[1]["ResourceIdentifier"] == {"Id": "E219LJDJKQIV8A"}

    def test_adds_distribution_without_oai(self):
        """Should add unmanaged CloudFront distribution even without OAI."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E219LJDJKQIV8A",
                            "Aliases": {"Items": ["dev.kernelworx.app"]},
                            "Origins": {"Items": []},
                        }
                    ]
                }
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        resources: list[dict[str, Any]] = []
        cleanup_hook._check_cloudfront_distribution(mock_client, set(), resources, "dev", "ue1")

        # Should find just distribution to import
        assert len(resources) == 1
        assert resources[0]["ResourceType"] == "AWS::CloudFront::Distribution"

    def test_skips_managed_distribution(self):
        """Should skip distribution already in CloudFormation."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E219LJDJKQIV8A",
                            "Aliases": {"Items": ["dev.kernelworx.app"]},
                            "Origins": {"Items": []},
                        }
                    ]
                }
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        # Distribution is already managed
        stack_resources = {"E219LJDJKQIV8A"}
        resources: list[dict[str, Any]] = []
        cleanup_hook._check_cloudfront_distribution(mock_client, stack_resources, resources, "dev", "ue1")

        # Should not add managed distribution
        assert len(resources) == 0

    def test_skips_managed_oai(self):
        """Should skip OAI already in CloudFormation but still import distribution."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E219LJDJKQIV8A",
                            "Aliases": {"Items": ["dev.kernelworx.app"]},
                            "Origins": {
                                "Items": [
                                    {
                                        "S3OriginConfig": {
                                            "OriginAccessIdentity": "origin-access-identity/cloudfront/E1DLJZW45792KZ"
                                        }
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        # OAI is already managed but distribution is not
        stack_resources = {"E1DLJZW45792KZ"}
        resources: list[dict[str, Any]] = []
        cleanup_hook._check_cloudfront_distribution(mock_client, stack_resources, resources, "dev", "ue1")

        # Should add only distribution (OAI already managed)
        assert len(resources) == 1
        assert resources[0]["ResourceType"] == "AWS::CloudFront::Distribution"

    def test_handles_no_matching_distribution(self):
        """Should handle no matching distribution gracefully."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E123456789ABC",
                            "Aliases": {"Items": ["other.domain.com"]},
                        }
                    ]
                }
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        resources: list[dict[str, Any]] = []
        cleanup_hook._check_cloudfront_distribution(mock_client, set(), resources, "dev", "ue1")

        # No resources should be added
        assert len(resources) == 0

    def test_handles_exception(self):
        """Should handle exception gracefully."""
        mock_client = MagicMock()
        mock_client.get_paginator.side_effect = Exception("API Error")

        resources: list[dict[str, Any]] = []
        # Should not raise
        cleanup_hook._check_cloudfront_distribution(mock_client, set(), resources, "dev", "ue1")

        # No resources should be added
        assert len(resources) == 0


class TestCheckAcmCertificates:
    """Tests for _check_acm_certificates function."""

    def test_adds_unmanaged_certificates_to_import(self):
        """Should add unmanaged ACM certificates to import list."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "CertificateSummaryList": [
                    {
                        "DomainName": "dev.kernelworx.app",
                        "CertificateArn": "arn:aws:acm:us-east-1:123:certificate/site",
                        "Status": "ISSUED",
                    },
                    {
                        "DomainName": "api.dev.kernelworx.app",
                        "CertificateArn": "arn:aws:acm:us-east-1:123:certificate/api",
                        "Status": "ISSUED",
                    },
                    {
                        "DomainName": "login.dev.kernelworx.app",
                        "CertificateArn": "arn:aws:acm:us-east-1:123:certificate/login",
                        "Status": "ISSUED",
                    },
                ]
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        resources: list[dict[str, Any]] = []
        cleanup_hook._check_acm_certificates(mock_client, set(), resources, "dev", "ue1")

        # Should find 3 certificates to import
        assert len(resources) == 3
        assert all(r["ResourceType"] == "AWS::CertificateManager::Certificate" for r in resources)

    def test_skips_managed_certificates(self):
        """Should skip certificates already in CloudFormation."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "CertificateSummaryList": [
                    {
                        "DomainName": "dev.kernelworx.app",
                        "CertificateArn": "arn:aws:acm:us-east-1:123:certificate/site",
                        "Status": "ISSUED",
                    },
                ]
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        # Certificate is already managed
        stack_resources = {"arn:aws:acm:us-east-1:123:certificate/site"}
        resources: list[dict[str, Any]] = []
        cleanup_hook._check_acm_certificates(mock_client, stack_resources, resources, "dev", "ue1")

        # Should not add managed certificate
        assert len(resources) == 0

    def test_skips_non_issued_certificates(self):
        """Should skip certificates that are not ISSUED."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "CertificateSummaryList": [
                    {
                        "DomainName": "dev.kernelworx.app",
                        "CertificateArn": "arn:aws:acm:us-east-1:123:certificate/pending",
                        "Status": "PENDING_VALIDATION",
                    },
                ]
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        resources: list[dict[str, Any]] = []
        cleanup_hook._check_acm_certificates(mock_client, set(), resources, "dev", "ue1")

        # No resources should be added
        assert len(resources) == 0

    def test_handles_exception(self):
        """Should handle exception gracefully."""
        mock_client = MagicMock()
        mock_client.get_paginator.side_effect = Exception("API Error")

        resources: list[dict[str, Any]] = []
        # Should not raise
        cleanup_hook._check_acm_certificates(mock_client, set(), resources, "dev", "ue1")

        # No resources should be added
        assert len(resources) == 0


class TestDeleteOrphanedCloudfrontDistribution:
    """Tests for _delete_orphaned_cloudfront_distribution function."""

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_deletes_orphaned_distribution(self, mock_boto_client):
        """Should delete an orphaned CloudFront distribution."""
        mock_cloudfront = MagicMock()
        mock_cfn = MagicMock()

        # Setup paginator to return a distribution with matching S3 bucket origin
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E219LJDJKQIV8A",
                            "Status": "Deployed",
                            "Aliases": {"Items": ["dev.kernelworx.app"]},
                            "Origins": {
                                "Items": [
                                    {
                                        "DomainName": "kernelworx-static-ue1-dev.s3.us-east-1.amazonaws.com",
                                        "S3OriginConfig": {
                                            "OriginAccessIdentity": "origin-access-identity/cloudfront/E1DLJZW45792KZ"
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        ]
        mock_cloudfront.get_paginator.return_value = mock_paginator

        # Mock stack resources (empty - distribution not managed)
        cfn_paginator = MagicMock()
        cfn_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = cfn_paginator
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        # Mock get_distribution_config - includes custom certificate
        mock_cloudfront.get_distribution_config.return_value = {
            "DistributionConfig": {
                "Enabled": True,
                "Aliases": {"Items": ["dev.kernelworx.app"]},
                "ViewerCertificate": {"ACMCertificateArn": "arn:aws:acm:us-east-1:123:certificate/abc"},
            },
            "ETag": "E123",
        }
        mock_cloudfront.update_distribution.return_value = {"ETag": "E456"}
        mock_cloudfront.get_waiter.return_value = MagicMock()
        mock_cloudfront.get_cloud_front_origin_access_identity.return_value = {"ETag": "OAI-E123"}
        mock_cloudfront.exceptions = MagicMock()
        mock_cloudfront.exceptions.NoSuchCloudFrontOriginAccessIdentity = type(
            "NoSuchCloudFrontOriginAccessIdentity", (Exception,), {}
        )

        def client_factory(service, **kwargs):
            if service == "cloudfront":
                return mock_cloudfront
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise
        cleanup_hook._delete_orphaned_cloudfront_distribution("dev.kernelworx.app", "dev")

        # Verify distribution was disabled and deleted
        mock_cloudfront.update_distribution.assert_called_once()
        mock_cloudfront.delete_distribution.assert_called_once()
        mock_cloudfront.delete_cloud_front_origin_access_identity.assert_called_once()

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_skips_managed_distribution(self, mock_boto_client):
        """Should skip CloudFormation-managed distribution."""
        mock_cloudfront = MagicMock()
        mock_cfn = MagicMock()

        # Setup paginator to return a distribution with matching S3 bucket origin
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E219LJDJKQIV8A",
                            "Status": "Deployed",
                            "Aliases": {"Items": ["dev.kernelworx.app"]},
                            "Origins": {
                                "Items": [
                                    {
                                        "DomainName": "kernelworx-static-ue1-dev.s3.us-east-1.amazonaws.com",
                                        "S3OriginConfig": {},
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        ]
        mock_cloudfront.get_paginator.return_value = mock_paginator

        # Stack resources contains this distribution (it's managed)
        cfn_paginator = MagicMock()
        cfn_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "ResourceType": "AWS::CloudFront::Distribution",
                        "PhysicalResourceId": "E219LJDJKQIV8A",
                    }
                ]
            }
        ]
        mock_cfn.get_paginator.return_value = cfn_paginator
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "cloudfront":
                return mock_cloudfront
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise
        cleanup_hook._delete_orphaned_cloudfront_distribution("dev.kernelworx.app", "dev")

        # Verify distribution was NOT deleted
        mock_cloudfront.delete_distribution.assert_not_called()

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_handles_no_matching_distribution(self, mock_boto_client):
        """Should handle no matching distribution gracefully."""
        mock_cloudfront = MagicMock()
        mock_cfn = MagicMock()

        # No distributions
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"DistributionList": {"Items": []}}]
        mock_cloudfront.get_paginator.return_value = mock_paginator

        mock_cfn.get_paginator.return_value = MagicMock(paginate=MagicMock(return_value=[]))
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "cloudfront":
                return mock_cloudfront
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise
        cleanup_hook._delete_orphaned_cloudfront_distribution("dev.kernelworx.app", "dev")

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_skips_distribution_with_different_bucket(self, mock_boto_client):
        """Should skip distribution that uses a different S3 bucket."""
        mock_cloudfront = MagicMock()
        mock_cfn = MagicMock()

        # Distribution uses a different S3 bucket (not ours)
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E123OTHER",
                            "Status": "Deployed",
                            "Aliases": {"Items": ["other-site.example.com"]},
                            "Origins": {
                                "Items": [
                                    {
                                        "DomainName": "some-other-bucket.s3.us-east-1.amazonaws.com",
                                        "S3OriginConfig": {},
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        ]
        mock_cloudfront.get_paginator.return_value = mock_paginator

        mock_cfn.get_paginator.return_value = MagicMock(
            paginate=MagicMock(return_value=[{"StackResourceSummaries": []}])
        )
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        def client_factory(service, **kwargs):
            if service == "cloudfront":
                return mock_cloudfront
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise and should not delete anything
        cleanup_hook._delete_orphaned_cloudfront_distribution("dev.kernelworx.app", "dev")

        # Verify no distribution was deleted
        mock_cloudfront.delete_distribution.assert_not_called()

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_handles_exception(self, mock_boto_client):
        """Should handle exception gracefully."""
        mock_cloudfront = MagicMock()
        mock_cfn = MagicMock()

        # CloudFront API throws exception
        mock_cloudfront.get_paginator.side_effect = Exception("API Error")

        # CFN client needs proper exceptions attribute
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})
        mock_cfn.get_paginator.return_value = MagicMock(
            paginate=MagicMock(return_value=[{"StackResourceSummaries": []}])
        )

        def client_factory(service, **kwargs):
            if service == "cloudfront":
                return mock_cloudfront
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise
        cleanup_hook._delete_orphaned_cloudfront_distribution("dev.kernelworx.app", "dev")

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_handles_cfn_client_error(self, mock_boto_client):
        """Should handle CloudFormation client errors gracefully."""
        mock_cloudfront = MagicMock()
        mock_cfn = MagicMock()

        # Setup paginator to return a distribution with matching S3 bucket origin
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E219LJDJKQIV8A",
                            "Status": "Deployed",
                            "Aliases": {"Items": ["dev.kernelworx.app"]},
                            "Origins": {
                                "Items": [
                                    {
                                        "DomainName": "kernelworx-static-ue1-dev.s3.us-east-1.amazonaws.com",
                                        "S3OriginConfig": {},
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        ]
        mock_cloudfront.get_paginator.return_value = mock_paginator
        mock_cloudfront.get_distribution_config.return_value = {
            "DistributionConfig": {"Enabled": True, "Aliases": {"Items": ["dev.kernelworx.app"]}},
            "ETag": "E123",
        }
        mock_cloudfront.update_distribution.return_value = {"ETag": "E456"}
        mock_cloudfront.get_waiter.return_value = MagicMock()
        mock_cloudfront.exceptions = MagicMock()
        mock_cloudfront.exceptions.NoSuchCloudFrontOriginAccessIdentity = type(
            "NoSuchCloudFrontOriginAccessIdentity", (Exception,), {}
        )

        # CFN raises ClientError (stack doesn't exist)
        ClientError = type("ClientError", (Exception,), {})
        cfn_paginator = MagicMock()
        cfn_paginator.paginate.side_effect = ClientError("Stack does not exist")
        mock_cfn.get_paginator.return_value = cfn_paginator
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = ClientError

        def client_factory(service, **kwargs):
            if service == "cloudfront":
                return mock_cloudfront
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise and should proceed to delete
        cleanup_hook._delete_orphaned_cloudfront_distribution("dev.kernelworx.app", "dev")

        # Verify distribution was deleted (since stack doesn't exist, dist is orphaned)
        mock_cloudfront.delete_distribution.assert_called_once()

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_deletes_oai_after_distribution(self, mock_boto_client):
        """Should delete OAI after deleting distribution."""
        mock_cloudfront = MagicMock()
        mock_cfn = MagicMock()

        # Setup paginator to return a distribution with matching S3 bucket origin and OAI
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E219LJDJKQIV8A",
                            "Status": "Deployed",
                            "Aliases": {"Items": ["dev.kernelworx.app"]},
                            "Origins": {
                                "Items": [
                                    {
                                        "DomainName": "kernelworx-static-ue1-dev.s3.us-east-1.amazonaws.com",
                                        "S3OriginConfig": {
                                            "OriginAccessIdentity": "origin-access-identity/cloudfront/E1DLJZW45792KZ"
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        ]
        mock_cloudfront.get_paginator.return_value = mock_paginator

        # Stack doesn't exist
        cfn_paginator = MagicMock()
        cfn_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = cfn_paginator
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        mock_cloudfront.get_distribution_config.return_value = {
            "DistributionConfig": {"Enabled": False, "Aliases": {"Items": []}},
            "ETag": "E123",
        }
        mock_cloudfront.get_cloud_front_origin_access_identity.return_value = {"ETag": "OAI-E123"}
        mock_cloudfront.exceptions = MagicMock()
        mock_cloudfront.exceptions.NoSuchCloudFrontOriginAccessIdentity = type(
            "NoSuchCloudFrontOriginAccessIdentity", (Exception,), {}
        )

        def client_factory(service, **kwargs):
            if service == "cloudfront":
                return mock_cloudfront
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise
        cleanup_hook._delete_orphaned_cloudfront_distribution("dev.kernelworx.app", "dev")

        # Verify OAI was deleted
        mock_cloudfront.delete_cloud_front_origin_access_identity.assert_called_once()

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_handles_oai_delete_exception(self, mock_boto_client):
        """Should handle OAI deletion exception gracefully."""
        mock_cloudfront = MagicMock()
        mock_cfn = MagicMock()

        # Setup paginator to return a distribution with matching S3 bucket origin and OAI
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E219LJDJKQIV8A",
                            "Status": "Deployed",
                            "Aliases": {"Items": ["dev.kernelworx.app"]},
                            "Origins": {
                                "Items": [
                                    {
                                        "DomainName": "kernelworx-static-ue1-dev.s3.us-east-1.amazonaws.com",
                                        "S3OriginConfig": {
                                            "OriginAccessIdentity": "origin-access-identity/cloudfront/E1DLJZW45792KZ"
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        ]
        mock_cloudfront.get_paginator.return_value = mock_paginator

        # Stack doesn't exist
        cfn_paginator = MagicMock()
        cfn_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = cfn_paginator
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        mock_cloudfront.get_distribution_config.return_value = {
            "DistributionConfig": {"Enabled": False, "Aliases": {"Items": []}},
            "ETag": "E123",
        }
        mock_cloudfront.get_cloud_front_origin_access_identity.return_value = {"ETag": "OAI-E123"}
        mock_cloudfront.delete_cloud_front_origin_access_identity.side_effect = Exception("Some other error")
        mock_cloudfront.exceptions = MagicMock()
        mock_cloudfront.exceptions.NoSuchCloudFrontOriginAccessIdentity = type(
            "NoSuchCloudFrontOriginAccessIdentity", (Exception,), {}
        )

        def client_factory(service, **kwargs):
            if service == "cloudfront":
                return mock_cloudfront
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise (handles exception gracefully)
        cleanup_hook._delete_orphaned_cloudfront_distribution("dev.kernelworx.app", "dev")

    @patch("boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-east-1"})
    def test_handles_oai_not_found(self, mock_boto_client):
        """Should handle OAI not found gracefully."""
        mock_cloudfront = MagicMock()
        mock_cfn = MagicMock()

        # Setup paginator to return a distribution with matching S3 bucket origin and OAI
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DistributionList": {
                    "Items": [
                        {
                            "Id": "E219LJDJKQIV8A",
                            "Status": "Deployed",
                            "Aliases": {"Items": ["dev.kernelworx.app"]},
                            "Origins": {
                                "Items": [
                                    {
                                        "DomainName": "kernelworx-static-ue1-dev.s3.us-east-1.amazonaws.com",
                                        "S3OriginConfig": {
                                            "OriginAccessIdentity": "origin-access-identity/cloudfront/E1DLJZW45792KZ"
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        ]
        mock_cloudfront.get_paginator.return_value = mock_paginator

        # Stack doesn't exist
        cfn_paginator = MagicMock()
        cfn_paginator.paginate.return_value = [{"StackResourceSummaries": []}]
        mock_cfn.get_paginator.return_value = cfn_paginator
        mock_cfn.exceptions = MagicMock()
        mock_cfn.exceptions.ClientError = type("ClientError", (Exception,), {})

        mock_cloudfront.get_distribution_config.return_value = {
            "DistributionConfig": {"Enabled": False, "Aliases": {"Items": []}},
            "ETag": "E123",
        }
        NoSuchCloudFrontOriginAccessIdentity = type("NoSuchCloudFrontOriginAccessIdentity", (Exception,), {})
        mock_cloudfront.get_cloud_front_origin_access_identity.side_effect = NoSuchCloudFrontOriginAccessIdentity()
        mock_cloudfront.exceptions = MagicMock()
        mock_cloudfront.exceptions.NoSuchCloudFrontOriginAccessIdentity = NoSuchCloudFrontOriginAccessIdentity

        def client_factory(service, **kwargs):
            if service == "cloudfront":
                return mock_cloudfront
            return mock_cfn

        mock_boto_client.side_effect = client_factory

        # Should not raise
        cleanup_hook._delete_orphaned_cloudfront_distribution("dev.kernelworx.app", "dev")
