"""Resolvers must only read input fields the GraphQL schema declares (#520).

#520: `CreateSellerProfileInput` and `UpdateSellerProfileInput` declared no
`unitType`, so the `input.unitType` reads in
`tofu/application/appsync/js-resolvers/create_seller_profile_resolver.js` and
`update_profile_fn.js` were always `undefined` and their whitelists could never
fire. GraphQL rejects an input object literal that carries an undeclared field,
so those branches were dead code that a unit test happily exercised.

This module is the generalized guard: for every Query/Mutation field whose
argument is an input object, the resolvers and pipeline functions that serve it
may only read `input.<field>` names that the corresponding input type declares.
A resolver validating a field the schema does not expose is a silent control
gap and now fails CI instead of shipping.

The schema and the OpenTofu configuration are parsed into a semantic model (via
python-hcl2, the pattern established by test_edge_security.py and
test_appsync_pipeline_functions.py). A pipeline function shared by several
fields is checked against the union of those fields' input types, since the same
code legitimately serves each of them.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_edge_security import TF_APP, load_hcl, resources

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "tofu" / "application" / "schema" / "schema.graphql"
APPSYNC_DIR = TF_APP / "modules" / "appsync"
JS_RESOLVERS_DIR = TF_APP / "appsync" / "js-resolvers"

_RESOLVER_FILES = ("resolvers_mutations.tf", "resolvers_queries.tf")

# Reads of an undeclared input field that are deliberate rather than drift.
# Each entry must still be exercised (asserted by
# test_undeclared_read_allowlist_is_still_needed), so a fixed case cannot leave
# a stale exemption behind.
UNDECLARED_READ_ALLOWLIST: dict[str, dict[str, str]] = {
    "update_order_fn.js": {
        "totalAmount": (
            "a negative guard: the client cannot set the order total directly, so the "
            "resolver rejects it if it ever appears alongside lineItems"
        )
    },
}


def _input_type_fields() -> dict[str, set[str]]:
    """Map every `input X { ... }` in the schema to its declared field names."""
    source = SCHEMA.read_text()
    fields: dict[str, set[str]] = {}
    for match in re.finditer(r"input\s+(\w+)\s*\{([^}]*)\}", source, re.S):
        fields[match.group(1)] = set(re.findall(r"^\s{2}(\w+)\s*:", match.group(2), re.M))
    return fields


def _fields_with_input_argument() -> dict[str, str]:
    """Map each Query/Mutation field taking `input: <Input>!` to its input type."""
    source = SCHEMA.read_text()
    mapping: dict[str, str] = {}
    for match in re.finditer(r"\n  (\w+)\((?:[^)]|\n)*?input:\s*(\w+)!", source):
        mapping.setdefault(match.group(1), match.group(2))
    return mapping


def _js_file(code) -> str | None:
    """Extract the resolver file name from `file("...js")` / `templatefile(...)`."""
    if not isinstance(code, str):
        return None
    tokens = re.findall(r"([\w./-]+\.js)", code)
    return tokens[-1].rsplit("/", 1)[-1] if tokens else None


def _function_code_files() -> dict[str, str]:
    """Map every aws_appsync_function label to its resolver file name."""
    files: dict[str, str] = {}
    for path in sorted(APPSYNC_DIR.glob("*.tf")):
        for label, attrs in resources(load_hcl(path), "aws_appsync_function"):
            name = _js_file(attrs.get("code"))
            if name:
                files[label] = name
    return files


def _field_code_files() -> dict[str, set[str]]:
    """Map each resolver's GraphQL field to its own code file plus its functions'."""
    functions = _function_code_files()
    files_by_field: dict[str, set[str]] = {}
    for filename in _RESOLVER_FILES:
        path = APPSYNC_DIR / filename
        if not path.exists():
            continue
        for _label, attrs in resources(load_hcl(path), "aws_appsync_resolver"):
            files: set[str] = set()
            own = _js_file(attrs.get("code"))
            if own:
                files.add(own)
            for config in attrs.get("pipeline_config", []) or []:
                for ref in config.get("functions", []) or []:
                    match = re.search(r"aws_appsync_function\.(\w+)\.", str(ref))
                    if match and match.group(1) in functions:
                        files.add(functions[match.group(1)])
            files_by_field[attrs.get("field")] = files
    return files_by_field


def _input_type_scope() -> dict[str, set[str]]:
    """Map each resolver file to the input types whose fields it may read."""
    input_fields = _input_type_fields()
    field_inputs = _fields_with_input_argument()
    scope: dict[str, set[str]] = {}
    for field, input_type in field_inputs.items():
        for name in _field_code_files().get(field, set()):
            scope.setdefault(name, set()).add(input_type)
    return {name: {i for i in types if i in input_fields} for name, types in scope.items()}


def _undeclared_reads() -> list[str]:
    """Return one message per resolver read of a field its input type omits."""
    input_fields = _input_type_fields()
    violations: list[str] = []
    for name, input_types in sorted(_input_type_scope().items()):
        path = JS_RESOLVERS_DIR / name
        assert path.exists(), f"{name} is wired into a resolver but does not exist"
        allowed: set[str] = set()
        for input_type in input_types:
            allowed |= input_fields[input_type]
        allowlist = UNDECLARED_READ_ALLOWLIST.get(name, {})
        scope = input_types.pop() if len(input_types) == 1 else " or ".join(sorted(input_types))
        for read in sorted(set(re.findall(r"\binput\.(\w+)", path.read_text()))):
            if read in allowed or read in allowlist:
                continue
            violations.append(f"{name} reads input.{read}, which {scope} does not declare")
    return violations


def test_resolvers_only_read_input_fields_the_schema_declares() -> None:
    assert not _undeclared_reads(), (
        "resolvers read input fields the schema does not declare, so the branch "
        "is unreachable (GraphQL rejects undeclared input fields):\n" + "\n".join(_undeclared_reads())
    )


def test_undeclared_read_allowlist_is_still_needed() -> None:
    """Each allowlisted read must still exist, and still be undeclared."""
    for name, reads in UNDECLARED_READ_ALLOWLIST.items():
        source = (JS_RESOLVERS_DIR / name).read_text()
        allowed: set[str] = set()
        for input_type in _input_type_scope()[name]:
            allowed |= _input_type_fields()[input_type]
        for read, reason in reads.items():
            assert f"input.{read}" in source, f"{name} no longer reads input.{read}"
            assert read not in allowed, f"{name} now declares input.{read}; drop the exemption"
            assert reason, f"exemption for {name} input.{read} needs a reason"


def test_profile_inputs_declare_their_unit_fields() -> None:
    """#520: the profile write paths validate unit fields, so the schema must accept them."""
    fields = _input_type_fields()
    for name in ("CreateSellerProfileInput", "UpdateSellerProfileInput"):
        missing = {"unitType", "unitNumber"} - fields[name]
        assert not missing, f"{name} does not declare {sorted(missing)}"
