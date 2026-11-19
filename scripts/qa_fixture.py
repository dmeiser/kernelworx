#!/usr/bin/env python3
"""Show & Sell QA fixture identities on the dev stack — one script, up and down.

    uv run python scripts/qa_fixture.py status        # pool state, no writes
    uv run python scripts/qa_fixture.py up            # create/refresh the four identities
    uv run python scripts/qa_fixture.py down          # delete them and sweep their rows
    uv run python scripts/qa_fixture.py down --yes    # ...without the confirmation prompt
    uv run python scripts/qa_fixture.py sweep \
        --lane data-id=stage2-1118107 --lane unit=<uuid> \
        --lane unit-campaign=<uuid> --lane join-code=<CODE> --yes
                                                    # one acceptance lane's rows, users kept

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

``sweep`` narrows the same idea to one acceptance lane, because an
acceptance run leaves rows the product cannot delete: the SDL carries no
``deleteUnit`` and no ``deleteUnitCampaign``, so the Unit and its Unit Campaign
rows outlive every GraphQL teardown the run performs.

Two things keep it narrow, and both matter:

* **Typed tokens.** A token is ``kind=value`` and must match the stored shape of
  its kind (``data-id``, ``unit``, ``unit-campaign``, ``campaign``, ``profile``,
  ``order``, ``join-code``, ``idem``). Free text is refused: a token with no kind,
  a short one, or a partial one would select rows the caller never meant, with
  ``--yes`` already given. A token is compared only to the field its kind names.
* **One reviewed rule per key shape.** Most rows a Stage 2 lane writes carry no
  fixture identity at all — an inventory balance or custody row names only its
  Unit Campaign, product and Scout profile, and a join-code pointer only its
  campaign id and a timestamp — so attribution alone cannot find them. Each key
  shape has its own rule, written against the builders that mint it
  (``src/utils/unit_models.py``, ``src/utils/unit_campaign_models.py``,
  ``src/utils/inventory_models.py``, ``src/utils/order_fulfillment_models.py``,
  ``src/utils/order_keys.py``, ``src/utils/mutations.py``). A row whose shape no
  rule describes is reported as ``kept`` and never deleted. Attribution is not a
  substitute for identity either, and three rules are narrow because of it: an
  active-join guard goes only when its exact Scout Campaign id is named (one
  profile holds a guard per Campaign, so a profile token cannot say which is
  joined), an idempotency marker goes only when a fixture identity wrote it (the
  idempotency key is caller-supplied, so the same key can exist for another
  actor), and an inventory movement row is never deleted at all — it is the
  append-only audit record the lane exists to produce, reported as history.

After deleting, ``sweep`` re-scans and applies the same rules again, printing
``LEFT <table>/<key>`` for a lane row that survived (a ``delete_item`` that
returned without an error is not evidence) and ``kept`` for a row a lane token
names that the rules refuse to remove — a third party's ``GRANT#…`` or
``MEMBERSHIP#…`` on a lane partition, a guard whose Campaign is not named, a
marker no fixture identity wrote, or that movement history. A table the identity
cannot read prints ``BLOCKED <table>: <denied action> is not granted to this
identity (<error>)``: a denied scan is reported with the permission it is
missing, never treated as an empty table and never reduced to a count. Measured
on 2026-11-19, ``kernelworx-qa-ue1-dev`` is denied ``dynamodb:Scan`` and
``dynamodb:DeleteItem`` on the Stage 2 inventory, orders and order-fulfillment
tables, so those rows are a named finding until a grant lands — an IAM grant
alone does not close the sweep, it only makes these tables readable enough for
the rules to run. Any ``LEFT``, ``FAILED`` or ``BLOCKED`` line makes the exit
code non-zero. The identities are never touched. See ``docs/QA_FIXTURE_RUNBOOK.md``.

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
import re
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

# Tables an acceptance lane writes that ``down`` does not reach by identity alone:
# the rows are keyed on resource ids (``INV#<unitCampaignId>``, ``CAMPAIGN#…/ORDER#…``)
# rather than on a fixture ``sub``, so ``sweep`` narrows them by lane token as well.
# Key shapes and owner attributes come from ``tofu/application/modules/dynamodb/main.tf``,
# ``src/utils/inventory_models.py`` (``actorAccountId`` on a movement row) and
# ``src/utils/order_fulfillment_models.py``.
LANE_TABLES: dict[str, tuple[str, tuple[str, ...], str]] = {
    "inventory": ("kernelworx-inventory-ue1-dev", ("pk", "sk"), "actorAccountId"),
    "orders": ("kernelworx-orders-ue1-dev", ("campaignId", "orderId"), "createdByAccountId"),
    "order-fulfillments": ("kernelworx-order-fulfillments-ue1-dev", ("pk", "sk"), "createdByAccountId"),
}

# Everything a lane sweep may consider, in one place.
SWEEP_TABLES: dict[str, tuple[str, tuple[str, ...], str]] = {**TABLES, **LANE_TABLES}

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


def _attribution(
    item: dict[str, Any], key_names: tuple[str, ...], owner_attr: str, wanted: set[str], mails: set[str]
) -> tuple[dict[str, str], str] | None:
    """Why this row belongs to a fixture identity, or ``None`` if nothing says so.

    One rule, used by ``down`` and by ``sweep`` alike: a key part that is a fixture address, a key
    part that is a fixture ``sub``, or the table's owner attribute naming one. Sharing a partition
    key with a fixture row is not attribution.
    """
    flat = _flatten(item)
    # These tables key on strings, and every owner attribute this script reads is a string; a bool
    # (``isActive``) or a number is not something to search, so it is skipped rather than matched.
    key_vals = {k: str(flat.get(k, "")) for k in key_names}
    parts = {p for v in key_vals.values() for p in _segments(v)}
    owner_value = flat.get(owner_attr, "")
    owners = _owner_ids(owner_value) if isinstance(owner_value, str) else set()
    if parts & mails:
        return key_vals, "key names a fixture address"
    if parts & wanted:
        return key_vals, "key names a fixture sub"
    if owners & wanted:
        return key_vals, f"{owner_attr} names a fixture sub"
    return None


# --------------------------------------------------------------------------- #
# Lane sweep: typed tokens, one reviewed rule per key shape, and a residue scan
# --------------------------------------------------------------------------- #

#: A lane sweep deletes without a prompt, so it never accepts free text.  A token names its kind
#: and must match the shape the application stores for that kind, and it is compared only to the
#: field that kind addresses — a Unit id is matched against a row's partition key, not against
#: every string in the row.  ``--lane 1`` is therefore refused rather than selecting every row
#: whose payload happens to contain ``1`` in every readable table.
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
TOKEN_SHAPES: dict[str, tuple[str, int]] = {
    "data-id": (r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+", 8),
    "unit": (_UUID, 36),
    "unit-campaign": (_UUID, 36),
    "campaign": (_UUID, 36),
    "profile": (_UUID, 36),
    "order": (r"ORDER#" + _UUID + r"#[A-Za-z0-9_-]{4,64}", 12),
    "join-code": (r"[A-Z0-9]{16}", 16),
    "idem": (r"[A-Za-z][A-Za-z0-9_-]{7,127}", 8),
}


def parse_lane_tokens(values: Iterable[str]) -> tuple[dict[str, set[str]], list[str]]:
    """Read ``kind=value`` lane tokens, and return every way one fails the shape it claims.

    Refusal happens before any table is read, so a mistyped sweep is a message rather than a set
    of deleted rows.
    """
    tokens: dict[str, set[str]] = {kind: set() for kind in TOKEN_SHAPES}
    problems: list[str] = []
    for value in values:
        kind, sep, raw = value.partition("=")
        if not sep:
            problems.append(f"{value!r}: a lane token names its kind, e.g. --lane unit-campaign=<uuid>")
            continue
        if kind not in TOKEN_SHAPES:
            problems.append(f"{value!r}: unknown token kind; expected one of {', '.join(sorted(TOKEN_SHAPES))}")
            continue
        pattern, minimum = TOKEN_SHAPES[kind]
        if len(raw) < minimum or not re.fullmatch(pattern, raw):
            problems.append(
                f"{value!r}: {kind} must match {pattern}; a short or partial token could name another run's rows"
            )
            continue
        tokens[kind].add(raw)
    return tokens, problems


def _bare(value: str, prefix: str) -> str:
    """One stored id spelling with its application prefix removed (``PROFILE#x`` to ``x``)."""
    head, sep, rest = value.partition("#")
    return rest if sep and head == prefix else value


def _strings(item: dict[str, Any]) -> dict[str, str]:
    """The string scalars of a raw item.

    ``_flatten`` hands back whatever a scalar attribute holds, and ``isActive`` holds a bool and a
    quantity holds a number; neither is something to compare an id token against.
    """
    return {k: v for k, v in _flatten(item).items() if isinstance(v, str)}


def _mask_secret(value: str) -> str:
    """Never carry a live join code into a report a person pastes into an issue."""
    return re.sub(r"[A-Z0-9]{16}", "*" * 16, value)


_DENIED_ACTION = re.compile(r"not authorized to perform:\s*([A-Za-z0-9:*_-]+)")


def _denied_action(exc: BaseException) -> str:
    """The permission a failed DynamoDB call is missing, when the service says which one it is.

    DynamoDB spells the denied action and the resource into the message, so a reader of a sweep report
    sees what to ask for rather than that something went wrong.  Measured on dev on 2026-11-19,
    ``kernelworx-qa-ue1-dev`` holds neither ``dynamodb:Scan`` nor ``dynamodb:DeleteItem`` on the Stage 2
    inventory, orders and order-fulfillment tables.  Anything the message does not name — a timeout, a
    wrong table — is reported by its exception type instead of being guessed at.
    """
    message = str(exc)
    denied = _DENIED_ACTION.search(message)
    return denied.group(1) if denied else type(exc).__name__


def _blocked_line(table: str, exc: BaseException) -> str:
    """One unreadable table, reported with the permission that is missing, never as a bare count."""
    message = str(exc)[:300]
    action = _denied_action(exc)
    if action == type(exc).__name__:
        return f"BLOCKED {table}: {type(exc).__name__}: {message}"
    return f"BLOCKED {table}: {action} is not granted to this identity ({type(exc).__name__}: {message})"


def _rule_units(item: dict[str, Any], tokens: dict[str, set[str]], subs: set[str]) -> tuple[str, str] | None:
    """``UNIT#<unitId>``: the metadata row is the lane's, a grant only when it is a fixture identity's."""
    flat = _strings(item)
    pk, sk = flat.get("pk", ""), flat.get("sk", "")
    if not pk.startswith("UNIT#"):
        return None
    unit = pk[len("UNIT#") :]
    if unit not in tokens["unit"]:
        return None
    if sk == "METADATA":
        if _owner_ids(flat.get("createdByAccountId", "")) & subs:
            return "delete", f"Unit metadata row for lane Unit {unit}, created by a fixture identity"
        return "keep", f"Unit {unit} carries no createdByAccountId naming a fixture identity"
    if sk.startswith("GRANT#"):
        named = {p for p in _owner_ids(sk) if p not in {"GRANT", "ACCOUNT"}}
        foreign = sorted(p for p in named if p not in subs)
        if named and not foreign:
            return "delete", f"Unit Admin grant held by a fixture identity on lane Unit {unit}"
        who = ", ".join(foreign) or _mask_secret(sk)
        return "keep", f"grant on lane Unit {unit} names {who}: not a fixture identity"
    return "keep", f"row shape {sk!r} on lane Unit {unit} is not described by any rule"


def _rule_marker(pk: str, sk: str, tokens: dict[str, set[str]], subs: set[str]) -> tuple[str, str] | None:
    """``IDEM#<actor>#<operation>#<scope>`` with sort key ``IDEM#<idempotencyKey>``.

    ``src/utils/mutations.py`` mints these as ``actor + operation + scope + caller-supplied key``, and
    the last of those four is exactly that: nothing in the application makes a key unique per tenant, so
    the same ``idem`` token can legitimately exist for another actor's partition.  A named key therefore
    selects a row only when the partition key also names a fixture identity as its author — authorship is
    checked first, before any of the three delete branches, and a marker that a lane token names but that
    no fixture identity wrote is reported and left.  The author is read by ``#`` segment after undoing
    ``_escape_key_segment``'s ``%23``, so neither the spelling of the actor (bare ``sub``, or an escaped
    ``ACCOUNT#sub``) nor a substring of an id changes the answer.  A tenant outside the fixture pool that
    happened to choose a ``stage2-…`` key is not this lane.

    Given authorship, the marker is the lane's when the key carries the lane's ``DATA_ID`` prefix — every
    key the Stage 2 lane sends is ``<data-id>-…`` — when the caller named that key, or when the partition
    key names a resource this lane named as its scope.

    Anything else is left.  A marker no token of this lane says anything about is not reported at all:
    the ``unit-campaigns`` table holds every earlier run's markers, and a sweep that listed them as
    refused would bury the rows a rule actually weighed.  What is reported is the case worth a reader —
    a marker naming a resource this lane created, or an idempotency key this lane named, that someone
    outside the fixture pool wrote, which stays and says so.
    """
    if not pk.startswith("IDEM#") or not sk.startswith("IDEM#"):
        return None
    key = sk[len("IDEM#") :]
    segments = _owner_ids(pk.replace("%23", "#"))
    authored = bool(segments & subs)
    scopes = tokens["unit"] | tokens["unit-campaign"] | tokens["campaign"] | tokens["join-code"] | tokens["order"]
    scoped = bool(segments & scopes)
    if not authored:
        if scoped or key in tokens["idem"]:
            return "keep", f"marker key {key} names a lane resource but no fixture identity wrote it"
        return None
    if key in tokens["idem"]:
        return "delete", f"marker for an idempotency key the caller named ({key}), written by a fixture identity"
    if any(key.startswith(f"{data_id}-") for data_id in tokens["data-id"]):
        return "delete", f"marker this lane's DATA_ID wrote ({key})"
    if scoped:
        return "delete", f"marker written by a fixture identity scoped to a lane resource ({key})"
    return None


def _rule_unit_campaigns(item: dict[str, Any], tokens: dict[str, set[str]], subs: set[str]) -> tuple[str, str] | None:
    """The shapes a Unit Campaign partition, a Scout Campaign guard, a join-code pointer and a marker hold.

    ``build_membership_item`` writes a ``profileId``, so a roster row is the lane's when the lane names
    that profile — on a Unit Campaign this lane named, which is the half that bounds it.  A guard is not
    the same shape: ``build_membership_guard_item`` is one row per Scout, and a Scout profile runs many
    Scout Campaigns, so a profile token says which person's guard this is and nothing about which
    Campaign is joined.  A guard is therefore deleted only when its exact Campaign identity is named; a
    prior run whose Campaign id cannot be recovered reports its guard as unresolved and leaves it.
    ``removeUnitCampaignMembership`` clears the guard's ``activeUnitCampaignId`` but leaves the guard row
    itself (``guard_release_action``), and nothing deletes a join-code pointer or a marker once its
    mutation is done: these are the rows a lane keeps.
    """
    flat = _strings(item)
    pk, sk = flat.get("pk", ""), flat.get("sk", "")
    if pk.startswith("UNIT_CAMPAIGN#"):
        campaign = _bare(pk[len("UNIT_CAMPAIGN#") :], "CAMPAIGN")
        if campaign not in tokens["unit-campaign"]:
            return None
        if sk == "METADATA":
            if _owner_ids(flat.get("createdByAccountId", "")) & subs:
                return "delete", f"Unit Campaign metadata row for lane Unit Campaign {campaign}"
            return "keep", f"Unit Campaign {campaign} carries no createdByAccountId naming a fixture identity"
        if sk.startswith("MEMBERSHIP#"):
            profile = _bare(flat.get("profileId") or sk[len("MEMBERSHIP#") :], "PROFILE")
            if profile in tokens["profile"]:
                return "delete", f"roster membership of the lane's own Scout profile on Unit Campaign {campaign}"
            return (
                "keep",
                f"membership of profile {profile} on lane Unit Campaign {campaign}: that profile is not this lane's",
            )
        return "keep", f"row shape {sk!r} on lane Unit Campaign {campaign} is not described by any rule"
    if pk.startswith("SCOUT_CAMPAIGN#"):
        campaign = _bare(pk[len("SCOUT_CAMPAIGN#") :], "CAMPAIGN")
        profile = _bare(flat.get("profileId", ""), "PROFILE")
        if campaign not in tokens["campaign"] and profile not in tokens["profile"]:
            return None
        if sk == "MEMBERSHIP_GUARD":
            if campaign not in tokens["campaign"]:
                return (
                    "keep",
                    f"active-join guard of profile {profile}'s Scout Campaign {campaign}: that Campaign is not "
                    "named, and one profile holds a guard per Campaign, so a profile token cannot say which is joined",
                )
            return "delete", f"active-join guard of lane Scout Campaign {campaign}"
        return "keep", f"row shape {sk!r} for lane Scout Campaign {campaign} is not described by any rule"
    if pk.startswith("JOIN_CODE#"):
        code = pk[len("JOIN_CODE#") :]
        unit_campaign = _bare(flat.get("unitCampaignId", ""), "CAMPAIGN")
        if sk == "POINTER" and (code in tokens["join-code"] or unit_campaign in tokens["unit-campaign"]):
            return "delete", f"join-code pointer for lane Unit Campaign {unit_campaign or code}"
        return None
    if pk.startswith("IDEM#"):
        return _rule_marker(pk, sk, tokens, subs)
    return None


def _rule_inventory(item: dict[str, Any], tokens: dict[str, set[str]], subs: set[str]) -> tuple[str, str] | None:
    """``UNIT_CAMPAIGN#<id>`` partitions: balances, custody and allocations, and the movement history.

    This is the shape a balance or custody row is invisible to under attribution: neither carries
    an owner attribute, and only a movement row carries ``actorAccountId``.  The partition key is
    the ownership fact, so it is the rule — narrowed by a principal guard, because a custody row
    for a profile this lane did not name, or a movement written by an account outside the fixture
    pool, is not this lane's to delete.  Attribution alone never deletes anything here: a row in a
    partition no ``unit-campaign`` token names is not reported at all.

    The movement rows are reported separately and never deleted.  ``src/utils/inventory_models.py``
    describes ``InventoryMovement`` as an immutable audit record, and ``build_movement_sk`` mints one
    row per write (``PRODUCT#<id>#MOVEMENT#<moment>#<n>``): deleting it would rewrite the trail an
    acceptance run exists to prove, and it is what an auditor or an accounting backfill reads after
    the lane is gone.  Every other row in the partition is a position a lane's own return and
    reconcile steps drove to zero, so taking it back is teardown, not evidence.
    """
    flat = _strings(item)
    pk = flat.get("pk", "")
    if not pk.startswith("UNIT_CAMPAIGN#"):
        return None
    campaign = _bare(pk[len("UNIT_CAMPAIGN#") :], "CAMPAIGN")
    if campaign not in tokens["unit-campaign"]:
        return None
    profile = _bare(flat.get("profileId", ""), "PROFILE")
    if profile and profile not in tokens["profile"]:
        return (
            "keep",
            f"custody row for profile {profile} in lane Unit Campaign {campaign}: that profile is not this lane's",
        )
    actor = flat.get("actorAccountId", "")
    if actor and not (_owner_ids(actor) & subs):
        return "keep", f"inventory row in lane Unit Campaign {campaign} written by {actor}, not a fixture identity"
    if flat.get("entityType") == "InventoryMovement" or "#MOVEMENT#" in flat.get("sk", ""):
        return (
            "keep",
            f"append-only inventory movement history in lane Unit Campaign {campaign}: immutable audit record, "
            "reported as history this sweep does not delete",
        )
    what = flat.get("entityType") or flat.get("sk", "").split("#")[-1]
    return "delete", f"inventory {what} row in lane Unit Campaign {campaign}"


def _rule_orders(item: dict[str, Any], tokens: dict[str, set[str]]) -> tuple[str, str] | None:
    """``{campaignId, orderId}``: an Order is the lane's when its campaign or its id is named."""
    flat = _strings(item)
    campaign = _bare(flat.get("campaignId", ""), "CAMPAIGN")
    order = flat.get("orderId", "")
    if campaign not in tokens["campaign"] and order not in tokens["order"]:
        return None
    profile = _bare(flat.get("profileId", ""), "PROFILE")
    if profile and profile not in tokens["profile"]:
        return "keep", f"Order {order} on campaign {campaign} belongs to profile {profile}, not named by this lane"
    return "delete", f"Order row of lane Scout Campaign {campaign} ({order})"


def _rule_fulfillments(item: dict[str, Any], tokens: dict[str, set[str]]) -> tuple[str, str] | None:
    """``pk`` is the Order's fulfillment partition; a lane Order owns its whole partition."""
    flat = _strings(item)
    pk = flat.get("pk", "")
    order = pk if pk.startswith("ORDER#") else ""
    campaign = _bare(flat.get("campaignId", ""), "CAMPAIGN")
    if order not in tokens["order"] and campaign not in tokens["campaign"]:
        return None
    return "delete", f"fulfillment row of lane Order {_mask_secret(order or campaign)}"


def _lane_rule(label: str, item: dict[str, Any], tokens: dict[str, set[str]], subs: set[str]) -> tuple[str, str] | None:
    """Whether one row belongs to this lane, and why — or why a lane token is not enough to delete it.

    Every key shape an acceptance lane writes has its own rule here, written against the builders
    that mint it.  A row a lane token names whose shape no rule describes comes back as ``keep``:
    visible in the record, never deleted, and never counted as a clean sweep.
    """
    if label == "accounts":
        return None  # identities outlive a lane sweep: the next run needs them
    if label == "units":
        return _rule_units(item, tokens, subs)
    if label == "unit-campaigns":
        return _rule_unit_campaigns(item, tokens, subs)
    if label == "inventory":
        return _rule_inventory(item, tokens, subs)
    if label == "orders":
        return _rule_orders(item, tokens)
    if label == "order-fulfillments":
        return _rule_fulfillments(item, tokens)
    return None


def owned_rows(d: Any, subs: Iterable[str]) -> tuple[list[tuple[str, str, dict[str, str], str]], list[tuple[str, str]]]:
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
                found = _attribution(item, key_names, owner_attr, wanted, mails)
                if found is None:
                    flat = _flatten(item)
                    skipped.append((label, "/".join(flat.get(k, "") for k in key_names)))
                else:
                    rows.append(found)
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


def _scan_lane_rows(
    d: Any, label: str, table: str, tokens: dict[str, set[str]], subs: set[str]
) -> list[tuple[dict[str, str], str, str]]:
    """Every row in one table a lane token names, with its decision and the rule that decided it.

    The scan does not filter on attribution first: a row the lane owns but that names no fixture
    identity (a balance, a custody row, a join-code pointer) is exactly what a lane leaves behind,
    and the residue report has to show it whether or not the delete took it.
    """
    key_names = SWEEP_TABLES[label][1]
    hits: list[tuple[dict[str, str], str, str]] = []
    scan_kw: dict[str, Any] = {"TableName": table, "ConsistentRead": False}
    while True:
        page = d.scan(**scan_kw)
        for item in page.get("Items", []):
            found = _lane_rule(label, item, tokens, subs)
            if found is None:
                continue
            decision, reason = found
            flat = _strings(item)
            hits.append(({k: flat.get(k, "") for k in key_names}, decision, reason))
        if "LastEvaluatedKey" not in page:
            return hits
        scan_kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def sweep_lane_rows(d: Any, subs: Iterable[str], tokens: dict[str, set[str]], out: TextIO) -> int:
    """Delete one acceptance lane's rows by rule, then re-scan and report every lane row left.

    A row is deleted only when a reviewed rule for its key shape says it belongs to this lane, so
    the sweep neither depends on the row carrying a fixture identity nor reaches rows the rules do
    not describe.  The read-back re-applies the same rules and prints:

    ``LEFT``     a lane row the delete did not take — a failure;
    ``kept``     a row a lane token names that the rules refuse to delete — a third party's grant or
                 membership on a lane partition, a foreign custody row, a guard whose Scout Campaign
                 is not named exactly, a marker no fixture identity wrote, or the lane's own
                 append-only movement history.  Every one is reported, and the first four are the
                 proof that another tenant's data survives;
    ``BLOCKED``  a table this identity cannot read, named with the action it is denied — its lane
                 rows are neither removed nor proven absent, so the sweep fails.

    The identities are never touched: ``sweep_lane_rows`` is not even given the Cognito client.
    """
    wanted = {s for s in subs if s}
    if not wanted:
        print("sweep: no fixture subs to attribute rows to; nothing deleted", file=out)
        return 1
    named = sum(len(values) for values in tokens.values())
    if not named:
        print(
            "sweep: refusing to run without a typed --lane <kind>=<value> token; an unbounded "
            "sweep would reach another run's rows",
            file=out,
        )
        return 1

    plan: list[tuple[str, str, dict[str, str], str]] = []
    kept: list[str] = []
    blocked: list[str] = []
    denied: list[str] = []
    scanned: list[str] = []
    for label, (table, _key_names, _owner_attr) in SWEEP_TABLES.items():
        try:
            found = _scan_lane_rows(d, label, table, tokens, wanted)
        except Exception as exc:  # noqa: BLE001 - a denied scan is reported, never treated as empty
            blocked.append(_blocked_line(table, exc))
            denied.append(f"{table}: {_denied_action(exc)}")
            continue
        scanned.append(f"reach {table:<34} scanned, {len(found)} row(s) named by these tokens")
        for key_vals, decision, reason in found:
            key = _mask_secret("/".join(key_vals.values()))
            if decision == "delete":
                plan.append((label, key, dict(key_vals), reason))
            else:
                kept.append(f"kept   {label:<18} {key}  [{reason}]")

    print(f"plan: sweep {named} lane token(s) over {len(SWEEP_TABLES)} table(s)", file=out)
    for line in scanned:
        print(f"  {line}", file=out)
    for line in blocked:
        print(f"  {line}", file=out)
    for label, key, _key_doc, reason in plan:
        print(f"  row    {label:<18} {key}  [{reason}]", file=out)
    for line in kept:
        print(f"  {line}", file=out)
    if not plan:
        print("  row    (no row names these lane tokens in a shape a rule deletes)", file=out)

    failures = 0
    for label, key, key_doc, _reason in plan:
        table = SWEEP_TABLES[label][0]
        try:
            d.delete_item(TableName=table, Key={k: {"S": v} for k, v in key_doc.items()})
            print(f"  deleted row  {label:<18} {key}", file=out)
        except Exception as exc:  # noqa: BLE001 - report each row, keep sweeping the rest
            failures += 1
            print(f"  FAILED row   {label:<18} {key}  {type(exc).__name__}", file=out)

    # Read-back: a delete_item that returned without an error is not evidence on its own.
    for label, (table, _key_names, _owner_attr) in SWEEP_TABLES.items():
        if any(line.startswith(f"BLOCKED {table}") for line in blocked):
            continue
        try:
            still = _scan_lane_rows(d, label, table, tokens, wanted)
        except Exception as exc:  # noqa: BLE001 - the read-back failing is itself a finding
            failures += 1
            print(f"  FAILED scan  {table}  {type(exc).__name__}", file=out)
            continue
        for key_vals, decision, reason in still:
            key = _mask_secret("/".join(key_vals.values()))
            if decision == "delete":
                failures += 1
                print(f"  LEFT   {label:<18} {key}  [{reason}]", file=out)
    if kept:
        print(
            f"  {len(kept)} row(s) a lane token names are deliberately left: another tenant's row on a "
            "lane partition, a row whose identity no token names exactly, or append-only history",
            file=out,
        )
    if blocked:
        print(
            f"  {len(blocked)} table(s) could not be read by this identity ({'; '.join(denied)}): their "
            "lane rows are neither removed nor proven absent, and the permission named there is what to ask for",
            file=out,
        )
    if failures or blocked:
        return 1
    print(
        f"  swept {len(plan)} row(s); a re-scan finds no row these rules call this lane's",
        file=out,
    )
    return 0


def main(argv: list[str], out: TextIO = sys.stdout) -> int:
    action = argv[1] if len(argv) > 1 else "status"
    if action not in {"status", "up", "down", "sweep"}:
        print(__doc__, file=out)
        return 2
    cognito = cip()
    if action == "status":
        render_status(cognito, out)
        return 0
    if action == "sweep":
        raw_tokens = tuple(v for i, v in enumerate(argv) if i > 1 and argv[i - 1] == "--lane" and v)
        tokens, problems = parse_lane_tokens(raw_tokens)
        for problem in problems:
            print(f"sweep: refused — {problem}", file=out)
        if problems:
            return 2
        if not any(tokens.values()):
            print(
                "sweep: pass at least one --lane <kind>=<value> token "
                f"({', '.join(sorted(TOKEN_SHAPES))}); an unbounded sweep would reach another run's rows",
                file=out,
            )
            return 2
        if "--yes" not in argv:
            print("sweep: refusing to delete without --yes (this sweep is not interactive)", file=out)
            return 2
        have = pool_users(cognito)
        subs = {s for s in (_attrs(have[m]).get("sub") for m in emails().values() if m in have) if s}
        return sweep_lane_rows(ddb(), subs, tokens, out)
    if action == "up":
        values = apply_up(cognito, out)
        sign_in_proof(cognito, values, out)
        render_status(cognito, out)
        return 0
    return apply_down(cognito, ddb(), "--yes" in argv, out)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
