"""Artifact hygiene for the Show & Sell acceptance run.

The run writes screenshots, Playwright traces, and an evidence record for a
journey whose fixture codes are live credentials-in-waiting (a 16-character Unit
invite grants Unit admin; a join code attaches a Scout campaign), and whose
identities have real passwords.  So the artifacts get two different treatments,
and the difference is the point:

* a fixture **code** is expected to appear — the UI renders it — so it is
  overwritten with a same-length placeholder.  Same length matters: a Playwright
  trace is NDJSON with byte offsets, and a placeholder of a different length
  corrupts the entries around it;
* a **password** must never appear, so finding one fails the run.  Redacting it
  would let an artifact that carried a credential be uploaded and read as clean,
  which is the opposite of what a scan is for.

This lives outside the spec so the scan can be tested without importing a module
that carries a pytest marker the unit suite does not register.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

__all__ = ["bare_account_id", "redact_and_scan", "redact_zip"]

#: Written over a fixture code inside an artifact.  Same length as a 16-character
#: code, so the trace's NDJSON entries keep their byte offsets and stay readable.
REDACTION = "REDACTED" * 2


def bare_account_id(account_id: str) -> str:
    """Return the bare Cognito sub behind an account id.

    ``getMyAccount`` answers the storage spelling (``ACCOUNT#<sub>``) while the
    Unit grant rows carry the bare sub, so the two are compared through this
    normalizer — the same one the access panel uses.  Compared raw, the caller's
    own grant looks like somebody else's, and revoking it is what the teardown
    must never do.

    Args:
        account_id: an account id in either spelling.
    """
    return account_id.removeprefix("ACCOUNT#")


def redact_zip(path: Path, needles: list[tuple[bytes, bytes]], password_bytes: list[bytes]) -> int:
    """Rewrite one trace zip with fixture codes replaced.

    Args:
        path: the zip to rewrite.
        needles: ``(needle, placeholder)`` pairs to replace.
        password_bytes: strings that must not appear.

    Returns:
        How many replacements were made.

    Raises:
        AssertionError: if a password appears in any member, naming the member.
    """
    with zipfile.ZipFile(path) as reader:
        members = [(info, reader.read(info.filename)) for info in reader.infolist()]

    replacements = 0
    rewritten: list[tuple[Any, bytes]] = []
    for info, blob in members:
        for password in password_bytes:
            assert password not in blob, f"a password appears in {path.name}:{info.filename}"
        for needle, placeholder in needles:
            replacements += blob.count(needle)
            blob = blob.replace(needle, placeholder)
        rewritten.append((info, blob))

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as writer:
        for info, blob in rewritten:
            writer.writestr(info, blob)
    return replacements


def redact_and_scan(evidence_dir: Path, passwords: list[str], codes: list[str]) -> int:
    """Redact fixture codes from every artifact, then fail on any leaked password.

    Args:
        evidence_dir: the artifact directory to walk.
        passwords: every fixture password in play.
        codes: the invite and join codes the run issued.

    Returns:
        The total number of redactions made.

    Raises:
        AssertionError: if a password appears in any artifact.
    """
    needles = [(code.encode("utf-8"), REDACTION.encode("utf-8")) for code in codes if code]
    password_bytes = [password.encode("utf-8") for password in passwords if password]
    redactions = 0

    for path in sorted(evidence_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".zip":
            redactions += redact_zip(path, needles, password_bytes)
            continue
        blob = path.read_bytes()
        for password in password_bytes:
            assert password not in blob, f"a password appears in {path.name}"
        for needle, placeholder in needles:
            redactions += blob.count(needle)
            blob = blob.replace(needle, placeholder)
        path.write_bytes(blob)
    return redactions
