import boto3

from cdk.cdk.cleanup_hook import _is_unmanaged_certificate


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
