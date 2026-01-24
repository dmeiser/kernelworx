import boto3

from cdk.cdk.cleanup_hook import (
    _find_best_matching_zone,
    _get_region_abbrev,
    _is_unmanaged_certificate,
    _is_validation_record,
    _matches_domain,
)

# =============================================================================
# Test fixtures and mocks
# =============================================================================


class DummyPaginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, StackName=None):
        for p in self.pages:
            yield p


class DummyCfnClient:
    def __init__(self, cert_arn):
        self.cert_arn = cert_arn

    def get_paginator(self, name):
        if name == "list_stack_resources":
            return DummyPaginator(
                [
                    {
                        "StackResourceSummaries": [
                            {
                                "ResourceType": "AWS::CertificateManager::Certificate",
                                "PhysicalResourceId": self.cert_arn,
                            }
                        ]
                    }
                ]
            )
        raise NotImplementedError


class DummyAcmClientTags:
    def __init__(self, tags):
        self.tags = tags

    def describe_certificate(self, CertificateArn=None):
        return {"Certificate": {"Tags": self.tags}}


class DummyAcmClientError:
    def describe_certificate(self, CertificateArn=None):
        raise Exception("describe failure")


def test_is_unmanaged_certificate_with_kernelworx_tags(monkeypatch):
    cert_arn = "arn:aws:acm:us-east-1:123:certificate/abc"

    def fake_client(service_name, region_name=None):
        if service_name == "acm":
            return DummyAcmClientTags(
                [{"Key": "Application", "Value": "kernelworx"}, {"Key": "Environment", "Value": "dev"}]
            )
        if service_name == "cloudformation":
            return DummyCfnClient(cert_arn)
        raise RuntimeError("unexpected client")

    monkeypatch.setattr(boto3, "client", fake_client)

    assert _is_unmanaged_certificate(cert_arn, environment_name="dev") is False


def test_is_unmanaged_certificate_present_in_stack(monkeypatch):
    cert_arn = "arn:aws:acm:us-east-1:123:certificate/def"

    def fake_client(service_name, region_name=None):
        if service_name == "acm":
            # no tags
            return DummyAcmClientTags([])
        if service_name == "cloudformation":
            return DummyCfnClient(cert_arn)
        raise RuntimeError("unexpected client")

    monkeypatch.setattr(boto3, "client", fake_client)

    assert _is_unmanaged_certificate(cert_arn, environment_name="dev") is False


def test_is_unmanaged_certificate_describe_failure(monkeypatch):
    cert_arn = "arn:aws:acm:us-east-1:123:certificate/ghi"

    def fake_client(service_name, region_name=None):
        if service_name == "acm":
            return DummyAcmClientError()
        if service_name == "cloudformation":
            return DummyCfnClient(cert_arn)
        raise RuntimeError("unexpected client")

    monkeypatch.setattr(boto3, "client", fake_client)

    # When describe fails, function should be conservative and treat as managed => False
    assert _is_unmanaged_certificate(cert_arn, environment_name="dev") is False


# =============================================================================
# Tests for _find_best_matching_zone
# =============================================================================


class TestFindBestMatchingZone:
    """Tests for hosted zone matching logic."""

    def test_exact_match(self) -> None:
        """Test exact domain match."""
        zones = [
            {"Id": "/hostedzone/Z1", "Name": "kernelworx.app."},
            {"Id": "/hostedzone/Z2", "Name": "example.com."},
        ]
        result = _find_best_matching_zone(zones, "kernelworx.app")
        assert result is not None
        assert result["Id"] == "/hostedzone/Z1"

    def test_subdomain_match(self) -> None:
        """Test subdomain matches parent zone."""
        zones = [
            {"Id": "/hostedzone/Z1", "Name": "kernelworx.app."},
        ]
        result = _find_best_matching_zone(zones, "api.dev.kernelworx.app")
        assert result is not None
        assert result["Id"] == "/hostedzone/Z1"

    def test_longest_suffix_wins(self) -> None:
        """Test that most specific zone wins."""
        zones = [
            {"Id": "/hostedzone/Z1", "Name": "kernelworx.app."},
            {"Id": "/hostedzone/Z2", "Name": "dev.kernelworx.app."},
        ]
        result = _find_best_matching_zone(zones, "api.dev.kernelworx.app")
        assert result is not None
        assert result["Id"] == "/hostedzone/Z2"  # More specific

    def test_no_match(self) -> None:
        """Test returns None when no zone matches."""
        zones = [
            {"Id": "/hostedzone/Z1", "Name": "other.com."},
        ]
        result = _find_best_matching_zone(zones, "api.kernelworx.app")
        assert result is None

    def test_empty_zones(self) -> None:
        """Test empty zones list returns None."""
        result = _find_best_matching_zone([], "api.kernelworx.app")
        assert result is None


# =============================================================================
# Tests for _get_region_abbrev
# =============================================================================


class TestGetRegionAbbrev:
    """Tests for region abbreviation mapping."""

    def test_us_east_1(self) -> None:
        """Test US East 1 abbreviation."""
        assert _get_region_abbrev("us-east-1") == "ue1"

    def test_us_east_2(self) -> None:
        """Test US East 2 abbreviation."""
        assert _get_region_abbrev("us-east-2") == "ue2"

    def test_us_west_1(self) -> None:
        """Test US West 1 abbreviation."""
        assert _get_region_abbrev("us-west-1") == "uw1"

    def test_us_west_2(self) -> None:
        """Test US West 2 abbreviation."""
        assert _get_region_abbrev("us-west-2") == "uw2"

    def test_unknown_region_uses_first_three_chars(self) -> None:
        """Test unknown region returns first 3 characters."""
        assert _get_region_abbrev("eu-west-1") == "eu-"
        assert _get_region_abbrev("ap-southeast-1") == "ap-"


# =============================================================================
# Tests for _is_validation_record
# =============================================================================


class TestIsValidationRecord:
    """Tests for ACM validation record detection."""

    def test_acme_challenge_record(self) -> None:
        """Test _acme-challenge records are detected."""
        record = {"Name": "_acme-challenge.api.kernelworx.app.", "Type": "CNAME"}
        assert _is_validation_record(record) is True

    def test_validation_record(self) -> None:
        """Test _validation records are detected."""
        record = {"Name": "_validation.api.kernelworx.app.", "Type": "CNAME"}
        assert _is_validation_record(record) is True

    def test_normal_record(self) -> None:
        """Test normal records are not flagged."""
        record = {"Name": "api.kernelworx.app.", "Type": "A"}
        assert _is_validation_record(record) is False

    def test_case_insensitive(self) -> None:
        """Test detection is case-insensitive."""
        record = {"Name": "_ACME-CHALLENGE.api.kernelworx.app.", "Type": "CNAME"}
        assert _is_validation_record(record) is True

    def test_empty_name(self) -> None:
        """Test empty name is handled."""
        record = {"Type": "CNAME"}
        assert _is_validation_record(record) is False


# =============================================================================
# Tests for _matches_domain
# =============================================================================


class TestMatchesDomain:
    """Tests for Route53 record domain matching."""

    def test_exact_match(self) -> None:
        """Test exact match with trailing dot."""
        assert _matches_domain("api.kernelworx.app.", "api.kernelworx.app") is True

    def test_subdomain_of_domain(self) -> None:
        """Test record ending with domain."""
        assert _matches_domain("www.api.kernelworx.app.", "api.kernelworx.app") is True

    def test_case_insensitive(self) -> None:
        """Test matching is case-insensitive."""
        assert _matches_domain("API.KERNELWORX.APP.", "api.kernelworx.app") is True

    def test_no_match(self) -> None:
        """Test non-matching domains."""
        assert _matches_domain("other.example.com.", "api.kernelworx.app") is False

    def test_short_record_name_no_false_positive(self) -> None:
        """Test that short record names don't incorrectly match."""
        # "api." split on "." gives "api", and "api.kernelworx.app" doesn't END with "api"
        assert _matches_domain("api.", "api.kernelworx.app") is False
