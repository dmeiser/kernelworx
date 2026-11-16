"""Every deployed Lambda carries an env var for every table its handler reads.

The hole this pins (QA, ``dev`` at ``2f457c5e``, WORK-79): ``redeemUnitInvite``
answered EVERY unusable invite code — unknown, expired, revoked, consumed — with
``INTERNAL_ERROR`` instead of ``NOT_FOUND``, and the §6.6 redemption throttle
stopped counting. Nothing in the handler was wrong. ``_record_failed_redemption``
reads ``tables.public_order_throttles``, whose name comes from
``get_required_env("PUBLIC_ORDER_THROTTLES_TABLE_NAME")`` — and that variable was
set for no Lambda in any environment, so the accessor raised inside the request
and the generic decorator answered the error the caller saw.

Three links make a table reachable from a deployed handler, and the unit suite
cannot see any of them: the module must read ``var.table_names.<key>`` into the
function's environment, the environment must pass that key to the module, and the
execution role must grant it. ``conftest`` injects every table name into the test
process, so a missing link is invisible until a real request hits a real
deployment.

The expected set is not hand-written. It is every ``tables.<key>`` the handler
module and everything it can import asks the accessor for, so a helper that
starts reading a new table fails here — in the PR that adds it — rather than in
``dev``'s traffic. Triggers are covered too: they receive ``local.common_env`` and
nothing else.

``tests/unit/test_unit_tenant_wiring.py`` pins the Unit tenant's other links
(role grants, resolvers, the 19 SDL fields) against the derivation exported here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.unit.test_edge_security import REPO_ROOT, TF_APP, block, load_hcl

SRC = REPO_ROOT / "src"
LAMBDA_MODULE = TF_APP / "modules" / "lambda" / "main.tf"
ENVIRONMENTS = TF_APP / "environments"
ENVS = ("dev", "prod", "ephemeral")

_TABLE_REF = re.compile(r"var\.table_names\.([a-z_]+)")


def accessor_table_keys() -> set[str]:
    """Every table key ``TableAccessor`` can hand out (``src/utils/dynamodb.py``)."""
    tree = ast.parse((SRC / "utils" / "dynamodb.py").read_text())
    return {
        str(node.args[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_get_table"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }


def _import_targets(module: Path, node: ast.AST) -> list[Path]:
    """The ``src/`` files one import statement resolves to, in both shapes.

    Handlers import their helpers two ways: the flat ``from utils import x`` the
    Lambda uses at runtime, and the package-relative ``from ..utils import x`` the
    test tree uses — plus the ``import_from_utils("<module>", ...)`` loader in
    ``src/utils/import_fallback.py`` most handlers go through. A closure walk that
    understood only one shape would under-read the table set and silently narrow
    every pin below.
    """
    root = SRC.parent
    names: list[str] = []
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom):
        package = module.parent
        for _ in range(getattr(node, "level", 0) - 1):
            package = package.parent
        bases: list[str] = []
        if node.module:
            bases.append(node.module)
            if node.level:
                bases.append(f"{package.relative_to(root).as_posix().replace('/', '.')}.{node.module}")
        elif node.level:
            bases.append(package.relative_to(root).as_posix().replace("/", "."))
        names = bases + [f"{base}.{alias.name}" for base in bases for alias in node.names]
    found: list[Path] = []
    for name in names:
        stem = name.replace(".", "/")
        if not stem.startswith("src/"):
            stem = f"src/{stem}"
        for candidate in (root / f"{stem}.py", root / f"{stem}/__init__.py"):
            if candidate.exists():
                found.append(candidate)
    return found


def reached_modules(entry: Path) -> set[Path]:
    """Every ``src/`` module ``entry`` can reach, transitively."""
    reached: set[Path] = set()
    pending = [entry]
    while pending:
        module = pending.pop()
        if module in reached or not module.exists():
            continue
        reached.add(module)
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            pending.extend(_import_targets(module, node))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "import_from_utils"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                candidate = SRC / "utils" / f"{node.args[0].value}.py"
                if candidate.exists():
                    pending.append(candidate)
    return reached


def closure_table_keys(entry: Path) -> set[str]:
    """Every table key reachable from ``entry`` as ``tables.<key>``.

    Fails loudly if the closure names something the accessor does not define
    (private attributes aside): that would otherwise drop a table from the pins
    with no trace.
    """
    keys: set[str] = set()
    for module in reached_modules(entry):
        for node in ast.walk(ast.parse(module.read_text())):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "tables":
                if not node.attr.startswith("_"):
                    keys.add(node.attr)
    invented = keys - accessor_table_keys()
    assert not invented, f"tables.{sorted(invented)} is not a TableAccessor table"
    return keys


def _locals(name: str) -> dict:
    for local_block in load_hcl(LAMBDA_MODULE).get("locals", []):
        body = block(local_block)
        if name in body:
            return block(body[name])
    raise AssertionError(f"the lambda module declares no `{name}` locals map")


def deployed_workloads() -> dict[str, dict]:
    """Every Lambda the module deploys: the ``functions`` and ``trigger_functions`` maps."""
    return {**_locals("functions"), **_locals("trigger_functions")}


def common_env() -> dict[str, str]:
    """``local.common_env``: env var name -> its HCL expression."""
    return {str(key): str(value) for key, value in _locals("common_env").items()}


def workload_env(key: str) -> dict[str, str]:
    """The environment one deployed workload actually receives, as the resource builds it.

    ``aws_lambda_function`` resources merge ``local.common_env`` with the
    workload's ``extra_env``; Cognito triggers get ``local.common_env`` alone.
    """
    env = dict(common_env())
    env.update(_extra_env(key))
    return env


def _extra_env(key: str) -> dict[str, str]:
    """One workload's ``extra_env`` as name -> expression.

    Two shapes exist in the module: a literal map, and a whole-map reference —
    ``public-orders`` sets ``extra_env = local.ses_env``. A reference is followed
    when the target parses as a map; anything the parser hands back as an opaque
    expression contributes no names, which is correct for these pins (no
    ``<TABLE>_TABLE_NAME`` lives in ``local.ses_env``) and asserted, so a future
    opaque ``extra_env`` that does carry table names fails here instead of
    blinding the pin.
    """
    config = block(deployed_workloads()[key])
    if "extra_env" not in config:
        return {}
    raw = config["extra_env"]
    if isinstance(block(raw), dict):
        return {str(name): str(value) for name, value in block(raw).items()}
    text = str(raw)
    reference = re.fullmatch(r'"\$\{local\.([a-z_]+)\}"', text)
    if reference:
        target = block(_locals(reference.group(1)))
        if isinstance(target, dict):
            return {str(name): str(value) for name, value in target.items()}
    assert "TABLE_NAME" not in text, (
        f"{key}: extra_env = {text} is not statically enumerable and mentions table names — the pins would go blind"
    )
    return {}


def handler_entry(config: dict) -> Path:
    """``src/<package>/<module>.py`` for one workload's ``handler`` string.

    Every entry point is ``<package>.<module>.<function>``; anything else fails
    rather than skipping the workload.
    """
    parts = str(config["handler"]).strip('"').split(".")
    assert len(parts) == 3, f"unexpected handler shape: {config['handler']!r}"
    entry = SRC / parts[0] / f"{parts[1]}.py"
    assert entry.exists(), f"handler module {entry} does not exist"
    return entry


def environment_table_keys(env_name: str) -> set[str]:
    """The ``table_names`` keys one environment hands ``module.lambda``."""
    doc = load_hcl(ENVIRONMENTS / env_name / "main.tf")
    for entry in doc.get("module", []):
        for name, bodies in entry.items():
            if name == "lambda":
                return set(block(bodies)["table_names"])
    raise AssertionError(f"{env_name}: no module.lambda block")


@pytest.mark.parametrize("key", sorted(deployed_workloads()))
def test_workload_env_names_every_table_its_closure_reads(key: str) -> None:
    config = block(deployed_workloads()[key])
    wanted = closure_table_keys(handler_entry(config))
    env = workload_env(key)
    missing = sorted(table for table in wanted if f"{table.upper()}_TABLE_NAME" not in env)
    assert not missing, (
        f"{key}: its handler reads tables.{missing}, but the deployed Lambda carries no "
        f"{', '.join(f'{t.upper()}_TABLE_NAME' for t in missing)}. TableAccessor._get_table calls "
        "get_required_env, so the first request that touches the table raises inside the handler and the "
        "caller is answered INTERNAL_ERROR instead of its domain error (the redeemUnitInvite defect, "
        "2f457c5e). Name it in local.common_env or that function's extra_env."
    )


@pytest.mark.parametrize("key", sorted(deployed_workloads()))
def test_workload_table_env_resolves_to_a_real_table_key(key: str) -> None:
    """A typo in an env wiring line is a table that does not exist, not a build error.

    ``var.table_names.<key>`` is an index, so an unknown key is a plan-time
    failure; a value that bypasses the map with a literal name is invisible to
    every other pin here, so pin the shape too.
    """
    for var, expression in workload_env(key).items():
        if not var.endswith("_TABLE_NAME"):
            continue
        referenced = _TABLE_REF.findall(str(expression))
        assert len(referenced) == 1, f"{key}: {var} = {expression!r} must resolve through var.table_names"
        assert referenced[0] in accessor_table_keys(), f"{key}: {var} points at var.table_names.{referenced[0]}"


@pytest.mark.parametrize("env_name", ENVS)
def test_environment_passes_the_module_every_table_key_it_is_asked_for(env_name: str) -> None:
    """The module indexes ``var.table_names`` directly, so a missing key fails the plan."""
    declared = environment_table_keys(env_name)
    needed = {key for expression in common_env().values() for key in _TABLE_REF.findall(str(expression))}
    for workload in deployed_workloads():
        referenced = {
            key for expression in _extra_env(workload).values() for key in _TABLE_REF.findall(str(expression))
        }
        needed |= referenced
    missing = sorted(needed - declared)
    assert not missing, f"{env_name}: module.lambda.table_names omits {missing}"


@pytest.mark.parametrize("env_name", ENVS)
def test_environment_names_only_outputs_the_dynamodb_module_declares(env_name: str) -> None:
    """The other direction of the same name: a typo in ``module.dynamodb.<output>``.

    An environment that reads an output the table module never declares is a plan
    failure — invisible to every test that only reads the environment's own map.
    """
    declared: set[str] = set()
    for entry in load_hcl(TF_APP / "modules" / "dynamodb" / "main.tf").get("output", []):
        declared |= set(entry)
    referenced = set(re.findall(r"module\.dynamodb\.([a-z_]+)", (ENVIRONMENTS / env_name / "main.tf").read_text()))
    missing = sorted(referenced - declared)
    assert not missing, f"{env_name}: module.dynamodb declares no output {missing}"
