"""Wiring contract for #337 decorator rollout on direct Lambda unit resolvers.

The `lambda_handler` decorator (src/utils/handlers.py) returns structured
`__isError` payloads instead of raising, so every resolver that invokes a
decorated handler must run JS code that detects the payload and calls
`util.error(...)` — otherwise the error dict leaks into the field result and
typed error codes never reach the client. The 10 direct Lambda UNIT resolvers
on decorator-wrapped handlers run `lambda_unit_resolver.js` for this. These
tests parse the OpenTofu configuration into a semantic model (via
python-hcl2) and assert the meaning of the wiring contract:

- Every UNIT resolver on a decorator-wrapped Lambda datasource carries
  lambda_unit_resolver.js and an APPSYNC_JS runtime, and none are converted
  to PIPELINE resolvers.
- The field set on those datasources is exactly the expected set (no
  resolver is left on the default VTL behavior, which cannot detect
  `__isError`).
- confirmPaymentMethodQRCodeUpload is NOT a unit resolver: since #330/#367 it
  is a PIPELINE whose confirm_qr_upload function invokes the decorated
  handler, so its `__isError` detection lives in confirm_qr_upload_fn.js
  (covered by the js-resolver tests).
"""

from __future__ import annotations

from pathlib import Path

import hcl2

REPO_ROOT = Path(__file__).resolve().parents[2]
APPSYNC_MODULE = REPO_ROOT / "tofu" / "application" / "modules" / "appsync"
RESOLVER_FILES = [
    APPSYNC_MODULE / "resolvers_mutations.tf",
    APPSYNC_MODULE / "resolvers_queries.tf",
    APPSYNC_MODULE / "resolvers_fields.tf",
]
UNIT_RESOLVER = "lambda_unit_resolver.js"

# Datasources backed by decorator-wrapped Lambda handlers that are invoked
# through direct UNIT resolvers (pipeline functions and field resolvers on
# these handlers have their own JS code with __isError detection).
EXPECTED_UNIT_FIELDS = {
    # listMyShares migrated to a JS pipeline resolver (#334) and no longer
    # invokes a Lambda; it is intentionally absent from this map.
    "aws_appsync_datasource.list_catalogs_in_use.name": {"listCatalogsInUse"},
    "aws_appsync_datasource.request_report.name": {"requestCampaignReport"},
    "aws_appsync_datasource.unit_reporting.name": {"getUnitReport"},
    "aws_appsync_datasource.list_unit_catalogs.name": {"listUnitCatalogs"},
    "aws_appsync_datasource.list_unit_campaign_catalogs.name": {"listUnitCampaignCatalogs"},
    "aws_appsync_datasource.delete_account.name": {"deleteMyAccount"},
    "aws_appsync_datasource.transfer_ownership.name": {"transferProfileOwnership"},
    "aws_appsync_datasource.request_qr_upload.name": {"requestPaymentMethodQRCodeUpload"},
    "aws_appsync_datasource.delete_qr_code.name": {"deletePaymentMethodQRCode"},
}


def test_confirm_upload_is_a_pipeline_not_a_unit_resolver():
    """#330/#367: confirmPaymentMethodQRCodeUpload invokes the decorated
    confirm-qr-upload handler through the confirm_qr_upload pipeline
    function (which detects __isError), not a direct unit resolver."""
    confirm = next(
        (attrs for _, attrs in _all_resolvers() if _norm(attrs["field"]) == "confirmPaymentMethodQRCodeUpload"),
        None,
    )
    assert confirm is not None, "confirmPaymentMethodQRCodeUpload resolver missing"
    assert _norm(confirm.get("kind", "")) == "PIPELINE"
    assert "data_source" not in confirm, "pipeline resolver must not bind a unit data_source"
    pipeline = confirm.get("pipeline_config", [{}])[0].get("functions", [])
    assert any("aws_appsync_function.confirm_qr_upload" in str(fn) for fn in pipeline), pipeline


def _norm(value):
    """Decode a python-hcl2 scalar: strip its quote wrapper and ${...} interpolation."""
    if isinstance(value, str):
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if value.startswith("${") and value.endswith("}"):
            value = value[2:-1]
    return value


def _all_resolvers():
    """Yield (name, attrs) for every aws_appsync_resolver in the module."""
    resolvers = []
    for path in RESOLVER_FILES:
        with path.open() as handle:
            parsed = hcl2.load(handle)
        for block in parsed["resource"]:
            for type_name, named in block.items():
                if _norm(type_name) != "aws_appsync_resolver":
                    continue
                for resolver_name, attrs in named.items():
                    resolvers.append((_norm(resolver_name), attrs))
    return resolvers


def _unit_resolvers():
    return [
        (name, attrs) for name, attrs in _all_resolvers() if _norm(attrs.get("data_source", "")) in EXPECTED_UNIT_FIELDS
    ]


def test_unit_resolver_fields_match_expected_per_datasource():
    for data_source, expected_fields in EXPECTED_UNIT_FIELDS.items():
        fields = {
            _norm(attrs["field"]) for _, attrs in _all_resolvers() if _norm(attrs.get("data_source", "")) == data_source
        }
        assert fields == expected_fields, f"{data_source}: {fields} != {expected_fields}"


def test_every_decorated_lambda_resolver_runs_unit_code_as_unit_resolver():
    unit = _unit_resolvers()
    assert len(unit) == sum(len(fields) for fields in EXPECTED_UNIT_FIELDS.values())
    for name, attrs in unit:
        code = str(attrs.get("code", ""))
        assert UNIT_RESOLVER in code, f"{name} missing {UNIT_RESOLVER}"
        runtimes = attrs.get("runtime") or []
        assert len(runtimes) == 1, f"{name} must declare exactly one runtime"
        assert _norm(runtimes[0].get("name", "")) == "APPSYNC_JS", f"{name} runtime"
        assert _norm(runtimes[0].get("runtime_version", "")) == "1.0.0", f"{name} runtime version"
        assert "kind" not in attrs, f"{name} must stay a UNIT resolver"
