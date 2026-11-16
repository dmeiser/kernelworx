#!/usr/bin/env python3
"""Show & Sell QA fixture identities on the dev stack — one script, up and down.

    uv run python scripts/qa_fixture.py status        # pool state, no writes
    uv run python scripts/qa_fixture.py up            # create/refresh the four identities
    uv run python scripts/qa_fixture.py down          # delete them and sweep their rows
    uv run python scripts/qa_fixture.py down --yes    # ...without the confirmation prompt

Why this exists
---------------
Every acceptance check on the Show & Sell wave that is worth anything needs a
*signed-in* user on https://dev.kernelworx.app, and the pipeline has no way to
produce one: the dev pool is Cognito, sign-up sends mail, and no lane holds an
inbox. These four identities answer that with an admin-created account whose
password is set directly, so QA can log in and run the journey itself instead
of auditing somebody else's screenshots.

Credentials
-----------
AWS identity comes from the host's **ambient profile only** — ``~/.aws/config``
/ ``~/.aws/credentials`` / the standard session environment. The dev pool is
administered by the scoped user ``kernelworx-qa-ue1-dev`` (account
``750620721302``); the script never takes a credential, a password, or a pool
id from argv, and never reads the repository's ``.env``. Passwords are
generated here and written only to the secrets file (mode ``0600``, path
``$QA_FIXTURE_SECRETS_FILE`` or ``~/.kernelworx/qa-fixture-secrets.json``);
they are never printed, logged, or placed in argv. Run ``status`` to see what
the pool holds without writing anything.

What the pool does to anyone joining users to rows
--------------------------------------------------
Measured on ``us-east-1_sDiuCOarb`` on 2026-11-16: the pool declares
``username_attributes = ["email"]`` (``tofu/application/modules/cognito/main.tf:191``),
and every stored ``Username`` in it is a UUID equal to that user's ``sub`` —
including the users ``scripts/create-test-users.sh`` admin-creates with
``--username "$email"``, whose ``--username`` value is accepted as a handle and
then aliased, not kept. The one exception is a federated sign-up, whose
``Username`` is ``Google_<id>``.

So the address resolves on every ``admin_*`` call this script makes, but it is
**not** what ``Username`` holds, and the app keys its rows on the token's
``sub`` claim (``ACCOUNT#<sub>``). Anything that joins a Cognito user to an
application row by ``Username``, or that assumes the stored ``Username`` is an
address, silently matches nothing. Join on ``sub`` or ``email``;
:func:`pool_users` keys by address for exactly this reason.

Teardown is deliberate: ``down`` prints its full plan first, asks before it
writes, deletes the rows before the identities, and deletes nothing it cannot
attribute to a fixture ``sub``. The plan names the evidence for every row — the
key spells the identity, or the owner attribute does — because a person checking
the plan should not have to re-derive the rule. A failed delete is reported per
item, keeps the exit code non-zero, and leaves the identities in place so a
re-run is still attributable. Rows it cannot attribute are reported and left
alone — an append-only audit row that refuses deletion is a fact to report, not a
license to guess.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import string
import sys
from typing import Any, Callable, Iterable, TextIO

import boto3

REGION = "us-east-1"
POOL = "us-east-1_sDiuCOarb"
GROUP = "show-sell-preview"
DOMAIN = "dev.kernelworx.app"
BASE_URL = "https://dev.kernelworx.app"
CLIENT_NAME = "KernelWorx-Web"

# Identity local-part -> (secrets key suffix, member of GROUP?)
# The scout is a group member because ``frontend/src/ShowSellRoutes.tsx`` gates the
# whole ``/show-sell/*`` tree, ``/show-sell/join`` included: a scout outside the
# group cannot open its own join page, so the joined half of the Stage 1 journey
# cannot run. ``outside`` is the identity that carries the closed half of the gate,
# and it is the only one kept out. (Verified by the WORK-200 journey on the dev
# stack; see ``tests/e2e/README.md``.)
IDENTS: dict[str, tuple[str, bool]] = {
    "qa-show-sell-admin": ("ADMIN", True),
    "qa-show-sell-admin2": ("ADMIN2", True),
    "qa-show-sell-scout": ("SCOUT", True),
    "qa-show-sell-outside": ("OUTSIDE", False),
}

# table label -> (physical name, key attributes, owner attribute)
TABLES: dict[str, tuple[str, tuple[str, ...], str]] = {
    "accounts": ("kernelworx-accounts-ue1-dev", ("accountId",), "accountId"),
    "units": ("kernelworx-units-ue1-dev", ("pk", "sk"), "createdByAccountId"),
    "unit-campaigns": ("kernelworx-unit-campaigns-ue1-dev", ("pk", "sk"), "createdByAccountId"),
}

# Rows the pool should never accumulate: per-run sign-ups that were created and
# then abandoned without ever being confirmed. ``status`` counts them so a new
# leak is visible instead of silent.
LEAK_PREFIXES = ("e2e-signup-", "qa-wave2-", "qa-probe")

# Password alphabet: everything Cognito accepts that is safe to put in a JSON
# file and in an auth-parameters map.
ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*-_+="

SECRETS_FILE = os.environ.get("QA_FIXTURE_SECRETS_FILE") or os.path.expanduser("~/.kernelworx/qa-fixture-secrets.json")


def cip() -> Any:
    """Cognito-IdP client from the ambient AWS identity."""
    return boto3.Session().client("cognito-idp", region_name=REGION)


def ddb() -> Any:
    """DynamoDB client from the ambient AWS identity."""
    return boto3.Session().client("dynamodb", region_name=REGION)


def password(n: int = 24) -> str:
    """A generated password that satisfies the pool's default policy."""
    while True:
        pw = "".join(secrets.choice(ALPHABET) for _ in range(n))
        if (
            any(c.islower() for c in pw)
            and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(not c.isalnum() for c in pw)
        ):
            return pw


def emails() -> dict[str, str]:
    """local-part -> address."""
    return {local: f"{local}@{DOMAIN}" for local in IDENTS}


def _attrs(user: dict[str, Any]) -> dict[str, str]:
    return {a["Name"]: a["Value"] for a in user.get("Attributes", [])}


def pool_users(c: Any) -> dict[str, dict[str, Any]]:
    """address -> user record, for the whole pool.

    Paginated: the dev pool holds more users than one page returns, and a
    truncated read makes a fixture that exists look absent.
    """
    out: dict[str, dict[str, Any]] = {}
    token = None
    while True:
        kw: dict[str, Any] = {"UserPoolId": POOL, "Limit": 60}
        if token:
            kw["PaginationToken"] = token
        page = c.list_users(**kw)
        for u in page.get("Users", []):
            mail = _attrs(u).get("email")
            if mail:
                out[mail] = u
        token = page.get("PaginationToken")
        if not token:
            return out


def group_members(c: Any) -> set[str]:
    """Addresses in :data:`GROUP` (empty when the group is empty)."""
    try:
        users = c.list_users_in_group(UserPoolId=POOL, GroupName=GROUP)["Users"]
    except c.exceptions.ResourceNotFoundException:
        return set()
    return {_attrs(u).get("email") or u["Username"] for u in users}


def leaked_users(known: dict[str, dict[str, Any]]) -> list[str]:
    """Addresses that look like abandoned per-run sign-ups."""
    return sorted(mail for mail in known if mail.split("@")[0].startswith(LEAK_PREFIXES))


def render_status(c: Any, out: TextIO) -> None:
    """Report pool state. Safe on an empty pool and writes nothing."""
    have = pool_users(c)
    mem = group_members(c)
    print(f"pool {POOL}  group {GROUP}  members: {sorted(mem) or 'none'}", file=out)
    for local, (_key, want) in IDENTS.items():
        mail = f"{local}@{DOMAIN}"
        u = have.get(mail)
        if not u:
            print(f"  {mail:<44} ABSENT", file=out)
            continue
        a = _attrs(u)
        print(
            f"  {mail:<44} {u['UserStatus']:<10} verified={str(a.get('email_verified')):<5} "
            f"preview={'yes' if mail in mem else 'no':<3} want={want}",
            file=out,
        )
    clients = c.list_user_pool_clients(UserPoolId=POOL, MaxResults=60)["UserPoolClients"]
    named = [cl for cl in clients if cl["ClientName"] == CLIENT_NAME]
    print(
        f"  app clients named {CLIENT_NAME}: {len(named)} of {len(clients)} "
        f"(a name lookup is only safe when this is 1)",
        file=out,
    )
    leaks = leaked_users(have)
    print(f"  users total={len(have)}  leaked strays={len(leaks)}", file=out)
    for mail in leaks:
        print(f"    stray {mail} [{have[mail]['UserStatus']}]", file=out)


def apply_up(c: Any, out: TextIO, secrets_file: str = SECRETS_FILE) -> dict[str, str]:
    """Create or refresh the four identities; idempotent when they exist."""
    values: dict[str, str] = {"TEST_QA_SHOW_SELL_BASE_URL": BASE_URL}
    for local, (key, want_group) in IDENTS.items():
        mail = f"{local}@{DOMAIN}"
        pw = password()
        try:
            c.admin_create_user(
                UserPoolId=POOL,
                Username=mail,
                MessageAction="SUPPRESS",
                UserAttributes=[
                    {"Name": "email", "Value": mail},
                    {"Name": "email_verified", "Value": "true"},
                ],
            )
            verb = "created"
        except c.exceptions.UsernameExistsException:
            verb = "refreshed"
        c.admin_set_user_password(UserPoolId=POOL, Username=mail, Password=pw, Permanent=True)
        c.admin_update_user_attributes(
            UserPoolId=POOL,
            Username=mail,
            UserAttributes=[{"Name": "email_verified", "Value": "true"}],
        )
        if want_group:
            c.admin_add_user_to_group(UserPoolId=POOL, Username=mail, GroupName=GROUP)
        else:
            try:
                c.admin_remove_user_from_group(UserPoolId=POOL, Username=mail, GroupName=GROUP)
            except c.exceptions.ResourceNotFoundException:
                pass
        values[f"TEST_QA_SHOW_SELL_{key}_EMAIL"] = mail
        values[f"TEST_QA_SHOW_SELL_{key}_PASSWORD"] = pw
        print(f"  {mail:<44} {verb}{' +' + GROUP if want_group else ''}", file=out)
    write_secrets(values, secrets_file)
    print(f"\nwrote {secrets_file} (mode 0600); no password is printed here", file=out)
    return values


def write_secrets(values: dict[str, str], path: str) -> None:
    """Persist the identities to a 0600 file outside the repository."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(values, fh, indent=2)
    os.chmod(path, 0o600)


def sign_in_proof(c: Any, values: dict[str, str], out: TextIO) -> bool:
    """Prove sign-in works and show which app client answered.

    The pool holds several clients that share the name ``KernelWorx-Web`` and
    they do not share ``ExplicitAuthFlows``, so a name lookup is a coin flip
    (``#567``). The proof therefore *tries* clients and reports the id that
    worked, rather than assuming the first one named is usable.
    """
    admin = values["TEST_QA_SHOW_SELL_ADMIN_EMAIL"]
    pw = values["TEST_QA_SHOW_SELL_ADMIN_PASSWORD"]
    for cl in c.list_user_pool_clients(UserPoolId=POOL, MaxResults=60)["UserPoolClients"]:
        try:
            r = c.initiate_auth(
                ClientId=cl["ClientId"],
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={"USERNAME": admin, "PASSWORD": pw},
            )
        except Exception:  # noqa: BLE001 - flow not enabled on this client; try the next
            continue
        result = r.get("AuthenticationResult")
        if not result:
            continue
        token = result["IdToken"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        print(
            f"  sign-in ok via client {cl['ClientId']}: groups={claims.get('cognito:groups')} mfa={claims.get('mfa')}",
            file=out,
        )
        return True
    print("  sign-in proof FAILED: no app client in the pool accepted USER_PASSWORD_AUTH", file=out)
    return False


def _flatten(item: dict[str, Any]) -> dict[str, str]:
    """Scalar attribute values of a raw DynamoDB item."""
    return {k: next(iter(v.values())) for k, v in item.items() if isinstance(v, dict) and len(v) == 1}


def _segments(value: str) -> set[str]:
    """The value itself plus each of its ``#``-separated parts."""
    return set(value.split("#")) if value else set()


def _owner_ids(value: str) -> set[str]:
    """Account ids spelled anywhere in a key or attribute value.

    Covers the bare ``sub``, the ``ACCOUNT#<sub>`` spelling the app uses, and a
    nested key such as ``GRANT#ACCOUNT#<sub>``. A global ``ACCOUNT#`` strip would
    turn that last one into ``GRANT#<sub>`` and lose the match, which is how the
    next key shape gets silently mis-attributed.
    """
    parts = value.split("#") if value else []
    embedded = {parts[i + 1] for i, p in enumerate(parts) if p == "ACCOUNT" and i + 1 < len(parts)}
    return embedded | set(parts)


def owned_rows(
    d: Any, subs: Iterable[str]
) -> tuple[list[tuple[str, str, dict[str, str], str]], list[tuple[str, str]]]:
    """Rows attributable to the fixture accounts, and rows that merely look related.

    A row is deletable only when a fixture identity is spelled in the row itself:
    a key part is exactly a fixture address (``…/ROLE#<fixture address>``), a key
    part is a fixture ``sub`` (``ACCOUNT#<sub>``, ``IDEM#<sub>#<action>#<uuid>``,
    ``UNIT#<id>/GRANT#<sub>``), or the owner attribute carries it
    (``createdByAccountId=ACCOUNT#<sub>`` on a ``METADATA`` row whose key is an
    opaque id). Everything else is reported as unattributed and never deleted,
    including rows that share a partition key with a fixture row: a third
    party's ``MEMBERSHIP#PROFILE#<their sub>`` on a fixture campaign is their
    data, and guessing here would reach into another tenant.

    Each deletable row comes back with the evidence that selected it, because a
    person reading the plan has to be able to check every row against these
    shapes without re-deriving the rule.
    """
    wanted = {s for s in subs if s}
    mails = set(emails().values())
    deletable: list[tuple[str, str, dict[str, str], str]] = []
    unattributed: list[tuple[str, str]] = []
    if not wanted:
        return deletable, unattributed
    for label, (table, key_names, owner_attr) in TABLES.items():
        skipped: list[tuple[str, str]] = []
        scan_kw: dict[str, Any] = {"TableName": table, "ConsistentRead": False}
        rows: list[tuple[dict[str, str], str]] = []
        while True:
            page = d.scan(**scan_kw)
            for item in page.get("Items", []):
                flat = _flatten(item)
                key_vals = {k: flat.get(k, "") for k in key_names}
                parts = {p for v in key_vals.values() for p in _segments(v)}
                owners = _owner_ids(flat.get(owner_attr, ""))
                if parts & mails:
                    rows.append((key_vals, "key names a fixture address"))
                elif parts & wanted:
                    rows.append((key_vals, "key names a fixture sub"))
                elif owners & wanted:
                    rows.append((key_vals, f"{owner_attr} names a fixture sub"))
                else:
                    skipped.append((label, "/".join(key_vals.values())))
            if "LastEvaluatedKey" not in page:
                break
            scan_kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        for key_vals, reason in rows:
            deletable.append((label, "/".join(key_vals.values()), {k: key_vals[k] for k in key_names}, reason))
        for label_skipped, key in skipped:
            unattributed.append((label_skipped, key))
    return deletable, unattributed


def _remove_secrets(secrets_file: str, out: TextIO) -> None:
    """Drop the credentials file, whether or not there was anything to delete."""
    if os.path.exists(secrets_file):
        os.remove(secrets_file)
        print(f"removed {secrets_file}", file=out)


def apply_down(
    c: Any,
    d: Any,
    assume_yes: bool,
    out: TextIO,
    confirm: Callable[[str], str] = input,
    secrets_file: str = SECRETS_FILE,
) -> int:
    """Delete the fixture rows first, then the identities. Plan first, always.

    The order is the point. Rows are attributable only while the users exist, so
    a row that fails to delete must never be followed by deleting the user whose
    ``sub`` attributes it: that would strand rows nothing can attribute later,
    the exact state this script exists to prevent. So each item is attempted on
    its own, a failure is printed rather than aborting the sweep, and if any row
    failed the users are left in place and the exit code is non-zero — the next
    ``down`` re-derives the same subs and finishes the job.
    """
    mails = emails()
    have = pool_users(c)
    mem = group_members(c)
    present = [m for m in mails.values() if m in have]
    subs = {s for s in (_attrs(have[m]).get("sub") for m in present) if s}
    rows, unattributed = owned_rows(d, subs)

    print(f"plan: delete {len(present)} fixture users", file=out)
    for mail in present:
        print(f"  user   {mail}", file=out)
    if not present:
        print("  user   (none present)", file=out)
    for label, key, _key_doc, reason in rows:
        print(f"  row    {label:<14} {key}  [{reason}]", file=out)
    if not rows:
        print("  row    (no fixture-owned rows found)", file=out)
    for label, key in unattributed:
        print(f"  left   {label:<14} {key}  (not attributable to a fixture sub)", file=out)
    print(
        f"  sweep  tables: {', '.join(TABLES)} — rows in any other table are left behind",
        file=out,
    )

    if not present and not rows:
        print("nothing to delete", file=out)
        _remove_secrets(secrets_file, out)
        return 0
    if not assume_yes:
        if confirm("proceed? [y/N] ").strip().lower() != "y":
            print("aborted", file=out)
            return 1

    row_failures = 0
    for label, key, key_doc, _reason in rows:
        table = TABLES[label][0]
        try:
            d.delete_item(TableName=table, Key={k: {"S": v} for k, v in key_doc.items()})
            print(f"  deleted row  {label:<14} {key}", file=out)
        except Exception as exc:  # noqa: BLE001 - report and keep sweeping; never abort mid-table
            row_failures += 1
            print(f"  FAILED row   {label:<14} {key}  {type(exc).__name__}", file=out)
    if row_failures:
        print(
            f"  {row_failures} row delete(s) failed: the fixture users are kept so their rows "
            "stay attributable — re-run `down` to finish",
            file=out,
        )
        return 1

    user_failures = 0
    for mail in present:
        try:
            c.admin_user_global_sign_out(UserPoolId=POOL, Username=mail)
        except Exception:  # noqa: BLE001 - never signed in
            pass
        try:
            if mail in mem:
                c.admin_remove_user_from_group(UserPoolId=POOL, Username=mail, GroupName=GROUP)
        except Exception:  # noqa: BLE001 - the user delete does not depend on the group edge
            pass
        try:
            c.admin_delete_user(UserPoolId=POOL, Username=mail)
            print(f"  deleted user {mail}", file=out)
        except Exception as exc:  # noqa: BLE001 - report the survivor instead of losing the rest
            user_failures += 1
            print(f"  FAILED user  {mail}  {type(exc).__name__}", file=out)
    _remove_secrets(secrets_file, out)
    if user_failures:
        print(f"  {user_failures} user delete(s) failed; their rows are already gone — re-run `down`", file=out)
        return 1
    return 0


def main(argv: list[str], out: TextIO = sys.stdout) -> int:
    action = argv[1] if len(argv) > 1 else "status"
    if action not in {"status", "up", "down"}:
        print(__doc__, file=out)
        return 2
    cognito = cip()
    if action == "status":
        render_status(cognito, out)
        return 0
    if action == "up":
        values = apply_up(cognito, out)
        sign_in_proof(cognito, values, out)
        render_status(cognito, out)
        return 0
    return apply_down(cognito, ddb(), "--yes" in argv, out)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
