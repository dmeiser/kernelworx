"""Tests for ``scripts/qa_fixture.py`` — the Show & Sell QA login fixture.

The script is the only supported way to put a signed-in identity on the dev
stack, so the properties that matter are pinned here against a stubbed boto3
client (no AWS access, no real pool):

* ``up`` is idempotent — an existing user is refreshed, not re-created, and a
  pool that already holds the fixture ends with exactly four identities.
* The ``show-sell-preview`` shape is re-asserted on every ``up``: admin, admin2
  and scout go in, ``outside`` stays out. The join step of the Stage 1 journey
  needs the scout in the group, and the closed half of the gate needs exactly
  one identity held out, so a membership that drifted is corrected in both
  directions rather than inherited.
* ``down`` deletes only rows a fixture ``sub`` owns, and reports every row it
  cannot attribute instead of deleting it.
* ``status`` renders a pool with no users, no group members and no strays.
* No generated password ever reaches stdout — the pool is public-facing and the
  repository is public, so a printed credential is a published credential.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List

import pytest

SCRIPT_REL = Path("scripts") / "qa_fixture.py"


# --------------------------------------------------------------------------- #
# Stub clients
# --------------------------------------------------------------------------- #


class CognitoError(Exception):
    """Base for the stub's modeled Cognito service exceptions."""


class DynamoError(Exception):
    """Base for the stub's modeled DynamoDB service exceptions."""


class DeleteRejected(DynamoError):
    """A delete call that fails mid-sweep: throttling, denied, transport."""


class UsernameExists(CognitoError):
    pass


class NotFound(CognitoError):
    pass


class StubCognito:
    """Enough of ``cognito-idp`` for the script: users, one group, one client."""

    class exceptions:  # noqa: N801 - mirrors the boto3 client's attribute
        UsernameExistsException = UsernameExists
        ResourceNotFoundException = NotFound

    def __init__(
        self,
        users: List[Dict[str, Any]] | None = None,
        group: List[str] | None = None,
        clients: List[Dict[str, str]] | None = None,
        pages: int = 1,
        fail_delete: List[str] | None = None,
    ) -> None:
        self.users: Dict[str, Dict[str, Any]] = {u["email"]: u for u in (users or [])}
        self.group = set(group or [])
        self.clients = clients or [{"ClientId": "client-real", "ClientName": "KernelWorx-Web"}]
        self.pages = pages
        self.calls: List[str] = []
        self.deleted: List[str] = []
        self.passwords: Dict[str, str] = {}
        self.fail_delete = set(fail_delete or [])

    # -- reads ------------------------------------------------------------- #

    def list_users(self, **kw: Any) -> Dict[str, Any]:
        """Serve ``pages`` pages before the users appear, then stop paginating."""
        if self.pages > 1:
            self.pages -= 1
            return {"Users": [], "PaginationToken": f"page-{self.pages}"}
        return {"Users": [self._record(m) for m in self.users]}

    def list_users_in_group(self, **_: Any) -> Dict[str, Any]:
        return {"Users": [self._record(m) for m in self.group]}

    def list_user_pool_clients(self, **_: Any) -> Dict[str, Any]:
        return {"UserPoolClients": list(self.clients)}

    # -- writes ------------------------------------------------------------ #

    def admin_create_user(self, *, Username: str, **_: Any) -> None:
        if Username in self.users:
            self.calls.append(f"create-duplicate:{Username}")
            raise UsernameExists
        self.calls.append(f"create:{Username}")
        self.users[Username] = {"email": Username, "sub": f"sub-{Username}", "status": "UNCONFIRMED"}

    def admin_set_user_password(self, *, Username: str, Password: str, **_: Any) -> None:
        self.calls.append(f"set-password:{Username}")
        self.passwords[Username] = Password

    def admin_update_user_attributes(self, *, Username: str, **_: Any) -> None:
        self.calls.append(f"attrs:{Username}")

    def admin_add_user_to_group(self, *, Username: str, **_: Any) -> None:
        self.calls.append(f"add-group:{Username}")
        self.group.add(Username)

    def admin_remove_user_from_group(self, *, Username: str, **_: Any) -> None:
        self.calls.append(f"remove-group:{Username}")
        if Username not in self.group:
            raise NotFound
        self.group.discard(Username)

    def admin_user_global_sign_out(self, *, Username: str, **_: Any) -> None:
        self.calls.append(f"sign-out:{Username}")

    def admin_delete_user(self, *, Username: str, **_: Any) -> None:
        self.calls.append(f"delete-user:{Username}")
        if Username in self.fail_delete:
            raise DeleteRejected("access denied")
        self.deleted.append(Username)
        self.users.pop(Username, None)

    def initiate_auth(self, *, ClientId: str, AuthParameters: Dict[str, str], **_: Any) -> Dict[str, Any]:
        self.calls.append(f"auth:{ClientId}")
        if ClientId != "client-real":
            raise NotFound("USER_PASSWORD_AUTH flow not enabled for this client")
        mail = AuthParameters["USERNAME"]
        if self.passwords.get(mail) != AuthParameters["PASSWORD"]:
            raise NotFound("wrong password")
        groups = [m for m in self.group if m == mail]
        return {"AuthenticationResult": {"IdToken": self._id_token(mail, groups)}}

    # -- helpers ----------------------------------------------------------- #

    def _record(self, mail: str) -> Dict[str, Any]:
        u = self.users[mail]
        return {
            "Username": f"uuid-{mail}",  # stored Username is the UUID sub, not the address
            "UserStatus": u.get("status", "CONFIRMED"),
            "Attributes": [
                {"Name": "email", "Value": mail},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "sub", "Value": u["sub"]},
            ],
        }

    @staticmethod
    def _id_token(mail: str, groups: List[str]) -> str:
        import base64

        payload = {"email": mail, "cognito:groups": groups, "mfa": False}
        blob = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        return f"header.{blob}.sig"


class StubDynamo:
    """Enough of ``dynamodb`` to exercise the sweep's attribution and failure rules."""

    def __init__(
        self,
        tables: Dict[str, List[Dict[str, Any]]],
        fail_keys: Dict[str, List[Dict[str, str]]] | None = None,
    ) -> None:
        self.tables = tables
        self.deleted: List[tuple[str, Dict[str, str]]] = []
        self.fail_keys = fail_keys or {}

    def scan(self, *, TableName: str, **_: Any) -> Dict[str, Any]:
        return {"Items": list(self.tables.get(TableName, []))}

    def delete_item(self, *, TableName: str, Key: Dict[str, Any]) -> None:
        key = {k: v["S"] for k, v in Key.items()}
        for bad in self.fail_keys.get(TableName, []):
            if bad == key:
                # One-shot: a throttle or denied call is transient, so the retry works.
                self.fail_keys[TableName].remove(bad)
                raise DeleteRejected("ThrottlingException")
        self.deleted.append((TableName, key))
        # A real table forgets the row, so a second ``down`` sees only what is left.
        self.tables[TableName] = [
            item for item in self.tables.get(TableName, []) if {k: item[k]["S"] for k in key} != key
        ]


def _s(value: str) -> Dict[str, Any]:
    return {"S": value}


def _item(**attrs: str) -> Dict[str, Any]:
    return {k: _s(v) for k, v in attrs.items()}


@pytest.fixture
def mod() -> ModuleType:
    assert SCRIPT_REL.is_file(), f"{SCRIPT_REL} must exist for the fixture script to be supported"
    spec = importlib.util.spec_from_file_location("qa_fixture", SCRIPT_REL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_users(mod: ModuleType) -> List[Dict[str, Any]]:
    return [{"email": f"{local}@{mod.DOMAIN}", "sub": f"sub-{local}", "status": "CONFIRMED"} for local in mod.IDENTS]


# --------------------------------------------------------------------------- #
# up — idempotent
# --------------------------------------------------------------------------- #


def test_up_creates_missing_identities_and_sets_the_group(mod: ModuleType, tmp_path: Path) -> None:
    c = StubCognito()
    out = io.StringIO()
    values = mod.apply_up(c, out, secrets_file=str(tmp_path / "secrets.json"))

    for local in mod.IDENTS:
        mail = f"{local}@{mod.DOMAIN}"
        assert c.calls.count(f"create:{mail}") == 1
        assert c.calls.count(f"set-password:{mail}") == 1
    assert c.group == {
        f"qa-show-sell-admin@{mod.DOMAIN}",
        f"qa-show-sell-admin2@{mod.DOMAIN}",
        f"qa-show-sell-scout@{mod.DOMAIN}",
    }
    assert values["TEST_QA_SHOW_SELL_BASE_URL"] == "https://dev.kernelworx.app"
    assert len(values) == 1 + 2 * len(mod.IDENTS)


def test_up_is_idempotent_when_the_users_already_exist(mod: ModuleType, tmp_path: Path) -> None:
    c = StubCognito(users=_fixture_users(mod), group=[f"qa-show-sell-admin@{mod.DOMAIN}"])
    out = io.StringIO()
    mod.apply_up(c, out, secrets_file=str(tmp_path / "secrets.json"))

    for local in mod.IDENTS:
        mail = f"{local}@{mod.DOMAIN}"
        assert f"create:{mail}" not in c.calls, "an existing identity must not be re-created"
        assert c.calls.count(f"create-duplicate:{mail}") == 1, "the refresh path must be taken"
        assert c.calls.count(f"set-password:{mail}") == 1
    assert "refreshed" in out.getvalue()
    assert len(c.users) == len(mod.IDENTS), "re-running up must not add a fifth identity"
    # Membership is re-asserted in both directions: a scout that drifted out is
    # put back (the journey's join step needs it), and outside is asserted out so
    # the closed half of the gate always has an identity to prove it with.
    assert f"add-group:qa-show-sell-scout@{mod.DOMAIN}" in c.calls
    assert f"remove-group:qa-show-sell-outside@{mod.DOMAIN}" in c.calls
    assert not any(call.startswith("remove-group:qa-show-sell-scout") for call in c.calls)
    assert c.group == {
        f"qa-show-sell-admin@{mod.DOMAIN}",
        f"qa-show-sell-admin2@{mod.DOMAIN}",
        f"qa-show-sell-scout@{mod.DOMAIN}",
    }


def test_up_writes_a_readable_secrets_file_outside_the_repo(mod: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "nested" / "secrets.json"
    c = StubCognito()
    mod.apply_up(c, io.StringIO(), secrets_file=str(path))

    mode = path.stat().st_mode & 0o777
    assert mode == 0o600, f"secrets file must be 0600, got {oct(mode)}"
    payload = json.loads(path.read_text())
    assert set(payload) >= {
        "TEST_QA_SHOW_SELL_ADMIN_EMAIL",
        "TEST_QA_SHOW_SELL_ADMIN2_EMAIL",
        "TEST_QA_SHOW_SELL_SCOUT_EMAIL",
        "TEST_QA_SHOW_SELL_OUTSIDE_EMAIL",
    }


def test_no_password_ever_reaches_stdout(mod: ModuleType, tmp_path: Path) -> None:
    """Behavioral gate: every verb's output is checked against every password."""
    c = StubCognito(users=_fixture_users(mod))
    secrets_file = str(tmp_path / "secrets.json")
    captured = io.StringIO()

    values = mod.apply_up(c, captured, secrets_file=secrets_file)
    mod.sign_in_proof(c, values, captured)
    mod.render_status(c, captured)
    code = mod.apply_down(c, StubDynamo({}), assume_yes=True, out=captured, secrets_file=secrets_file)

    printed = captured.getvalue()
    assert code == 0
    assert not c.deleted or code == 0
    for mail, pw in c.passwords.items():
        assert mail in printed, f"the address {mail} may be printed; the password may not"
        assert pw not in printed, "a generated password reached stdout"
    assert "PASSWORD" not in printed


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #


def test_status_renders_an_empty_pool(mod: ModuleType) -> None:
    c = StubCognito()
    out = io.StringIO()
    mod.render_status(c, out)
    text = out.getvalue()

    assert "members: none" in text
    for local in mod.IDENTS:
        assert f"{local}@{mod.DOMAIN}" in text
    assert text.count("ABSENT") == len(mod.IDENTS)
    assert "users total=0  leaked strays=0" in text


def test_status_reports_membership_and_strays(mod: ModuleType) -> None:
    c = StubCognito(
        users=_fixture_users(mod)
        + [
            {"email": "e2e-signup-dead@example.com", "sub": "s1", "status": "UNCONFIRMED"},
            {"email": "qa-wave2-ab12@fldubai.com", "sub": "s2", "status": "UNCONFIRMED"},
        ],
        group=[f"qa-show-sell-admin@{mod.DOMAIN}"],
        clients=[
            {"ClientId": "a", "ClientName": "KernelWorx-Web"},
            {"ClientId": "b", "ClientName": "KernelWorx-Web"},
        ],
    )
    out = io.StringIO()
    mod.render_status(c, out)
    text = out.getvalue()

    assert "preview=yes" in text and "preview=no" in text
    assert "app clients named KernelWorx-Web: 2 of 2" in text
    assert "leaked strays=2" in text
    assert "e2e-signup-dead@example.com" in text and "qa-wave2-ab12@fldubai.com" in text


def test_pool_users_follows_the_pagination_token(mod: ModuleType) -> None:
    """A truncated read would report a fixture that exists as ABSENT."""
    c = StubCognito(users=_fixture_users(mod), pages=3)
    assert len(mod.pool_users(c)) == len(mod.IDENTS)


# --------------------------------------------------------------------------- #
# down — attribution rules
# --------------------------------------------------------------------------- #


def _rows() -> Dict[str, List[Dict[str, Any]]]:
    return {
        "kernelworx-accounts-ue1-dev": [
            _item(accountId="ACCOUNT#sub-admin"),
            _item(accountId="ACCOUNT#someone-else"),
        ],
        "kernelworx-units-ue1-dev": [
            _item(pk="UNIT#u1", sk="META", createdByAccountId="ACCOUNT#sub-admin"),
            _item(pk="UNIT#u1", sk="ROLE#qa-show-sell-admin@dev.kernelworx.app"),
            _item(pk="UNIT#u1", sk="ROLE#someone-else@example.com"),
            _item(pk="UNIT#u9", sk="META", createdByAccountId="ACCOUNT#someone-else"),
            _item(pk="IDEM#sub-admin#createUnit#BOOTSTRAP", sk="IDEM#req-1"),
            _item(pk="IDEM#someone-else#createUnit#BOOTSTRAP", sk="IDEM#req-2"),
        ],
        "kernelworx-unit-campaigns-ue1-dev": [
            _item(pk="UNIT#u1", sk="CAMPAIGN#c1", createdByAccountId="ACCOUNT#sub-admin"),
            _item(pk="UNIT#u9", sk="CAMPAIGN#c9", createdByAccountId="ACCOUNT#someone-else"),
            _item(pk="UNIT#u9", sk="GRANT#ACCOUNT#sub-admin"),
        ],
    }


def test_down_deletes_only_fixture_owned_rows(mod: ModuleType) -> None:
    users = _fixture_users(mod)
    users[0]["sub"] = "sub-admin"
    c = StubCognito(users=users, group=[f"qa-show-sell-admin@{mod.DOMAIN}"])
    d = StubDynamo(_rows())
    out = io.StringIO()

    code = mod.apply_down(c, d, assume_yes=True, out=out, secrets_file="does-not-exist.json")
    text = out.getvalue()

    assert code == 0
    assert sorted(c.deleted) == sorted(mod.emails().values())
    deleted = {(t, k["pk"] if "pk" in k else k["accountId"]) for t, k in d.deleted}
    assert ("kernelworx-accounts-ue1-dev", "ACCOUNT#sub-admin") in deleted
    assert ("kernelworx-units-ue1-dev", "UNIT#u1") in deleted
    assert ("kernelworx-unit-campaigns-ue1-dev", "UNIT#u1") in deleted
    for _t, key in d.deleted:
        assert "someone-else" not in key.values() and "u9" not in key.values()
    assert "plan: delete 4 fixture users" in text
    assert "sweep  tables: accounts, units, unit-campaigns" in text, "the sweep's coverage must be visible"
    assert text.index("plan:") < text.index("deleted user"), "the plan must precede the write"
    assert text.index("deleted row") < text.index("deleted user"), "rows go before the users they depend on"


def test_a_key_naming_a_fixture_identity_is_attributable(mod: ModuleType) -> None:
    """``GRANT#ACCOUNT#<sub>`` and ``ROLE#<fixture address>`` are fixture rows.

    A global ``ACCOUNT#`` strip turns ``GRANT#ACCOUNT#<sub>`` into
    ``GRANT#<sub>``, which matches nothing and silently leaves the row behind.
    """
    users = _fixture_users(mod)
    users[0]["sub"] = "sub-admin"
    c = StubCognito(users=users)
    d = StubDynamo(_rows())

    mod.apply_down(c, d, assume_yes=True, out=io.StringIO(), secrets_file="does-not-exist.json")
    deleted = {(t, k.get("sk") or k.get("accountId")) for t, k in d.deleted}

    assert ("kernelworx-unit-campaigns-ue1-dev", "GRANT#ACCOUNT#sub-admin") in deleted
    assert ("kernelworx-units-ue1-dev", "ROLE#qa-show-sell-admin@dev.kernelworx.app") in deleted


def test_a_third_party_row_on_a_fixture_partition_is_never_deleted(mod: ModuleType) -> None:
    """Sharing a partition key with a fixture row is not attribution.

    ``UNIT#u1/ROLE#someone-else@example.com`` is another tenant's grant on a
    fixture Unit; deleting it would reach into their data, so it is reported
    and left alone.
    """
    users = _fixture_users(mod)
    users[0]["sub"] = "sub-admin"
    c = StubCognito(users=users)
    d = StubDynamo(_rows())
    out = io.StringIO()

    mod.apply_down(c, d, assume_yes=True, out=out, secrets_file="does-not-exist.json")

    assert ("kernelworx-units-ue1-dev", {"pk": "UNIT#u1", "sk": "ROLE#someone-else@example.com"}) not in d.deleted
    assert "UNIT#u1/ROLE#someone-else@example.com  (not attributable to a fixture sub)" in out.getvalue()


def test_the_plan_says_which_evidence_owns_each_row(mod: ModuleType) -> None:
    """Attribution has to be checkable by the person reading the plan.

    The three shapes the rule accepts are different claims, so the plan names the
    one that selected each row — and the idempotency rows, whose only identity is
    segment 2 of the partition key, are shown for both the fixture caller and a
    stranger's.
    """
    users = _fixture_users(mod)
    users[0]["sub"] = "sub-admin"
    c = StubCognito(users=users)
    d = StubDynamo(_rows())
    out = io.StringIO()

    mod.apply_down(c, d, assume_yes=True, out=out, secrets_file="does-not-exist.json")
    text = out.getvalue()

    assert "UNIT#u1/META  [createdByAccountId names a fixture sub]" in text
    assert "ROLE#qa-show-sell-admin@dev.kernelworx.app  [key names a fixture address]" in text
    assert "GRANT#ACCOUNT#sub-admin  [key names a fixture sub]" in text
    assert "IDEM#sub-admin#createUnit#BOOTSTRAP/IDEM#req-1  [key names a fixture sub]" in text
    assert "IDEM#someone-else#createUnit#BOOTSTRAP/IDEM#req-2  [key names a fixture sub]" not in text
    assert "left   units          IDEM#someone-else#createUnit#BOOTSTRAP/IDEM#req-2" in text


def test_a_failed_row_delete_keeps_the_users_and_a_second_down_finishes(mod: ModuleType) -> None:
    """The state this script exists to prevent must not be created by the script.

    Rows are attributable only while the users exist. So a row that fails must
    not be paid for by deleting the user: the sweep reports it, keeps every
    identity, exits non-zero, and a second ``down`` re-derives the same subs and
    deletes what is left.
    """
    users = _fixture_users(mod)
    users[0]["sub"] = "sub-admin"
    c = StubCognito(users=users)
    d = StubDynamo(_rows(), fail_keys={"kernelworx-units-ue1-dev": [{"pk": "UNIT#u1", "sk": "META"}]})
    first = io.StringIO()

    code = mod.apply_down(c, d, assume_yes=True, out=first, secrets_file="does-not-exist.json")
    text = first.getvalue()

    assert code == 1, "a partial teardown must not report success"
    assert "FAILED row   units          UNIT#u1/META  DeleteRejected" in text
    assert "re-run `down` to finish" in text
    assert c.deleted == [], "no fixture user may go while its rows are still there"

    second = io.StringIO()
    code = mod.apply_down(c, d, assume_yes=True, out=second, secrets_file="does-not-exist.json")

    assert code == 0
    assert sorted(c.deleted) == sorted(mod.emails().values())
    assert ("kernelworx-units-ue1-dev", {"pk": "UNIT#u1", "sk": "META"}) in d.deleted


def test_a_failed_user_delete_is_reported_without_losing_the_rest(mod: ModuleType, tmp_path: Path) -> None:
    survivors = f"qa-show-sell-scout@{mod.DOMAIN}"
    users = _fixture_users(mod)
    c = StubCognito(users=users, fail_delete=[survivors])
    path = tmp_path / "secrets.json"
    mod.apply_up(c, io.StringIO(), secrets_file=str(path))
    out = io.StringIO()

    code = mod.apply_down(c, StubDynamo({}), assume_yes=True, out=out, secrets_file=str(path))

    assert code == 1
    assert f"FAILED user  {survivors}" in out.getvalue()
    assert len(c.deleted) == len(mod.IDENTS) - 1, "the other identities still go"
    assert survivors in c.users


def test_sweep_refuses_rows_it_cannot_attribute(mod: ModuleType) -> None:
    users = _fixture_users(mod)
    users[0]["sub"] = "sub-admin"
    c = StubCognito(users=users)
    d = StubDynamo(_rows())
    out = io.StringIO()

    mod.apply_down(c, d, assume_yes=True, out=out, secrets_file="does-not-exist.json")

    assert ("kernelworx-units-ue1-dev", {"pk": "UNIT#u9", "sk": "META"}) not in d.deleted
    assert ("kernelworx-unit-campaigns-ue1-dev", {"pk": "UNIT#u9", "sk": "CAMPAIGN#c9"}) not in d.deleted
    text = out.getvalue()
    assert "not attributable to a fixture sub" in text
    assert "UNIT#u9/META" in text and "UNIT#u9/CAMPAIGN#c9" in text


def test_sweep_without_a_sub_touches_nothing(mod: ModuleType) -> None:
    """No fixture user in the pool means no sub to attribute rows to."""
    c = StubCognito()
    d = StubDynamo(_rows())
    out = io.StringIO()

    code = mod.apply_down(c, d, assume_yes=True, out=out, secrets_file="does-not-exist.json")
    assert code == 0
    assert d.deleted == []
    assert c.deleted == []
    assert "no fixture-owned rows found" in out.getvalue()


# --------------------------------------------------------------------------- #
# sweep — one acceptance lane's rows, by lane token, identities kept
# --------------------------------------------------------------------------- #


class DeniedScanDynamo(StubDynamo):
    """A table the IAM identity cannot read at all, which is how dev answers today.

    The message is the shape DynamoDB returns for a missing grant, because the sweep report is held to
    naming the permission that is missing rather than only the fact that a read failed.
    """

    DENIED = (
        "An error occurred (AccessDeniedException) when calling the Scan operation: User: "
        "arn:aws:iam::750620721302:user/kernelworx-qa-ue1-dev is not authorized to perform: "
        "dynamodb:Scan on resource: arn:aws:dynamodb:us-east-1:750620721302:table/{table} because no "
        "identity-based policy allows the dynamodb:Scan action"
    )

    def __init__(self, tables: Dict[str, List[Dict[str, Any]]], denied: List[str], *, message: str = DENIED) -> None:
        super().__init__(tables)
        self.denied = set(denied)
        self.message = message

    def scan(self, *, TableName: str, **_: Any) -> Dict[str, Any]:
        if TableName in self.denied:
            raise ScanRejected(self.message.format(table=TableName))
        return super().scan(TableName=TableName, **_)


class ScanRejected(RuntimeError):
    """Stand-in for the ``AccessDeniedException`` dev answers on a denied table."""


# Real key shapes, taken from the builders that mint them, so a rule is tested against the row
# the application actually writes rather than a sketch of one.
_LANE = "stage2-1118140"
_LANE_UNIT = "11111111-1111-4111-8111-111111111111"
_OTHER_UNIT = "88888888-8888-4888-8888-888888888888"
_LANE_UC = "22222222-2222-4222-8222-222222222222"
_OTHER_UC = "33333333-3333-4333-8333-333333333333"
_LANE_CAMPAIGN = "44444444-4444-4444-8444-444444444444"
_OTHER_CAMPAIGN = "55555555-5555-4555-8555-555555555555"
_LANE_PROFILE = "66666666-6666-4666-8666-666666666666"
_OTHER_PROFILE = "77777777-7777-4777-8777-777777777777"
_LANE_ORDER = f"ORDER#{_LANE_CAMPAIGN}#a1b2c3d4"
_OTHER_ORDER = f"ORDER#{_OTHER_CAMPAIGN}#ff00ee11"
_LANE_CODE = "ABCD1234EFGH5678"
_OTHER_CODE = "ZZZZ9999YYYY8888"
_ADMIN_SUB = "sub-admin"
_LANE_SS = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_OTHER_SS = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _lane_tokens(mod: ModuleType) -> Dict[str, set[str]]:
    """The tokens one lane run can honestly name: its own ids, code and DATA_ID."""
    tokens, problems = mod.parse_lane_tokens(
        [
            f"data-id={_LANE}",
            f"unit={_LANE_UNIT}",
            f"unit-campaign={_LANE_UC}",
            f"campaign={_LANE_CAMPAIGN}",
            f"profile={_LANE_PROFILE}",
            f"order={_LANE_ORDER}",
            f"join-code={_LANE_CODE}",
        ]
    )
    assert not problems, problems
    return tokens


def _lane_rows(*, residue: bool = True) -> Dict[str, List[Dict[str, Any]]]:
    """Two lanes' rows and a third party's, in the shapes the Stage 2 lane writes.

    ``residue=False`` drops the two survivors that keep a sweep from reporting clean — a shape no rule
    describes and the lane's own movement history — so a test about what gets *deleted* can assert the
    exit code without re-litigating the gate.
    """
    rows = {
        "kernelworx-units-ue1-dev": [
            _item(
                pk=f"UNIT#{_LANE_UNIT}",
                sk="METADATA",
                createdByAccountId=f"ACCOUNT#{_ADMIN_SUB}",
                displayName="Stage 2 Pack stage2-1118140",
            ),
            _item(
                pk=f"UNIT#{_OTHER_UNIT}",
                sk="METADATA",
                createdByAccountId=f"ACCOUNT#{_ADMIN_SUB}",
                displayName="Stage 2 Pack stage2-1118133",
            ),
            _item(pk=f"UNIT#{_LANE_UNIT}", sk=f"GRANT#ACCOUNT#{_ADMIN_SUB}"),
            _item(pk=f"UNIT#{_LANE_UNIT}", sk="GRANT#ACCOUNT#someone-else"),
            _item(pk=f"UNIT#{_LANE_UNIT}", sk="SOMETHING#ELSE"),
        ],
        "kernelworx-unit-campaigns-ue1-dev": [
            _item(
                pk=f"UNIT_CAMPAIGN#{_LANE_UC}",
                sk="METADATA",
                campaignName="Stage 2 Stock stage2-1118140",
                createdByAccountId=f"ACCOUNT#{_ADMIN_SUB}",
            ),
            _item(
                pk=f"UNIT_CAMPAIGN#{_OTHER_UC}",
                sk="METADATA",
                campaignName="Stage 2 Stock stage2-1118133",
                createdByAccountId=f"ACCOUNT#{_ADMIN_SUB}",
            ),
            _item(pk=f"UNIT_CAMPAIGN#{_LANE_UC}", sk=f"MEMBERSHIP#PROFILE#{_LANE_PROFILE}"),
            _item(pk=f"UNIT_CAMPAIGN#{_LANE_UC}", sk=f"MEMBERSHIP#PROFILE#{_OTHER_PROFILE}"),
            _item(pk=f"SCOUT_CAMPAIGN#{_LANE_CAMPAIGN}", sk="MEMBERSHIP_GUARD"),
            _item(pk=f"SCOUT_CAMPAIGN#{_OTHER_CAMPAIGN}", sk="MEMBERSHIP_GUARD"),
            _item(
                pk=f"JOIN_CODE#{_LANE_CODE}", sk="POINTER", unitCampaignId=_LANE_UC, createdAt="2026-11-19T00:00:00Z"
            ),
            _item(
                pk=f"JOIN_CODE#{_OTHER_CODE}", sk="POINTER", unitCampaignId=_OTHER_UC, createdAt="2026-11-19T00:00:00Z"
            ),
            _item(
                pk=f"IDEM#{_ADMIN_SUB}#updateUnitCampaign#{_LANE_UC}",
                sk=f"IDEM#{_LANE}-stock-receipt",
                resultPayload='{"joinCode": "' + _LANE_CODE + '"}',
            ),
            _item(
                pk=f"IDEM#{_ADMIN_SUB}#joinUnitCampaign#{_LANE_CODE}",
                sk="IDEM#f4090f4f-1111-4111-8111-111111111111",
            ),
            # Another tenant's join attempt on this lane's code: a lane resource names it, so it is
            # reported — and it stays, because no fixture identity wrote it.
            _item(
                pk=f"IDEM#someone-else#joinUnitCampaign#{_LANE_CODE}",
                sk="IDEM#deadbeef-2222-4222-8222-222222222222",
            ),
            # A fixture marker on another run's resource: not this lane's, and not worth a line in the
            # report — the table holds every earlier run's markers.
            _item(
                pk=f"IDEM#{_ADMIN_SUB}#joinUnitCampaign#{_OTHER_CODE}",
                sk="IDEM#9b1c2d3e-3333-4333-8333-333333333333",
            ),
            {
                # A bool attribute is not something to match an id against: an earlier shape of the
                # matcher raised TypeError here, which read as a denied table.
                "pk": _s(f"UNIT_CAMPAIGN#{_OTHER_UC}"),
                "sk": _s("METADATA"),
                "isActive": {"BOOL": False},
                "createdByAccountId": _s(f"ACCOUNT#{_ADMIN_SUB}"),
            },
        ],
        "kernelworx-inventory-ue1-dev": [
            # The two shapes attribution cannot see: no owner attribute anywhere on the row.
            _item(
                pk=f"UNIT_CAMPAIGN#{_LANE_UC}",
                sk="PRODUCT#p1#BALANCE",
                entityType="InventoryBalance",
                unitCampaignId=_LANE_UC,
                productId="PRODUCT#p1",
            ),
            _item(
                pk=f"UNIT_CAMPAIGN#{_LANE_UC}",
                sk=f"PRODUCT#p1#CUSTODY#PROFILE#{_LANE_PROFILE}",
                entityType="ScoutCustodyBalance",
                unitCampaignId=_LANE_UC,
                productId="PRODUCT#p1",
                profileId=f"PROFILE#{_LANE_PROFILE}",
                campaignId=f"CAMPAIGN#{_LANE_CAMPAIGN}",
            ),
            _item(
                pk=f"UNIT_CAMPAIGN#{_LANE_UC}",
                sk=f"PRODUCT#p1#CUSTODY#PROFILE#{_OTHER_PROFILE}",
                entityType="ScoutCustodyBalance",
                unitCampaignId=_LANE_UC,
                profileId=f"PROFILE#{_OTHER_PROFILE}",
            ),
            _item(
                pk=f"UNIT_CAMPAIGN#{_LANE_UC}",
                sk="PRODUCT#p1#MOVEMENT#2026-11-19T00:00:00Z#m1",
                entityType="InventoryMovement",
                actorAccountId=f"ACCOUNT#{_ADMIN_SUB}",
            ),
            _item(
                pk=f"UNIT_CAMPAIGN#{_LANE_UC}",
                sk="PRODUCT#p1#MOVEMENT#2026-11-19T00:00:01Z#m2",
                entityType="InventoryMovement",
                actorAccountId="ACCOUNT#someone-else",
            ),
            _item(pk=f"UNIT_CAMPAIGN#{_OTHER_UC}", sk="PRODUCT#p1#BALANCE", entityType="InventoryBalance"),
        ],
        "kernelworx-orders-ue1-dev": [
            _item(
                campaignId=f"CAMPAIGN#{_LANE_CAMPAIGN}",
                orderId=_LANE_ORDER,
                profileId=f"PROFILE#{_LANE_PROFILE}",
            ),
            _item(campaignId=f"CAMPAIGN#{_OTHER_CAMPAIGN}", orderId=_OTHER_ORDER),
        ],
        "kernelworx-order-fulfillments-ue1-dev": [
            _item(pk=_LANE_ORDER, sk="FULFILLMENT#2026-11-19T00:00:02Z#f1", campaignId=f"CAMPAIGN#{_LANE_CAMPAIGN}"),
            _item(pk=_OTHER_ORDER, sk="FULFILLMENT#2026-11-19T00:00:03Z#f2", campaignId=f"CAMPAIGN#{_OTHER_CAMPAIGN}"),
        ],
        "kernelworx-accounts-ue1-dev": [_item(accountId=f"ACCOUNT#{_ADMIN_SUB}")],
    }
    if not residue:
        rows["kernelworx-units-ue1-dev"] = [
            item for item in rows["kernelworx-units-ue1-dev"] if item["sk"]["S"] != "SOMETHING#ELSE"
        ]
        rows["kernelworx-inventory-ue1-dev"] = [
            item
            for item in rows["kernelworx-inventory-ue1-dev"]
            if not item["sk"]["S"].startswith("PRODUCT#p1#MOVEMENT#2026-11-19T00:00:00Z")
        ]
    return rows


def _survivors(d: StubDynamo) -> set[str]:
    """Every row still in the stub, addressed by whatever key pair that table uses."""
    survivors: set[str] = set()
    for table, items in d.tables.items():
        for item in items:
            parts = [
                value["S"] for name in ("pk", "sk", "campaignId", "orderId", "accountId") if (value := item.get(name))
            ]
            survivors.add(f"{table}/{'/'.join(parts)}")
    return survivors


def test_sweep_removes_lane_rows_that_carry_no_fixture_identity(mod: ModuleType) -> None:
    """The shapes attribution cannot see are the ones a lane leaves behind, so they are swept by rule.

    An inventory balance or custody row names no account at all (only a movement row carries
    ``actorAccountId``), and a join-code pointer carries only ``unitCampaignId`` and a timestamp.
    A membership guard carries neither, and is taken back by its exact Scout Campaign id.  Each is
    removed by the rule for its key shape; the movement row in the same partition is the one lane row
    the rule deliberately does not remove, which the test below holds it to.
    """
    d = StubDynamo(_lane_rows())
    out = io.StringIO()

    code = mod.sweep_lane_rows(d, {_ADMIN_SUB}, _lane_tokens(mod), out)
    deleted = {(t, tuple(sorted(k.items()))) for t, k in d.deleted}
    text = out.getvalue()

    assert code == 1, (
        "this fixture holds the lane's own movement history and a shape no rule describes, and a sweep "
        "that could not attribute everything it named never reports clean"
    )
    assert (
        "kernelworx-inventory-ue1-dev",
        (("pk", f"UNIT_CAMPAIGN#{_LANE_UC}"), ("sk", "PRODUCT#p1#BALANCE")),
    ) in deleted
    assert (
        "kernelworx-inventory-ue1-dev",
        (("pk", f"UNIT_CAMPAIGN#{_LANE_UC}"), ("sk", f"PRODUCT#p1#CUSTODY#PROFILE#{_LANE_PROFILE}")),
    ) in deleted
    assert (
        "kernelworx-unit-campaigns-ue1-dev",
        (("pk", f"JOIN_CODE#{_LANE_CODE}"), ("sk", "POINTER")),
    ) in deleted
    assert (
        "kernelworx-unit-campaigns-ue1-dev",
        (("pk", f"SCOUT_CAMPAIGN#{_LANE_CAMPAIGN}"), ("sk", "MEMBERSHIP_GUARD")),
    ) in deleted
    assert (
        "kernelworx-orders-ue1-dev",
        (("campaignId", f"CAMPAIGN#{_LANE_CAMPAIGN}"), ("orderId", _LANE_ORDER)),
    ) in deleted
    assert (
        "kernelworx-order-fulfillments-ue1-dev",
        (("pk", _LANE_ORDER), ("sk", "FULFILLMENT#2026-11-19T00:00:02Z#f1")),
    ) in deleted
    assert "inventory InventoryBalance row in lane Unit Campaign" in text
    assert "join-code pointer for lane Unit Campaign" in text
    assert "active-join guard" in text


def test_sweep_reports_every_lane_token_match_and_deletes_only_its_own(mod: ModuleType) -> None:
    """A lane token that names a row is never silent: it is deleted, or reported in its class.

    Third-party rows on a lane partition — another account's Unit Admin grant, another profile's
    roster membership, another profile's custody, a movement written by an account outside the
    fixture pool, another run's idempotency marker — survive as ``kept``, and the report says why each
    survived.  The lane's own movement history survives as ``HISTORY``, and a shape no rule describes
    survives as ``UNKNOWN``, and both keep the sweep from reporting clean.
    """
    d = StubDynamo(_lane_rows())
    out = io.StringIO()

    code = mod.sweep_lane_rows(d, {_ADMIN_SUB}, _lane_tokens(mod), out)
    text = out.getvalue()
    survivors = _survivors(d)

    assert code == 1
    assert f"kernelworx-units-ue1-dev/UNIT#{_OTHER_UNIT}/METADATA" in survivors
    assert f"kernelworx-unit-campaigns-ue1-dev/UNIT_CAMPAIGN#{_OTHER_UC}/METADATA" in survivors
    assert f"kernelworx-inventory-ue1-dev/UNIT_CAMPAIGN#{_OTHER_UC}/PRODUCT#p1#BALANCE" in survivors
    assert f"kernelworx-orders-ue1-dev/CAMPAIGN#{_OTHER_CAMPAIGN}/{_OTHER_ORDER}" in survivors
    assert f"kernelworx-accounts-ue1-dev/ACCOUNT#{_ADMIN_SUB}" in survivors, "identities outlive a lane"
    assert f"kernelworx-units-ue1-dev/UNIT#{_LANE_UNIT}/GRANT#ACCOUNT#someone-else" in survivors
    assert (
        f"kernelworx-unit-campaigns-ue1-dev/UNIT_CAMPAIGN#{_LANE_UC}/MEMBERSHIP#PROFILE#{_OTHER_PROFILE}" in survivors
    )
    assert (
        f"kernelworx-inventory-ue1-dev/UNIT_CAMPAIGN#{_LANE_UC}/PRODUCT#p1#CUSTODY#PROFILE#{_OTHER_PROFILE}"
        in survivors
    )
    assert (
        f"kernelworx-inventory-ue1-dev/UNIT_CAMPAIGN#{_LANE_UC}/PRODUCT#p1#MOVEMENT#2026-11-19T00:00:00Z#m1"
        in survivors
    ), "the lane's own movement trail is append-only history, never a teardown target"
    assert (
        f"kernelworx-inventory-ue1-dev/UNIT_CAMPAIGN#{_LANE_UC}/PRODUCT#p1#MOVEMENT#2026-11-19T00:00:01Z#m2"
        in survivors
    )
    assert (
        f"kernelworx-unit-campaigns-ue1-dev/IDEM#someone-else#joinUnitCampaign#{_LANE_CODE}"
        "/IDEM#deadbeef-2222-4222-8222-222222222222"
    ) in survivors
    assert (
        f"kernelworx-unit-campaigns-ue1-dev/IDEM#{_ADMIN_SUB}#joinUnitCampaign#{_OTHER_CODE}"
        "/IDEM#9b1c2d3e-3333-4333-8333-333333333333"
    ) in survivors
    assert "kept   units" in text and "not a fixture identity" in text
    assert "that profile is not this lane" in text
    assert "written by ACCOUNT#someone-else, not a fixture identity" in text
    assert "names a lane resource but no fixture identity wrote it" in text
    assert "HISTORY  inventory" in text, "history is reported as history, not as a row the sweep could not remove"
    assert "append-only inventory movement history in lane Unit Campaign" in text
    assert _OTHER_CODE not in out.getvalue(), "a marker no lane token names is not this sweep's business"
    assert "UNKNOWN  units" in text
    assert "row shape 'SOMETHING#ELSE' on lane Unit" in text, "a shape no rule describes is reported, never deleted"
    assert "5 row(s) a rule reviewed and left" in text, "another tenant's rows are the proof, and they pass"
    assert "1 row(s) a lane token names are UNRESOLVED" in text
    assert "1 row(s) of this lane's own append-only history are retained on purpose and are NOT cleaned" in text


def test_a_guard_needs_its_exact_campaign_identity(mod: ModuleType) -> None:
    """A profile token selects a person, not a Campaign, and one person holds a guard per Campaign.

    All four fixture identities are shared by every lane, so a profile token says which Scout this is
    and nothing about which of that Scout's Campaigns is joined: a profile-only prior-lane sweep would
    have deleted the guard of a Campaign another lane is still using.  ``build_membership_guard_item``
    writes one ``SCOUT_CAMPAIGN#<campaignId>/MEMBERSHIP_GUARD`` row per Scout Campaign, so the exact
    Campaign identity is what selects it, and a guard whose Campaign no token names is reported as
    unresolved and left standing.
    """
    rows = {
        "kernelworx-unit-campaigns-ue1-dev": [
            _item(
                pk=f"SCOUT_CAMPAIGN#CAMPAIGN#{_LANE_CAMPAIGN}",
                sk="MEMBERSHIP_GUARD",
                campaignId=f"CAMPAIGN#{_LANE_CAMPAIGN}",
                profileId=f"PROFILE#{_LANE_PROFILE}",
            ),
            # The same Scout's other Campaign, joined by a run whose Campaign id nobody named: the
            # profile attribute matches, and that is precisely the match that must not delete it.
            _item(
                pk=f"SCOUT_CAMPAIGN#CAMPAIGN#{_OTHER_CAMPAIGN}",
                sk="MEMBERSHIP_GUARD",
                campaignId=f"CAMPAIGN#{_OTHER_CAMPAIGN}",
                profileId=f"PROFILE#{_LANE_PROFILE}",
            ),
        ]
    }
    d = StubDynamo(rows)
    out = io.StringIO()
    tokens, problems = mod.parse_lane_tokens([f"data-id={_LANE}", f"profile={_LANE_PROFILE}"])
    assert not problems, problems

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, tokens, out) == 1, (
        "a guard nobody may be said to own is unresolved residue, not a survivor to pass over"
    )
    deleted = {tuple(sorted(k.items())) for _t, k in d.deleted}
    text = out.getvalue()

    assert deleted == set(), "no Campaign token, no guard delete"
    assert (("pk", f"SCOUT_CAMPAIGN#CAMPAIGN#{_OTHER_CAMPAIGN}"), ("sk", "MEMBERSHIP_GUARD")) not in deleted
    assert "that Campaign is not named, and one profile holds a guard per Campaign" in text
    assert "2 row(s) a lane token names are UNRESOLVED" in text


def test_a_named_campaign_takes_the_guard_its_roster_row_points_at(mod: ModuleType) -> None:
    """A prior lane's guard is still reachable: the roster row names its Campaign exactly.

    ``_sweep_prior_lanes`` reads the prior run's Unit, its Unit Campaigns and that Campaigns' roster
    through the product, so it can name the Scout Campaign ids before it deletes the profile that made
    them.  With the Campaign named, the guard ``guard_release_action`` leaves behind and the roster row
    the removal audit keeps both go; another run's Campaign on the same shared profile does not.
    """
    rows = {
        "kernelworx-unit-campaigns-ue1-dev": [
            # ``guard_key`` addresses the Scout Campaign by its stored spelling, prefix included.
            _item(
                pk=f"SCOUT_CAMPAIGN#CAMPAIGN#{_OTHER_CAMPAIGN}",
                sk="MEMBERSHIP_GUARD",
                campaignId=f"CAMPAIGN#{_OTHER_CAMPAIGN}",
                profileId=f"PROFILE#{_OTHER_PROFILE}",
            ),
            _item(
                pk=f"SCOUT_CAMPAIGN#CAMPAIGN#{_LANE_CAMPAIGN}",
                sk="MEMBERSHIP_GUARD",
                campaignId=f"CAMPAIGN#{_LANE_CAMPAIGN}",
                profileId=f"PROFILE#{_LANE_PROFILE}",
            ),
            _item(
                pk=f"UNIT_CAMPAIGN#{_OTHER_UC}",
                sk=f"MEMBERSHIP#PROFILE#{_LANE_PROFILE}",
                profileId=f"PROFILE#{_LANE_PROFILE}",
            ),
        ]
    }
    d = StubDynamo(rows)
    tokens, problems = mod.parse_lane_tokens(
        [
            f"data-id={_LANE}",
            f"unit-campaign={_OTHER_UC}",
            f"campaign={_LANE_CAMPAIGN}",
            f"profile={_LANE_PROFILE}",
        ]
    )
    assert not problems, problems

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, tokens, io.StringIO()) == 0
    deleted = {tuple(sorted(k.items())) for _t, k in d.deleted}

    assert (("pk", f"SCOUT_CAMPAIGN#CAMPAIGN#{_LANE_CAMPAIGN}"), ("sk", "MEMBERSHIP_GUARD")) in deleted
    assert (("pk", f"UNIT_CAMPAIGN#{_OTHER_UC}"), ("sk", f"MEMBERSHIP#PROFILE#{_LANE_PROFILE}")) in deleted
    assert all(_OTHER_PROFILE not in str(key) for key in deleted), "another run's guard is not this run's"


def test_the_lane_grant_and_its_own_membership_are_removed(mod: ModuleType) -> None:
    """The lane's own fixture grant and membership go; only a foreign principal survives."""
    d = StubDynamo(_lane_rows(residue=False))

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, _lane_tokens(mod), io.StringIO()) == 0
    deleted = {tuple(sorted(k.items())) for _t, k in d.deleted}

    assert (("pk", f"UNIT#{_LANE_UNIT}"), ("sk", f"GRANT#ACCOUNT#{_ADMIN_SUB}")) in deleted
    assert (("pk", f"UNIT_CAMPAIGN#{_LANE_UC}"), ("sk", f"MEMBERSHIP#PROFILE#{_LANE_PROFILE}")) in deleted


def test_a_token_naming_another_run_matches_nothing_here(mod: ModuleType) -> None:
    """One run's tokens cannot sweep another's rows, even though both use the same fixture identities."""
    d = StubDynamo(_lane_rows())
    other, problems = mod.parse_lane_tokens(
        [
            "data-id=stage2-1118133",
            f"unit={_OTHER_UNIT}",
            f"unit-campaign={_OTHER_UC}",
            f"campaign={_OTHER_CAMPAIGN}",
            f"profile={_OTHER_PROFILE}",
            f"order={_OTHER_ORDER}",
            f"join-code={_OTHER_CODE}",
        ]
    )
    assert not problems, problems

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, other, io.StringIO()) == 0
    deleted_keys = {k["pk"] if "pk" in k else k["campaignId"] for _t, k in d.deleted}

    assert _LANE_UNIT not in deleted_keys
    assert _LANE_UC not in deleted_keys
    assert all(_LANE_PROFILE not in str(k) for _t, k in d.deleted)


@pytest.mark.parametrize(
    "value",
    [
        "stage2-1118140",  # no kind: free text is what the old sweep accepted and what deleted a canary
        "unit=11111111-1111-4111-8111-11111111",  # a prefix of a real id
        "unit=111111111111111111111111111111111111",
        "data-id=ab",
        "data-id=stage2",
        "join-code=ABCD1234",
        "join-code=abcd1234efgh5678",
        "order=ORDER#44444444-4444-4444-8444-444444444444",
        "profile=PROFILE#66666666-6666-4666-8666-666666666666",
        "tenant=66666666-6666-4666-8666-666666666666",
        "id=x",
    ],
)
def test_an_ambiguous_token_is_refused_before_any_table_is_read(mod: ModuleType, value: str) -> None:
    """A destructive sweep run with ``--yes`` must not guess what a token meant."""
    tokens, problems = mod.parse_lane_tokens([value])

    assert problems, f"{value!r} should be refused"
    assert not any(tokens[kind] for kind in tokens)


def test_a_valid_token_set_is_accepted_exactly(mod: ModuleType) -> None:
    tokens, problems = mod.parse_lane_tokens(
        [
            f"data-id={_LANE}",
            f"unit={_LANE_UNIT}",
            f"unit-campaign={_LANE_UC}",
            f"campaign={_LANE_CAMPAIGN}",
            f"profile={_LANE_PROFILE}",
            f"order={_LANE_ORDER}",
            f"join-code={_LANE_CODE}",
            f"idem={_LANE}-stock-receipt",
        ]
    )

    assert not problems
    assert tokens["data-id"] == {_LANE}
    assert tokens["idem"] == {f"{_LANE}-stock-receipt"}
    assert len(tokens["unit"]) == 1


def test_a_named_idempotency_key_selects_its_marker_and_no_other(mod: ModuleType) -> None:
    """``idem`` is the narrowest marker rule: the exact key the caller used."""
    rows = {
        "kernelworx-unit-campaigns-ue1-dev": [
            _item(pk=f"IDEM#{_ADMIN_SUB}#joinUnitCampaign#{_OTHER_CODE}", sk=f"IDEM#{_LANE}-odd-key"),
            _item(
                pk=f"IDEM#{_ADMIN_SUB}#joinUnitCampaign#{_OTHER_CODE}", sk="IDEM#deadbeef-2222-4222-8222-222222222222"
            ),
        ]
    }
    d = StubDynamo(rows)
    tokens, problems = mod.parse_lane_tokens([f"idem={_LANE}-odd-key"])
    assert not problems, problems

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, tokens, io.StringIO()) == 0
    assert [k["sk"] for _t, k in d.deleted] == [f"IDEM#{_LANE}-odd-key"]


def test_a_named_idempotency_key_never_reaches_another_actors_marker(mod: ModuleType) -> None:
    """The idempotency key is caller-supplied, so naming one is not ownership of it.

    ``src/utils/mutations.py`` identifies a marker by actor + operation + scope + key, and nothing in
    the application makes that last part unique per tenant: two callers can send the same key.  The
    same key therefore selects only a marker a fixture identity wrote.  A tenant outside the fixture
    pool that happens to hold it stays, and says why.
    """
    shared_key = "deadbeef-2222-4222-8222-222222222222"
    rows = {
        "kernelworx-unit-campaigns-ue1-dev": [
            # The same caller-supplied key, two authors.
            _item(pk=f"IDEM#{_ADMIN_SUB}#joinUnitCampaign#{_LANE_CODE}", sk=f"IDEM#{shared_key}"),
            _item(pk=f"IDEM#someone-else#joinUnitCampaign#{_LANE_CODE}", sk=f"IDEM#{shared_key}"),
        ]
    }
    d = StubDynamo(rows)
    out = io.StringIO()
    tokens, problems = mod.parse_lane_tokens([f"idem={shared_key}", f"join-code={_LANE_CODE}"])
    assert not problems, problems

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, tokens, out) == 0
    text = out.getvalue()

    assert [k["pk"] for _t, k in d.deleted] == [f"IDEM#{_ADMIN_SUB}#joinUnitCampaign#{_LANE_CODE}"]
    assert (
        f"kernelworx-unit-campaigns-ue1-dev/IDEM#someone-else#joinUnitCampaign#{_LANE_CODE}/IDEM#{shared_key}"
        in _survivors(d)
    )
    assert "*" * 16 in text, "the report masks the join code in the row it names"
    assert "names a lane resource but no fixture identity wrote it" in text


def test_a_shape_no_rule_describes_fails_the_sweep_closed(mod: ModuleType) -> None:
    """A lane token names the row and no reviewed rule describes it: nothing may call that clean.

    Deleting it would be a guess about whose row it is, and passing over it is exactly how the earlier
    sweep exited 0 with rows still on the table.  So it is ``UNKNOWN`` — never deleted, and the run that
    could not attribute everything it named does not get a zero exit code.
    """
    rows = {"kernelworx-unit-campaigns-ue1-dev": [_item(pk=f"UNIT_CAMPAIGN#{_LANE_UC}", sk="REPORT#pending")]}
    d = StubDynamo(rows)
    out = io.StringIO()
    tokens, problems = mod.parse_lane_tokens([f"unit-campaign={_LANE_UC}"])
    assert not problems, problems

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, tokens, out) == 1
    text = out.getvalue()

    assert "UNKNOWN  unit-campaigns" in text
    assert "row shape 'REPORT#pending' on lane Unit Campaign" in text
    assert "1 row(s) a lane token names are UNRESOLVED" in text
    assert d.deleted == [], "a row nobody reviewed is never deleted"


def test_the_lanes_own_history_is_residue_the_gate_stays_open_on(mod: ModuleType) -> None:
    """Retained audit trail is not a third party's row, and it is not a cleanup that happened.

    The movement rows are the lane's own and the lane must not delete them, so reporting them as
    ``kept`` would put them in the same class as another tenant's grant and let a sweep exit 0 with the
    lane's writes still on the table.  They are ``HISTORY``, and the exit code stays non-zero even
    though every position row in the same partition went — which is the owner's decision to accept, not
    a flag on this command.
    """
    rows = {
        "kernelworx-inventory-ue1-dev": [
            _item(pk=f"UNIT_CAMPAIGN#{_LANE_UC}", sk="PRODUCT#p1#BALANCE", entityType="InventoryBalance"),
            _item(
                pk=f"UNIT_CAMPAIGN#{_LANE_UC}",
                sk="PRODUCT#p1#MOVEMENT#2026-11-19T00:00:00Z#m1",
                entityType="InventoryMovement",
                actorAccountId=f"ACCOUNT#{_ADMIN_SUB}",
            ),
        ]
    }
    d = StubDynamo(rows)
    out = io.StringIO()
    tokens, problems = mod.parse_lane_tokens([f"unit-campaign={_LANE_UC}"])
    assert not problems, problems

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, tokens, out) == 1
    text = out.getvalue()

    assert [k["sk"] for _t, k in d.deleted] == ["PRODUCT#p1#BALANCE"], "the position goes, the trail stays"
    assert "HISTORY  inventory" in text
    assert "kept   inventory" not in text, "the lane's own trail is not another tenant's row"
    assert "1 row(s) of this lane's own append-only history are retained on purpose and are NOT cleaned" in text


def test_only_reviewed_foreign_survivors_leave_the_sweep_clean(mod: ModuleType) -> None:
    """The other half, so the rule above is not just "any survivor is a failure".

    A lane that shares a partition with a real tenant has to be able to report a clean teardown: the
    rows a rule reviewed and attributed elsewhere survive, and that is the proof the tenant's data is
    untouched.
    """
    d = StubDynamo(_lane_rows(residue=False))
    out = io.StringIO()

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, _lane_tokens(mod), out) == 0
    text = out.getvalue()

    assert "UNKNOWN" not in text and "HISTORY" not in text
    assert "5 row(s) a rule reviewed and left" in text
    assert "a re-scan finds no row these rules call this lane" in text


def test_a_verdict_this_command_does_not_know_about_fails_closed(
    mod: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rule that answers with a fifth class must not land in the passing branch by default."""
    monkeypatch.setattr(
        mod, "_lane_rule", lambda label, item, tokens, subs: ("quarantine", "a class this command has never heard of")
    )
    d = StubDynamo({"kernelworx-units-ue1-dev": [_item(pk=f"UNIT#{_LANE_UNIT}", sk="METADATA")]})
    out = io.StringIO()

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, _lane_tokens(mod), out) == 1
    text = out.getvalue()

    assert "rule verdict 'quarantine' is not one of" in text
    assert d.deleted == []


def test_every_rule_verdict_is_a_class_the_sweep_reports(mod: ModuleType) -> None:
    """The rules and the report are one vocabulary, and a new verdict has to be registered in both."""
    import ast

    tree = ast.parse(SCRIPT_REL.read_text(encoding="utf-8"))
    verdicts: set[str] = set()
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name.startswith("_rule_")):
            continue
        for ret in ast.walk(fn):
            value = ret.value if isinstance(ret, ast.Return) else None
            if isinstance(value, ast.Tuple) and value.elts:
                first = value.elts[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    verdicts.add(first.value)

    assert {"delete", "keep", "unknown", "history"} <= verdicts, sorted(verdicts)
    assert verdicts <= set(mod.LANE_VERDICTS), (
        f"a rule returned {sorted(verdicts - set(mod.LANE_VERDICTS))}, which sweep_lane_rows cannot classify"
    )


def test_attribution_alone_never_deletes_an_inventory_row(mod: ModuleType) -> None:
    """A fixture identity in the token set is not a lane boundary in the inventory table.

    A movement row carries ``actorAccountId``, so an attribution rule could select it from a fixture
    sub alone — and an account is shared by every lane, so that rule would reach into another run's
    positions.  The inventory rule is the partition key: no ``unit-campaign`` token, no row is even
    reported, whatever else the sweep names.
    """
    d = StubDynamo(_lane_rows(residue=False))
    out = io.StringIO()
    tokens, problems = mod.parse_lane_tokens([f"data-id={_LANE}", f"unit={_LANE_UNIT}", f"profile={_LANE_PROFILE}"])
    assert not problems, problems

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, tokens, out) == 0
    assert [t for t, _k in d.deleted if t == "kernelworx-inventory-ue1-dev"] == []
    assert f"reach {'kernelworx-inventory-ue1-dev':<34} scanned, 0 row(s) named by these tokens" in out.getvalue()


def test_a_join_code_never_reaches_the_report(mod: ModuleType) -> None:
    """A pointer row is planned and deleted, and its code is masked in the same breath."""
    d = StubDynamo(_lane_rows(residue=False))
    out = io.StringIO()

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, _lane_tokens(mod), out) == 0

    assert _LANE_CODE not in out.getvalue(), "a live join code must not be pasted into an issue"


def test_the_sweep_says_which_tables_it_could_actually_read(mod: ModuleType) -> None:
    """Coverage is reported, so a sweep that could only see three tables never reads as six."""
    out = io.StringIO()
    mod.sweep_lane_rows(StubDynamo(_lane_rows()), {_ADMIN_SUB}, _lane_tokens(mod), out)
    text = out.getvalue()

    for table in mod.SWEEP_TABLES.values():
        assert f"reach {table[0]:<34} scanned" in text


def test_a_lane_row_the_delete_left_behind_fails_the_sweep(mod: ModuleType) -> None:
    """``delete_item`` returning without an error is not evidence; the re-scan is."""
    d = StubDynamo(
        _lane_rows(),
        fail_keys={"kernelworx-inventory-ue1-dev": [{"pk": f"UNIT_CAMPAIGN#{_LANE_UC}", "sk": "PRODUCT#p1#BALANCE"}]},
    )
    out = io.StringIO()

    code = mod.sweep_lane_rows(d, {_ADMIN_SUB}, _lane_tokens(mod), out)
    text = out.getvalue()

    assert code == 1
    assert "FAILED row   inventory" in text
    assert f"LEFT   inventory          UNIT_CAMPAIGN#{_LANE_UC}/PRODUCT#p1#BALANCE" in text


def test_a_table_the_identity_cannot_read_is_reported_blocked_and_the_sweep_fails(mod: ModuleType) -> None:
    """A denied ``Scan`` is a finding, not an empty table, and the report names the missing grant.

    This is the measured dev state on 2026-11-19: ``kernelworx-qa-ue1-dev`` is denied
    ``dynamodb:Scan`` on the Stage 2 inventory table, so a lane's inventory rows are neither removed
    nor proven absent.  ``sweep`` says so, names the action that is missing so the next reader knows
    what to ask for, and exits non-zero rather than reporting a clean sweep — and the grant that would
    fix it does not by itself make the sweep correct, which is what the per-shape rules above are for.
    """
    d = DeniedScanDynamo(_lane_rows(), denied=["kernelworx-inventory-ue1-dev"])
    out = io.StringIO()

    code = mod.sweep_lane_rows(d, {_ADMIN_SUB}, _lane_tokens(mod), out)
    text = out.getvalue()

    assert code == 1
    assert "BLOCKED kernelworx-inventory-ue1-dev: dynamodb:Scan is not granted to this identity" in text
    assert "1 table(s) could not be read by this identity (kernelworx-inventory-ue1-dev: dynamodb:Scan)" in text
    assert all(table != "kernelworx-inventory-ue1-dev" for table, _key in d.deleted), "a denied table is not swept"


def test_a_read_that_fails_for_another_reason_is_not_blamed_on_a_missing_grant(mod: ModuleType) -> None:
    """The action is named when DynamoDB names it, and never invented when it does not."""
    d = DeniedScanDynamo(
        _lane_rows(),
        denied=["kernelworx-orders-ue1-dev"],
        message="Could not connect to the endpoint URL: https://dynamodb.us-east-1.amazonaws.com/",
    )
    out = io.StringIO()

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, _lane_tokens(mod), out) == 1
    text = out.getvalue()

    assert "BLOCKED kernelworx-orders-ue1-dev: ScanRejected: Could not connect" in text
    assert "kernelworx-orders-ue1-dev: ScanRejected)" in text
    assert "dynamodb:Scan is not granted" not in text


def test_the_residue_scan_follows_the_page_token(mod: ModuleType) -> None:
    """A lane's rows spread over pages must all be seen, not just the first page."""

    class PagedDynamo(StubDynamo):
        def __init__(self, tables: Dict[str, List[Dict[str, Any]]]) -> None:
            super().__init__(tables)
            self.pages = 0

        def scan(self, *, TableName: str, **kwargs: Any) -> Dict[str, Any]:
            rows = self.tables.get(TableName, [])
            if not kwargs.get("ExclusiveStartKey"):
                self.pages += 1
                return {"Items": rows[:1], "LastEvaluatedKey": {"pk": "next"}} if len(rows) > 1 else {"Items": rows}
            return {"Items": rows[1:]}

    d = PagedDynamo(
        {
            "kernelworx-inventory-ue1-dev": [
                _item(pk=f"UNIT_CAMPAIGN#{_LANE_UC}", sk="PRODUCT#p1#BALANCE"),
                _item(pk=f"UNIT_CAMPAIGN#{_LANE_UC}", sk="PRODUCT#p2#BALANCE"),
            ]
        }
    )
    out = io.StringIO()

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, _lane_tokens(mod), out) == 0
    assert len(d.deleted) == 2, "both pages are swept, not only the first"


def test_sweep_refuses_an_unbounded_run_and_a_run_that_deletes_nothing(mod: ModuleType) -> None:
    """No token means no lane, and no lane means an unbounded sweep across another run's rows."""
    d = StubDynamo(_lane_rows())
    out = io.StringIO()
    empty_tokens = {kind: set() for kind in mod.TOKEN_SHAPES}

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, empty_tokens, out) == 1
    assert "refusing to run without a typed --lane" in out.getvalue()
    assert d.deleted == []

    again = io.StringIO()
    assert mod.sweep_lane_rows(StubDynamo(_lane_rows()), set(), _lane_tokens(mod), again) == 1
    assert "no fixture subs" in again.getvalue()


def test_sweep_never_touches_an_identity(mod: ModuleType) -> None:
    """A lane sweep runs with its fixture users still in place — the next run needs them.

    ``sweep_lane_rows`` is not even given the Cognito client, so it cannot delete a user by
    accident the way a shared teardown function could.
    """
    import inspect

    signature = inspect.signature(mod.sweep_lane_rows)

    assert [p.name for p in signature.parameters.values()][:2] == ["d", "subs"]
    assert "c" not in signature.parameters, "the sweeper holds no Cognito client"


def test_the_lane_token_kinds_are_the_sweepers_token_kinds(mod: ModuleType) -> None:
    """The lane's token vocabulary and the sweeper's token shapes are one list, not two that drifted.

    A kind the lane emits and the sweeper does not know is a refused run; a shape the sweeper accepts
    and the lane never emits is a class of row nobody names, which is how a sweep quietly stops being
    one.
    """
    from tests.e2e.utils import show_sell_stage2_support as stage2

    assert set(stage2.LANE_TOKEN_KINDS) <= set(mod.TOKEN_SHAPES), "the lane names a kind the sweeper refuses"
    assert set(mod.TOKEN_SHAPES) - set(stage2.LANE_TOKEN_KINDS) == {"idem", "show-and-sell"}, (
        "idem is the hand-run's narrowest form and show-and-sell the Stage 4 lane's: a lane reaches its own "
        "markers through the DATA_ID every key it sends is prefixed with, and a Stage 4 lane names its event "
        "partition by the showAndSellId it was answered — both kinds are added by the lane that emits them, "
        "so a new kind any lane must name belongs in that lane's token list too"
    )


def test_another_tenants_lane_shaped_marker_key_is_refused(mod: ModuleType) -> None:
    """A key that looks like this lane's is not this lane's unless a fixture identity wrote it.

    The ``DATA_ID`` branch of the marker rule is a prefix test, so it is the actor that keeps it
    honest: ``IDEM#someone-else#…/IDEM#stage2-1118140-try-again`` is another account's mutation.
    """
    rows = {
        "kernelworx-unit-campaigns-ue1-dev": [
            _item(pk=f"IDEM#someone-else#joinUnitCampaign#{_LANE_CODE}", sk=f"IDEM#{_LANE}-try-again"),
            _item(pk=f"IDEM#{_ADMIN_SUB}#joinUnitCampaign#{_LANE_CODE}", sk=f"IDEM#{_LANE}-mine"),
        ]
    }
    d = StubDynamo(rows)
    out = io.StringIO()

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, _lane_tokens(mod), out) == 0
    assert [k["sk"] for _t, k in d.deleted] == [f"IDEM#{_LANE}-mine"]
    assert "names a lane resource but no fixture identity wrote it" in out.getvalue()


def test_a_marker_key_segment_escaped_by_the_application_still_matches(mod: ModuleType) -> None:
    """``_escape_key_segment`` writes ``%23`` for a ``#`` inside a scope, so a prefixed id survives matching."""
    rows = {
        "kernelworx-unit-campaigns-ue1-dev": [
            _item(
                pk=f"IDEM#{_ADMIN_SUB}#createOrder#CAMPAIGN%23{_LANE_CAMPAIGN}",
                sk="IDEM#f4090f4f-1111-4111-8111-111111111111",
            ),
        ]
    }
    d = StubDynamo(rows)

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, _lane_tokens(mod), io.StringIO()) == 0
    assert [k["sk"] for _t, k in d.deleted] == ["IDEM#f4090f4f-1111-4111-8111-111111111111"]


def test_the_sweep_cli_requires_a_typed_lane_token_and_yes(mod: ModuleType) -> None:
    """``sweep`` deletes rows, so it is never interactive, never unbounded, and never free-text."""
    without_token = io.StringIO()
    assert mod.main(["qa_fixture.py", "sweep", "--yes"], out=without_token) == 2
    assert "at least one --lane" in without_token.getvalue()

    ambiguous = io.StringIO()
    assert mod.main(["qa_fixture.py", "sweep", "--lane", "stage2-1118140", "--yes"], out=ambiguous) == 2
    assert "refused" in ambiguous.getvalue()

    without_yes = io.StringIO()
    assert mod.main(["qa_fixture.py", "sweep", "--lane", f"unit={_LANE_UNIT}"], out=without_yes) == 2
    assert "--yes" in without_yes.getvalue()


def test_down_asks_before_writing_and_aborts_on_any_answer_but_yes(mod: ModuleType) -> None:
    c = StubCognito(users=_fixture_users(mod))
    d = StubDynamo(_rows())
    out = io.StringIO()

    code = mod.apply_down(c, d, assume_yes=False, out=out, confirm=lambda _p: "n", secrets_file="does-not-exist.json")
    assert code == 1
    assert c.deleted == [] and d.deleted == []
    assert "aborted" in out.getvalue()


def test_down_removes_the_secrets_file_it_wrote(mod: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    c = StubCognito()
    mod.apply_up(c, io.StringIO(), secrets_file=str(path))
    assert path.exists()

    mod.apply_down(c, StubDynamo({}), assume_yes=True, out=io.StringIO(), secrets_file=str(path))
    assert not path.exists(), "teardown must not leave credentials behind"


def test_down_removes_a_stale_secrets_file_even_with_nothing_to_delete(mod: ModuleType, tmp_path: Path) -> None:
    """An empty pool is not a reason to leave a password file on disk."""
    path = tmp_path / "secrets.json"
    path.write_text('{"TEST_QA_SHOW_SELL_ADMIN_PASSWORD": "x"}', encoding="utf-8")
    out = io.StringIO()

    code = mod.apply_down(StubCognito(), StubDynamo({}), assume_yes=True, out=out, secrets_file=str(path))

    assert code == 0
    assert "nothing to delete" in out.getvalue()
    assert not path.exists(), "the empty path still has to drop the credentials"


def test_status_never_builds_a_dynamodb_client(mod: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """``status`` is read-only on Cognito and must not need table permissions."""

    def no_dynamo() -> Any:
        raise AssertionError("status must not open a DynamoDB client")

    monkeypatch.setattr(mod, "cip", lambda: StubCognito())
    monkeypatch.setattr(mod, "ddb", no_dynamo)
    assert mod.main(["qa_fixture.py", "status"], io.StringIO()) == 0


# --------------------------------------------------------------------------- #
# entry point hygiene
# --------------------------------------------------------------------------- #


def test_passwords_never_travel_through_argv_or_the_environment(mod: ModuleType) -> None:
    """The script takes no credential argument and reads no workspace ``.env``."""
    source = SCRIPT_REL.read_text()
    for banned in ("argparse", "--password", "load_dotenv", "TEST_OWNER_PASSWORD"):
        assert banned not in source, f"{banned} must not appear: credentials are generated here"
    assert "boto3.Session()" in source, "AWS identity comes from the ambient profile"


def test_signs_in_through_a_client_that_accepts_the_flow(mod: ModuleType, tmp_path: Path) -> None:
    """A pool may hold several clients sharing one name with different flows."""
    c = StubCognito(
        clients=[
            {"ClientId": "client-no-flow", "ClientName": "KernelWorx-Web"},
            {"ClientId": "client-real", "ClientName": "KernelWorx-Web"},
        ]
    )
    values = mod.apply_up(c, io.StringIO(), secrets_file=str(tmp_path / "secrets.json"))
    out = io.StringIO()

    assert mod.sign_in_proof(c, values, out) is True
    assert "ok via client client-real" in out.getvalue()


def test_sign_in_proof_fails_loudly_when_no_client_accepts_the_flow(mod: ModuleType, tmp_path: Path) -> None:
    c = StubCognito(clients=[{"ClientId": "nope", "ClientName": "KernelWorx-Web"}])
    values = mod.apply_up(c, io.StringIO(), secrets_file=str(tmp_path / "secrets.json"))
    out = io.StringIO()

    assert mod.sign_in_proof(c, values, out) is False
    assert "FAILED" in out.getvalue()


def test_secrets_file_location_is_documented_and_outside_the_tree(mod: ModuleType) -> None:
    assert mod.SECRETS_FILE.startswith(os.path.expanduser("~")) or "QA_FIXTURE_SECRETS_FILE" in os.environ
    assert not mod.SECRETS_FILE.startswith(str(Path.cwd())), "secrets must not land in the repository"


# --------------------------------------------------------------------------- #
# Stage 4 sweep: the show-and-sells partition and the Unit's payment rows
# --------------------------------------------------------------------------- #


def _stage4_tokens(mod: ModuleType) -> Dict[str, set[str]]:
    tokens, problems = mod.parse_lane_tokens(
        [
            f"data-id={_LANE}",
            f"unit={_LANE_UNIT}",
            f"unit-campaign={_LANE_UC}",
            f"campaign={_LANE_CAMPAIGN}",
            f"profile={_LANE_PROFILE}",
            f"join-code={_LANE_CODE}",
            f"show-and-sell={_LANE_SS}",
        ]
    )
    assert not problems, problems
    return tokens


def test_a_named_show_and_sell_partition_is_swept_whole_and_its_foreigners_survive(mod: ModuleType) -> None:
    """A ``show-and-sell`` token takes the lane's whole event aggregate; another Scout's signup does not move.

    The Stage 4 lane's cleanup (:func:`tests.unit.show_sell_stage4_fixtures.clean_sales_lane`) already
    removes this partition as the lane's own step; the sweep is the residue check behind it, so every
    lane row here — event, slot, signup, sale, sale revision, obligation, fulfillment record — is a
    ``delete``, the same decision the cleanup makes. The guards are the standing shape: a signup for a
    profile no token named, a sale written by an account outside the fixture pool, a fulfillment an
    outsider acted, and a sale an outsider voided all survive as kept — every authorship field present
    on the row is tested, not just the first — and an event no token names is not mentioned at all.
    """
    rows = {
        "kernelworx-show-and-sells-ue1-dev": [
            _item(
                pk=f"SHOW_AND_SELL#{_LANE_SS}",
                sk="METADATA",
                entityType="ShowAndSell",
                unitCampaignId=_LANE_UC,
                createdByAccountId=f"ACCOUNT#{_ADMIN_SUB}",
            ),
            _item(pk=f"SHOW_AND_SELL#{_LANE_SS}", sk="SLOT#slot-1", entityType="ShowAndSellSlot"),
            _item(
                pk=f"SHOW_AND_SELL#{_LANE_SS}",
                sk=f"SIGNUP#slot-1#PROFILE#{_LANE_PROFILE}",
                entityType="ShowAndSellSignup",
                profileId=f"PROFILE#{_LANE_PROFILE}",
                signedUpByAccountId=f"ACCOUNT#{_ADMIN_SUB}",
            ),
            _item(
                pk=f"SHOW_AND_SELL#{_LANE_SS}",
                sk=f"SIGNUP#slot-1#PROFILE#{_OTHER_PROFILE}",
                entityType="ShowAndSellSignup",
                profileId=f"PROFILE#{_OTHER_PROFILE}",
            ),
            _item(
                pk=f"SHOW_AND_SELL#{_LANE_SS}",
                sk="SALE#sale-1",
                entityType="ShowAndSellSale",
                enteredByAccountId=f"ACCOUNT#{_ADMIN_SUB}",
            ),
            _item(
                pk=f"SHOW_AND_SELL#{_LANE_SS}",
                sk="SALE#sale-1#REVISION#1",
                entityType="ShowAndSellSaleRevision",
                correctedByAccountId=f"ACCOUNT#{_ADMIN_SUB}",
            ),
            _item(
                pk=f"SHOW_AND_SELL#{_LANE_SS}",
                sk="SALE#sale-2",
                entityType="ShowAndSellSale",
                enteredByAccountId="ACCOUNT#someone-else",
            ),
            _item(pk=f"SHOW_AND_SELL#{_LANE_SS}", sk="WE_OWE#owe-1", entityType="WeOweObligation", saleId="sale-1"),
            _item(
                pk=f"SHOW_AND_SELL#{_LANE_SS}",
                sk="WE_OWE#owe-1#FULFILLMENT#f1",
                entityType="WeOweFulfillment",
                actorAccountId=f"ACCOUNT#{_ADMIN_SUB}",
            ),
            # A fulfillment acted by an account outside the fixture pool: its author rides on
            # ``actorAccountId``, a field the earlier guard never read, and it must still survive.
            _item(
                pk=f"SHOW_AND_SELL#{_LANE_SS}",
                sk="WE_OWE#owe-1#FULFILLMENT#f2",
                entityType="WeOweFulfillment",
                actorAccountId="ACCOUNT#someone-else",
            ),
            # Entered by the lane but voided by an outsider: the first authorship field matching is
            # not enough — every present author names a fixture identity or the row is kept.
            _item(
                pk=f"SHOW_AND_SELL#{_LANE_SS}",
                sk="SALE#sale-3",
                entityType="ShowAndSellSale",
                enteredByAccountId=f"ACCOUNT#{_ADMIN_SUB}",
                voidedByAccountId="ACCOUNT#someone-else",
            ),
            _item(
                pk=f"IDEM#{_ADMIN_SUB}#createShowAndSellSale#{_LANE_SS}",
                sk=f"IDEM#{_LANE}-sale-quinn",
            ),
            # Another event entirely: the token set says nothing about it, so the sweep is silent.
            _item(pk=f"SHOW_AND_SELL#{_OTHER_SS}", sk="METADATA", entityType="ShowAndSell"),
            # A pk shape that is neither an event partition nor a marker: not this rule's business.
            _item(pk="SOMETHING_ELSE", sk="x"),
        ]
    }
    d = StubDynamo(rows)
    out = io.StringIO()

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, _stage4_tokens(mod), out) == 0
    text = out.getvalue()
    deleted = {(t, tuple(sorted(k.items()))) for t, k in d.deleted}

    assert ("kernelworx-show-and-sells-ue1-dev", (("pk", f"SHOW_AND_SELL#{_LANE_SS}"), ("sk", "METADATA"))) in deleted
    assert (
        "kernelworx-show-and-sells-ue1-dev",
        (("pk", f"SHOW_AND_SELL#{_LANE_SS}"), ("sk", "SLOT#slot-1")),
    ) in deleted
    assert (
        "kernelworx-show-and-sells-ue1-dev",
        (("pk", f"SHOW_AND_SELL#{_LANE_SS}"), ("sk", f"SIGNUP#slot-1#PROFILE#{_LANE_PROFILE}")),
    ) in deleted
    assert (
        "kernelworx-show-and-sells-ue1-dev",
        (("pk", f"SHOW_AND_SELL#{_LANE_SS}"), ("sk", "SALE#sale-1")),
    ) in deleted
    assert (
        "kernelworx-show-and-sells-ue1-dev",
        (("pk", f"SHOW_AND_SELL#{_LANE_SS}"), ("sk", "SALE#sale-1#REVISION#1")),
    ) in deleted
    assert (
        "kernelworx-show-and-sells-ue1-dev",
        (("pk", f"SHOW_AND_SELL#{_LANE_SS}"), ("sk", "WE_OWE#owe-1")),
    ) in deleted
    assert (
        "kernelworx-show-and-sells-ue1-dev",
        (("pk", f"SHOW_AND_SELL#{_LANE_SS}"), ("sk", "WE_OWE#owe-1#FULFILLMENT#f1")),
    ) in deleted
    assert (
        "kernelworx-show-and-sells-ue1-dev",
        (("pk", f"IDEM#{_ADMIN_SUB}#createShowAndSellSale#{_LANE_SS}"), ("sk", f"IDEM#{_LANE}-sale-quinn")),
    ) in deleted
    survivors = _survivors(d)
    assert f"kernelworx-show-and-sells-ue1-dev/SHOW_AND_SELL#{_LANE_SS}/SALE#sale-2" in survivors
    assert (
        f"kernelworx-show-and-sells-ue1-dev/SHOW_AND_SELL#{_LANE_SS}/SIGNUP#slot-1#PROFILE#{_OTHER_PROFILE}"
        in survivors
    )
    assert f"kernelworx-show-and-sells-ue1-dev/SHOW_AND_SELL#{_LANE_SS}/SALE#sale-3" in survivors, (
        "a sale the lane entered but an outsider voided is not the lane's to delete"
    )
    assert f"kernelworx-show-and-sells-ue1-dev/SHOW_AND_SELL#{_LANE_SS}/WE_OWE#owe-1#FULFILLMENT#f2" in survivors, (
        "a fulfillment acted by an outsider names its author only in actorAccountId"
    )
    assert f"kernelworx-show-and-sells-ue1-dev/SHOW_AND_SELL#{_OTHER_SS}/METADATA" in survivors
    assert "that profile is not this lane's" in text
    assert "written by ACCOUNT#someone-else, not a fixture identity" in text
    assert _OTHER_SS not in text, "an event no token names is not this sweep's business"


def test_an_unruled_shape_inside_a_named_event_fails_the_sweep_closed(mod: ModuleType) -> None:
    """The event token selects the partition, and a sort key no rule describes must not pass as clean."""
    rows = {
        "kernelworx-show-and-sells-ue1-dev": [
            _item(pk=f"SHOW_AND_SELL#{_LANE_SS}", sk="MYSTERY#row"),
        ]
    }
    d = StubDynamo(rows)
    out = io.StringIO()

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, _stage4_tokens(mod), out) == 1
    assert "UNKNOWN  show-and-sells" in out.getvalue()
    assert "1 row(s) a lane token names are UNRESOLVED" in out.getvalue()


def test_the_lanes_payment_methods_capacity_counter_and_unit_markers_are_swept(mod: ModuleType) -> None:
    """The Stage 4 payment half: method rows by author, the counter by Unit token, markers by authorship.

    ``PAYMENT-CAPACITY`` names no author and the collection query can never return it, so the Unit
    token is the whole ownership fact; a method row is the lane's when ``createdByAccountId`` names a
    fixture identity, and another tenant's method on the lane's Unit survives. The create/QR markers
    are scoped to the Unit id, so they live in this table — and the marker rule's authorship guard
    keeps another account's attempt on the lane's Unit.
    """
    rows = {
        "kernelworx-units-ue1-dev": [
            _item(
                pk=f"UNIT#{_LANE_UNIT}",
                sk=f"PAYMENT#Venmo {_LANE}",
                paymentMethodId="pm-1",
                createdByAccountId=f"ACCOUNT#{_ADMIN_SUB}",
            ),
            _item(pk=f"UNIT#{_LANE_UNIT}", sk="PAYMENT-CAPACITY", activeCustomCount="3"),
            _item(
                pk=f"UNIT#{_LANE_UNIT}",
                sk="PAYMENT#Someone else's",
                paymentMethodId="pm-9",
                createdByAccountId="ACCOUNT#someone-else",
            ),
            _item(
                pk=f"IDEM#{_ADMIN_SUB}#createUnitPaymentMethod#{_LANE_UNIT}",
                sk=f"IDEM#{_LANE}-payment-method-create",
            ),
            _item(
                pk=f"IDEM#someone-else#requestUnitPaymentMethodQrUpload#{_LANE_UNIT}",
                sk="IDEM#deadbeef-4444-4444-8444-444444444444",
            ),
        ]
    }
    d = StubDynamo(rows)
    out = io.StringIO()

    assert mod.sweep_lane_rows(d, {_ADMIN_SUB}, _stage4_tokens(mod), out) == 0
    text = out.getvalue()
    deleted = {(t, tuple(sorted(k.items()))) for t, k in d.deleted}

    assert ("kernelworx-units-ue1-dev", (("pk", f"UNIT#{_LANE_UNIT}"), ("sk", f"PAYMENT#Venmo {_LANE}"))) in deleted
    assert ("kernelworx-units-ue1-dev", (("pk", f"UNIT#{_LANE_UNIT}"), ("sk", "PAYMENT-CAPACITY"))) in deleted
    assert (
        "kernelworx-units-ue1-dev",
        (
            ("pk", f"IDEM#{_ADMIN_SUB}#createUnitPaymentMethod#{_LANE_UNIT}"),
            ("sk", f"IDEM#{_LANE}-payment-method-create"),
        ),
    ) in deleted
    survivors = _survivors(d)
    assert f"kernelworx-units-ue1-dev/UNIT#{_LANE_UNIT}/PAYMENT#Someone else's" in survivors
    assert f"kernelworx-units-ue1-dev/UNIT#{_LANE_UNIT}/PAYMENT-CAPACITY" not in survivors
    assert "carries no createdByAccountId naming a fixture identity" in text
    assert "names a lane resource but no fixture identity wrote it" in text
    assert "kept   units" in text
