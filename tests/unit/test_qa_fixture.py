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
    ) -> None:
        self.users: Dict[str, Dict[str, Any]] = {u["email"]: u for u in (users or [])}
        self.group = set(group or [])
        self.clients = clients or [{"ClientId": "client-real", "ClientName": "KernelWorx-Web"}]
        self.pages = pages
        self.calls: List[str] = []
        self.deleted: List[str] = []
        self.passwords: Dict[str, str] = {}

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
            "Username": f"uuid-{mail}",  # the pool aliases e-mail: Username is a UUID
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
    """Enough of ``dynamodb`` to exercise the sweep's attribution rules."""

    def __init__(self, tables: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tables = tables
        self.deleted: List[tuple[str, Dict[str, str]]] = []

    def scan(self, *, TableName: str, **_: Any) -> Dict[str, Any]:
        return {"Items": self.tables.get(TableName, [])}

    def delete_item(self, *, TableName: str, Key: Dict[str, Any]) -> None:
        self.deleted.append((TableName, {k: v["S"] for k, v in Key.items()}))


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
            _item(pk="UNIT#u9", sk="META", createdByAccountId="ACCOUNT#someone-else"),
        ],
        "kernelworx-unit-campaigns-ue1-dev": [
            _item(pk="UNIT#u1", sk="CAMPAIGN#c1", createdByAccountId="ACCOUNT#sub-admin"),
            _item(pk="UNIT#u9", sk="CAMPAIGN#c9", createdByAccountId="ACCOUNT#someone-else"),
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
    assert text.index("plan:") < text.index("deleted user"), "the plan must precede the write"


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
