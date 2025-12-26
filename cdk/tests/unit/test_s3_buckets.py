"""Tests for the s3_buckets module."""

import pytest
from aws_cdk import App, Stack, assertions
from aws_cdk import aws_s3 as s3

from cdk.s3_buckets import create_s3_buckets


class TestCreateS3Buckets:
    """Tests for create_s3_buckets function."""

    @pytest.fixture
    def stack(self):
        """Create a test stack."""
        app = App()
        return Stack(app, "TestStack")

    @pytest.fixture
    def rn(self):
        """Create a resource naming function."""

        def _rn(name: str) -> str:
            return f"{name}-ue1-test"

        return _rn

    def test_returns_dict_with_both_buckets(self, stack, rn):
        """Should return a dict with both buckets."""
        result = create_s3_buckets(stack, rn)

        assert "static_assets_bucket" in result
        assert "exports_bucket" in result
        assert isinstance(result["static_assets_bucket"], s3.Bucket)
        assert isinstance(result["exports_bucket"], s3.Bucket)

    def test_static_assets_bucket_name(self, stack, rn):
        """Static assets bucket should have correct name in CloudFormation template."""
        create_s3_buckets(stack, rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::S3::Bucket", {"BucketName": "kernelworx-static-ue1-test"})

    def test_exports_bucket_name(self, stack, rn):
        """Exports bucket should have correct name in CloudFormation template."""
        create_s3_buckets(stack, rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::S3::Bucket", {"BucketName": "kernelworx-exports-ue1-test"})

    def test_different_resource_namer(self, stack):
        """Should work with different resource naming function."""

        def custom_rn(name: str) -> str:
            return f"{name}-custom-prod"

        create_s3_buckets(stack, custom_rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::S3::Bucket", {"BucketName": "kernelworx-static-custom-prod"})
        template.has_resource_properties("AWS::S3::Bucket", {"BucketName": "kernelworx-exports-custom-prod"})

    def test_returns_exactly_two_buckets(self, stack, rn):
        """Should return exactly 2 buckets."""
        result = create_s3_buckets(stack, rn)
        assert len(result) == 2

    def test_buckets_block_public_access(self, stack, rn):
        """Buckets should block public access."""
        create_s3_buckets(stack, rn)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                }
            },
        )
