"""Tests for scripts/check_comment_only_diff.py, the comment-only diff gate.

The gate enforces AGENT.md, section "Comments": a pull request whose entire
diff is comments, blank lines, and docs prose is rejected unless it carries
the `comment-only` label and a `Claim:` line stating the wrong reader-facing
claim it corrects. The subprocess tests drive the real script against real
scratch git repositories, so they reproduce the ticket oracle end to end.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_comment_only_diff.py"

_spec = importlib.util.spec_from_file_location("check_comment_only_diff", SCRIPT)
assert _spec is not None and _spec.loader is not None
gate = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gate  # the gate's @dataclass classes resolve annotations via sys.modules
_spec.loader.exec_module(gate)

RULE_FRAGMENT = "why does this particular confusing"

WHY_COMMENT = (
    "# Cognito rejects mixing legacy flow names with ALLOW_* names in one "
    "explicit_auth_flows list (UpdateUserPoolClient answers 'Auth flow name "
    "with prefix ALLOW cannot be used with legacy auth flow names'), so this "
    "list stays ALLOW_USER_AUTH."
)


def added(path: str, lines: list[str]) -> str:
    header = (
        f"diff --git a/{path} b/{path}\n"
        f"index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
    )
    return header + "".join(f"+{line}\n" for line in lines)


# --- line classification ---------------------------------------------------------


def test_python_comment_line_is_not_content() -> None:
    assert gate.line_is_comment_or_prose("src/x.py", "    # return the list")


def test_python_code_line_with_trailing_comment_is_content() -> None:
    assert not gate.line_is_comment_or_prose("src/x.py", "    count += 1  # keeps the budget")


def test_js_line_comments_and_block_fragments_are_not_content() -> None:
    for line in ("// note", "/* note", " * note", " */"):
        assert gate.line_is_comment_or_prose("frontend/src/x.ts", line), line


def test_unknown_and_json_lines_are_content() -> None:
    assert not gate.line_is_comment_or_prose("data/config.json", '{"a": 1}')
    assert not gate.line_is_comment_or_prose("Makefile", "# notes kept conservative")


def test_markdown_lines_are_docs_prose() -> None:
    assert gate.line_is_comment_or_prose("docs/readme.md", "the flag is named --dry-run")


# --- verdicts over synthetic diffs --------------------------------------------------


def test_restatement_only_diff_is_rejected_and_quotes_the_rule() -> None:
    diff = added("src/items.py", ["    # return the list"])
    verdict = gate.assess(diff, labels=[], body="adds a helpful comment")
    assert not verdict.ok
    assert RULE_FRAGMENT in verdict.message
    assert "delete the comment" in verdict.message
    assert "src/items.py" in verdict.message  # paths render without the a//b/ side prefix


def test_why_comment_only_diff_needs_label_and_claim_and_says_so() -> None:
    diff = added("src/x.py", [f"    {WHY_COMMENT}"])
    unlabelled = gate.assess(diff, labels=[], body="documents a constraint")
    assert not unlabelled.ok
    assert "comment-only" in unlabelled.message
    assert "Claim:" in unlabelled.message

    no_claim = gate.assess(diff, labels=["comment-only"], body="documents a constraint")
    assert not no_claim.ok
    assert "Claim:" in no_claim.message

    justified = gate.assess(
        diff,
        labels=["comment-only"],
        body=(
            "documents a constraint\n\n"
            "Claim: the runbook said any auth flow name works; Cognito rejects mixing "
            "legacy names with ALLOW_* names."
        ),
    )
    assert justified.ok
    assert "accepted" in justified.message


def test_why_comment_with_a_code_line_passes_without_the_label() -> None:
    diff = added("src/x.py", [f"    {WHY_COMMENT}", '    explicit_auth_flows = ["ALLOW_USER_AUTH"]'])
    verdict = gate.assess(diff, labels=[], body="wires the flow")
    assert verdict.ok


def test_markdown_only_diff_is_comment_only() -> None:
    diff = added("docs/runbook.md", ["the flag is named --dry-run, not --dry run"])
    verdict = gate.assess(diff, labels=[], body="docs fix")
    assert not verdict.ok


def test_yaml_comment_only_diff_is_comment_only() -> None:
    diff = added(".github/workflows/x.yml", ["# this runs nightly"])
    verdict = gate.assess(diff, labels=[], body="explains the schedule")
    assert not verdict.ok


def test_rename_mode_and_binary_sections_are_not_comment_only() -> None:
    rename = (
        "diff --git a/old.py b/new.py\n"
        "similarity index 100%\n"
        "rename from old.py\n"
        "rename to new.py\n"
    )
    assert gate.assess(rename, labels=[], body="rename").ok

    binary = "diff --git a/x.png b/x.png\nBinary files a/x.png and b/x.png differ\n"
    assert gate.assess(binary, labels=[], body="favicon").ok


def test_empty_diff_has_nothing_to_judge() -> None:
    assert gate.assess("", labels=[], body="").ok


# --- the script end to end against real git ----------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=gate-test", "-c", "user.email=gate-test@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def scratch_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "items.py").write_text("def items() -> list[int]:\n    return []\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _run(repo: Path, base: str, head: str, *, labels: str = "", body: str = "") -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PR_BASE_SHA": base,
        "PR_HEAD_SHA": head,
        "PR_LABELS": labels,
        "PR_BODY": body,
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def _commit_comment(repo: Path, message: str) -> str:
    (repo / "items.py").write_text(
        "def items() -> list[int]:\n    # return the list\n    return []\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_script_rejects_a_restatement_comment_pr_and_quotes_the_rule(scratch_repo: tuple[Path, str]) -> None:
    repo, base = scratch_repo
    head = _commit_comment(repo, "add a clarifying comment")
    result = _run(repo, base, head, body="clarifies the function")
    assert result.returncode == 1
    assert RULE_FRAGMENT in result.stdout
    assert "delete the comment" in result.stdout
    assert "::error::" in result.stderr


def test_script_accepts_a_justified_why_comment_pr(scratch_repo: tuple[Path, str]) -> None:
    repo, base = scratch_repo
    (repo / "items.py").write_text(
        "def items() -> list[int]:\n"
        "    # the empty list, not None: callers sum() the result, and the 2026-09 crash "
        "run 43759285075 was a None flowing into sum().\n"
        "    return []\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "record the constraint")
    head = _git(repo, "rev-parse", "HEAD")
    result = _run(
        repo,
        base,
        head,
        labels="no-release,comment-only",
        body="Claim: the crash note said the list could be None; it must stay an empty list.",
    )
    assert result.returncode == 0
    assert "accepted" in result.stdout


def test_script_accepts_a_code_pr_without_the_label(scratch_repo: tuple[Path, str]) -> None:
    repo, base = scratch_repo
    (repo / "items.py").write_text("def items() -> list[int]:\n    return [1]\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "ship a one")
    head = _git(repo, "rev-parse", "HEAD")
    result = _run(repo, base, head)
    assert result.returncode == 0
    assert "not comment-only" in result.stdout


def test_script_exits_two_without_pr_shas(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        env={k: v for k, v in os.environ.items() if k not in {"PR_BASE_SHA", "PR_HEAD_SHA"}},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
