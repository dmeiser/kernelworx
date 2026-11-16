#!/usr/bin/env python3
"""Fail a pull request whose entire diff is comments, blank lines, and docs prose.

Why this exists: PR #949 merged with six green checks, a QA PASS, and a PM
scope PASS for a diff whose whole content was narration prose — every gate
asked "does the code still work" and none asked "does this comment need to
exist". AGENT.md section "Comments" states the rule; this script is the
mechanical half of it, the comment-only diff.

A diff is comment-only when every added and every removed line is blank, docs
prose (markdown/text files), or a comment in that file type's comment syntax,
and no file is renamed, mode-changed, or binary-changed. A comment-only diff
fails unless the pull request carries the `comment-only` label AND its body
carries a non-empty line starting with `Claim:` naming the wrong reader-facing
claim the change corrects.

CI (.github/workflows/comment-only-diff.yml) supplies the pull-request context
through the environment:

    PR_BASE_SHA   pull request base commit   (required)
    PR_HEAD_SHA   pull request head commit   (required)
    PR_LABELS     label names joined with commas
    PR_BODY       pull request body

A file path containing spaces is not parsed (no tracked path uses one).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

COMMENT_ONLY_LABEL = "comment-only"
CLAIM_LINE = re.compile(r"^[ \t]*Claim:[ \t]*\S", re.IGNORECASE | re.MULTILINE)

# Comment syntax per file type. A line counts as a comment only when its
# stripped text starts with the type's comment marker; trailing prose after
# code is part of a content line and never strips it.
LINE_COMMENT_PREFIXES: dict[str, tuple[str, ...]] = {
    ".bash": ("#",),
    ".graphql": ("#",),
    ".py": ("#",),
    ".pyi": ("#",),
    ".sh": ("#",),
    ".tf": ("#",),
    ".tfvars": ("#",),
    ".toml": ("#",),
    ".yml": ("#",),
    ".yaml": ("#",),
}
JS_SUFFIXES = frozenset({".cjs", ".js", ".jsx", ".mjs", ".ts", ".tsx"})
MARKUP_SUFFIXES = frozenset({".htm", ".html", ".vue", ".xml"})
PROSE_SUFFIXES = frozenset({".markdown", ".md", ".rst", ".txt"})

RULE = """\
The rule (AGENT.md, "Comments"):
    A comment may exist only to answer: why does this particular confusing
    piece of code exist, and what problem was it meant to solve?

The test to apply: delete the comment. Does the next reader now do something
wrong? No -> delete it. Yes -> keep it, and make it say what goes wrong."""


def _suffix(path: str) -> str:
    name = path.rsplit("/", 1)[-1].lower()
    return "" if "." not in name else name[name.rindex(".") :]


def line_is_comment_or_prose(path: str, text: str) -> bool:
    """True when the line contributes no executable or structural content."""
    stripped = text.strip()
    if not stripped:
        return True
    suffix = _suffix(path)
    if suffix in PROSE_SUFFIXES:
        return True
    if suffix in JS_SUFFIXES:
        return (
            stripped.startswith(("//", "/*", "*"))
            or stripped.endswith("*/")
        )
    if suffix in MARKUP_SUFFIXES:
        return stripped.startswith("<!--") and stripped.endswith("-->")
    prefixes = LINE_COMMENT_PREFIXES.get(suffix)
    if prefixes is not None:
        return stripped.startswith(prefixes)
    return False


@dataclass
class _Section:
    path: str = ""
    structural: bool = False
    changed: list[str] = field(default_factory=list)
    content_lines: int = 0


@dataclass
class Verdict:
    ok: bool
    message: str


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] == '"':
        inner = token[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return token


def _strip_side(path: str) -> str:
    """Drop the `a/` or `b/` side prefix of a `--- a/x` / `+++ b/x` header path."""
    return path[2:] if path[:2] in ("a/", "b/") else path


def _b_side(diff_header: str) -> str:
    """The b-side path of a `diff --git a/X b/Y` header (paths with spaces are not parsed)."""
    rest = diff_header[len("diff --git ") :]
    marker = rest.find(" b/")
    return rest[marker + 3 :] if marker != -1 else ""


def assess(diff_text: str, *, labels: list[str], body: str) -> Verdict:
    sections: list[_Section] = []
    current: _Section | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            current = _Section(path=_b_side(raw))
            sections.append(current)
            continue
        if current is None:
            continue
        if raw.startswith(
            (
                "rename from ",
                "rename to ",
                "copy from ",
                "copy to ",
                "old mode ",
                "new mode ",
                "Binary files ",
            )
        ):
            current.structural = True
            continue
        if raw.startswith("+++ "):
            side = raw[4:]
            if side != "/dev/null":
                current.path = _strip_side(_unquote(side))
            continue
        if raw.startswith("--- "):
            side = raw[4:]
            if current.path == "" and side != "/dev/null":
                current.path = _strip_side(_unquote(side))
            continue
        if raw.startswith(("+", "-")):
            current.changed.append(raw[1:])

    if not sections:
        return Verdict(True, "comment-only check: the diff touches no files; nothing to judge.")

    for section in sections:
        if section.structural:
            return Verdict(
                True,
                f"comment-only check: not comment-only — {section.path or '(renamed path)'} "
                "is a rename, mode change, or binary change.",
            )
        section.content_lines = sum(
            1 for line in section.changed if not line_is_comment_or_prose(section.path, line)
        )
        if section.content_lines:
            return Verdict(
                True,
                f"comment-only check: not comment-only — {section.path} changes "
                f"{section.content_lines} non-comment line(s).",
            )

    if COMMENT_ONLY_LABEL in labels and CLAIM_LINE.search(body):
        return Verdict(
            True,
            "comment-only check: comment-only diff, accepted — the `comment-only` label is "
            "present and the description states the wrong reader-facing claim being corrected.",
        )

    listed = "\n".join(
        f"    {section.path or '(unknown path)'}  {len(section.changed)} changed line(s)" for section in sections
    )
    missing = []
    if COMMENT_ONLY_LABEL not in labels:
        missing.append(f"add the `{COMMENT_ONLY_LABEL}` label")
    if not CLAIM_LINE.search(body):
        missing.append("add a description line starting with `Claim:` naming the wrong reader-facing claim corrected here")
    return Verdict(
        False,
        "comment-only diff: every added and removed line in this pull request is a comment, "
        "a blank line, or docs prose.\n\n"
        f"{RULE}\n\n"
        f"Changed files (no code line survives stripping comments):\n{listed}\n\n"
        "To pass: "
        + "; or ".join(missing)
        + ".",
    )


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def main() -> int:
    base = os.environ.get("PR_BASE_SHA", "").strip()
    head = os.environ.get("PR_HEAD_SHA", "").strip()
    if not base or not head:
        print("comment-only check: PR_BASE_SHA and PR_HEAD_SHA must name the pull request commits.", file=sys.stderr)
        return 2
    try:
        merge_base = _git("merge-base", base, head).strip()
        diff_text = _git("diff", "-U0", merge_base, head)
    except subprocess.CalledProcessError as failure:
        detail = (failure.stderr or "").strip()
        print(f"comment-only check: git {failure.cmd[1] if len(failure.cmd) > 1 else ''} failed: {detail}", file=sys.stderr)
        return 2

    labels = [item.strip() for item in os.environ.get("PR_LABELS", "").split(",") if item.strip()]
    verdict = assess(diff_text, labels=labels, body=os.environ.get("PR_BODY", ""))
    if verdict.ok:
        print(verdict.message)
        return 0
    print(verdict.message)
    print("::error::comment-only diff rejected. See AGENT.md, section \"Comments\", and the message above.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
