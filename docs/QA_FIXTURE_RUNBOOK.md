# QA login fixture on the dev stack

QA cannot test a feature it cannot log in to. This runbook is the answer to
"no credentials": one script, four identities, and the state of the dev Cognito
pool as it can actually be observed. Nothing here needs a mailbox, a GitHub
secret, or an interactive confirmation flow.

Script: `scripts/qa_fixture.py` · Tests: `tests/unit/test_qa_fixture.py`

## The four identities

Pool `us-east-1_sDiuCOarb` (`kernelworx-users-ue1-dev`, `us-east-1`), group
`show-sell-preview`, domain `dev.kernelworx.app`:

| Identity | Role in the journey | `show-sell-preview` |
| --- | --- | --- |
| `qa-show-sell-admin@dev.kernelworx.app` | creates the Unit and the Unit Campaign, invites the second admin | member |
| `qa-show-sell-admin2@dev.kernelworx.app` | accepts the invite, redeems it, acts as the second admin | member |
| `qa-show-sell-scout@dev.kernelworx.app` | joins a campaign by code, appears on the roster | member |
| `qa-show-sell-outside@dev.kernelworx.app` | an account that never joins — the negative half of the preview gate | not a member |

Three members and one sign-in-capable non-member is the minimum that shows the
preview gate from both sides. The scout has to be a member because
`frontend/src/ShowSellRoutes.tsx` gates the **whole** `/show-sell/*` tree,
`/show-sell/join` included: a scout outside the group is redirected to `/` and
cannot open its own join page, which is the precondition the Stage 1 journey in
`tests/e2e/README.md` needs. `outside` is what carries the closed half of the
gate. `up` asserts that shape every run: it adds admin, admin2 and scout to the
group and removes `outside`, so a membership that drifted is corrected rather
than inherited.

## Commands

Run from a clean checkout with nothing but a configured AWS profile. `boto3` comes
from the repository's environment, so `uv sync` runs first:

```bash
uv sync                                             # the script's boto3 comes from here
uv run python scripts/qa_fixture.py status          # read-only: users, group, leaks
uv run python scripts/qa_fixture.py up              # create or refresh the four
uv run python scripts/qa_fixture.py down            # plan, confirm, delete rows + users
uv run python scripts/qa_fixture.py down --yes      # same, non-interactive
```

`up` is idempotent: an existing identity is refreshed (new password, forced
`email_verified`, correct group state) and never re-created, so re-running it
cannot grow the pool. `down` prints every user and every row it intends to
delete before it writes anything, and refuses to delete any row it cannot tie to
a fixture `sub`.

## What `down` guarantees

Order and failure handling are the contract, because the script must never create
the unattributable state it exists to clear:

1. **Rows first, users last.** A row is attributable only while the user whose
   `sub` owns it still exists. Deleting the user in front of a row that failed
   would strand that row forever.
2. **One item, one attempt, one line.** A failed `delete_item` is printed as
   `FAILED row <table> <key> <error>` and the sweep keeps going; it does not
   abort the table and it does not delete any identity.
3. **A partial teardown exits non-zero and keeps the secrets file.** The message
   says to re-run `down`; the next run re-derives the same subs from the users
   that are still there and finishes the job. `tests/unit/test_qa_fixture.py::test_a_failed_row_delete_keeps_the_users_and_a_second_down_finishes`
   pins exactly that sequence.
4. **A row is deleted only when it names a fixture identity.** A key part equal
   to a fixture `sub` or a fixture address (`…/ROLE#<fixture address>` — a grant
   naming the fixture), or the owner attribute carrying it, qualify. A row that
   merely shares a partition key with a fixture row does **not**:
   `UNIT#u1/ROLE#someone-else@example.com` is another tenant's grant on a fixture
   Unit, and it is reported and left alone. Each planned row prints *why* it was
   selected — `[key names a fixture sub]`, `[key names a fixture address]`,
   `[createdByAccountId names a fixture sub]` — so a person reading the plan can
   check every row against those shapes instead of trusting the rule.
5. **A stale secrets file is dropped even when there is nothing to delete.**

### Which rows a real teardown claimed, as measured

A dry run against `us-east-1_sDiuCOarb` and the three sweep tables on 2026-11-16
(answered `n`, so nothing was written) planned 4 users and 107 rows, and reported
60 rows as left:

| shape | rows | evidence that selected it |
| --- | --- | --- |
| `ACCOUNT#<sub>` | 4 | key names a fixture sub |
| `IDEM#<sub>#<action>#<uuid>` / `IDEM#<request-uuid>` | 72 | key names a fixture sub (the caller is segment 2) |
| `UNIT#<id>/GRANT#<sub>` | 11 | key names a fixture sub |
| `UNIT#<id>/METADATA` | 10 | `createdByAccountId=ACCOUNT#<sub>` |
| `UNIT#<id>/INVITE#…` | 1 | `createdByAccountId=ACCOUNT#<sub>` |
| `UNIT_CAMPAIGN#<id>/METADATA` | 9 | `createdByAccountId=ACCOUNT#<sub>` |
| **left**: `ACCOUNT#<other sub>` | 33 | no fixture identity in key or owner |
| **left**: `UNIT_CAMPAIGN#<id>/MEMBERSHIP#PROFILE#<other>` | 9 | another tenant's membership on a fixture campaign |
| **left**: `SCOUT_CAMPAIGN#CAMPAIGN#<id>/MEMBERSHIP_GUARD` | 9 | no fixture identity anywhere |
| **left**: `JOIN_CODE#<code>/POINTER` | 9 | the code is an opaque id, the owner is not in the key |

So every deleted row spells a fixture identity in its own key or owner attribute,
and the two shapes that would be tempting to sweep up by partition — a third
party's `MEMBERSHIP#PROFILE#…` and the `JOIN_CODE` pointers inside a fixture
campaign — are the ones reported and left.
`tests/unit/test_qa_fixture.py::test_a_third_party_row_on_a_fixture_partition_is_never_deleted`
pins that half.

### Known gap: which tables the sweep can even read

`down` sweeps `accounts`, `units` and `unit-campaigns`, and its plan prints
`sweep tables: …` so the coverage is visible at teardown rather than discovered
later. Fixture rows also appear in `kernelworx-inventory-ue1-dev`,
`kernelworx-orders-ue1-dev` and `kernelworx-order-fulfillments-ue1-dev` once a
Show & Sell Stage 2 lane runs; those are in `SWEEP_TABLES`, which `sweep` uses,
and `down` still leaves them. `TABLES` in the script is the one place to extend.

The reach is bounded by the IAM identity, not just by `TABLES`: measured on
2026-11-16, `kernelworx-qa-ue1-dev` is denied `dynamodb:Scan` on
`user-campaigns`, `scout-credit`, `we-owe`, `show-and-sells`,
`campaign-inventory`, `inventory`, `order-fulfillments`, `user-profiles` and
`tokens` (dev suffixes). Closing the gap therefore needs a table read grant
first — an owner action outside this card's no-IAM-change boundary — before a
`TABLES` entry would do anything but fail.

### `sweep`: one acceptance lane's rows, identities kept

`down` removes the pool and everything attributable to it. `sweep` removes one
acceptance lane's rows and keeps the pool, because a Stage 2 run leaves rows the
product cannot delete: the SDL carries no `deleteUnit` and no
`deleteUnitCampaign`, so the Unit and its Unit Campaign rows outlive every
GraphQL teardown the run performs.

```bash
uv run python scripts/qa_fixture.py sweep --lane stage2-1118107 \
    --lane <unitId> --lane <unitCampaignId> --yes
```

A row is deleted only when **both** conditions hold:

1. it passes the attribution rule above, so it belongs to a fixture identity and
   not to a third party sharing its partition, and
2. it names one of the caller's lane tokens — the run's `DATA_ID` (which the
   Unit display name and every Unit Campaign name it made carry), or the Unit
   and Unit Campaign ids that run was answered.

Condition 2 is what stops one run sweeping the whole pool: another lane's Unit
on the same fixture admin is attributed but not named, so it is left. Condition
1 is what stops a lane reaching into a tenant that happens to sit on its own
partition key. A sweep with no `--lane` token refuses to run.

`sweep` then re-scans and prints `LEFT <table>/<key>` for anything still naming
those tokens, because a `delete_item` that returned without an error is not
evidence, and prints `BLOCKED <table>: <error>` for a table the identity cannot
read — a denied scan is reported, never treated as an empty table. Any `LEFT`
or `BLOCKED` line makes the exit code non-zero. The identities are never
touched: `sweep_lane_rows` is not even given the Cognito client.

Measured again on 2026-11-19 with the Stage 2 lane tables added to
`SWEEP_TABLES`: `accounts`, `units` and `unit-campaigns` read and delete;
`kernelworx-inventory-ue1-dev`, `kernelworx-orders-ue1-dev` and
`kernelworx-order-fulfillments-ue1-dev` answer `AccessDeniedException` on
`Scan` and on `DeleteItem`. So a Stage 2 lane's inventory rows — the zeroed
balances and the append-only movement history — are a named finding until the
table grant lands. `tests/e2e/test_smoke_show_sell_stage2.py` calls this
command in its teardown and records what it reported, so a lane cannot claim a
clean sweep it did not get.

### AWS identity

Credentials come from the host's **ambient AWS profile** (`~/.aws/config`,
`~/.aws/credentials`, or the standard session variables). The dev pool is
administered by the scoped user
`arn:aws:iam::750620721302:user/kernelworx-qa-ue1-dev`. The script takes no
credential, pool id, or password on the command line and never reads the
repository's `.env`.

Measured boundaries of that user on 2026-11-16 (`status` needs only the first
group):

| Allowed | Denied |
| --- | --- |
| `ListUsers`, `ListGroups`, `ListUsersInGroup`, `ListUserPoolClients`, `DescribeUserPool`, `AdminCreateUser`, `AdminSetUserPassword`, `AdminUpdateUserAttributes`, `AdminAddUserToGroup`, `AdminRemoveUserFromGroup`, `AdminUserGlobalSignOut`, `AdminDeleteUser` | `DescribeUserPoolClient`, `ListTagsForResource` |

The denials matter: without `DescribeUserPoolClient` no tool can list which app
client has which `ExplicitAuthFlows`, and without `ListTagsForResource` nothing
can tell a tofu-managed client from an orphan. Anything that needs those reads
must be run by an identity that holds them.

### Passwords

Passwords are generated by the script and written **only** to a `0600` file:
`$QA_FIXTURE_SECRETS_FILE`, defaulting to `~/.kernelworx/qa-fixture-secrets.json`.
They never appear in argv, stdout, a log, an artifact, or an issue comment —
`tests/unit/test_qa_fixture.py::test_no_password_ever_reaches_stdout` fails the
build if one does. `down` deletes the file.

The keys in that file are the ones a QA run consumes:

```text
TEST_QA_SHOW_SELL_BASE_URL            https://dev.kernelworx.app
TEST_QA_SHOW_SELL_ADMIN_EMAIL / _PASSWORD
TEST_QA_SHOW_SELL_ADMIN2_EMAIL / _PASSWORD
TEST_QA_SHOW_SELL_SCOUT_EMAIL / _PASSWORD
TEST_QA_SHOW_SELL_OUTSIDE_EMAIL / _PASSWORD
```

`source` them into the environment of the run rather than copying them into a
file in the tree.

## Which Cognito field joins to which application row

The pool declares **`username_attributes = ["email"]`**
(`tofu/application/modules/cognito/main.tf:191`), so an e-mail address is a
sign-in and lookup handle. What the pool *stores* in `Username` is a different
thing, and getting these three fields straight is the difference between a join
that works and one that quietly returns nothing:

| Field | What it holds in `us-east-1_sDiuCOarb` |
| --- | --- |
| stored `Username` | a UUID equal to the user's `sub`, for every pool-local user |
| `sub` attribute | the same UUID; application rows are keyed `ACCOUNT#<sub>` |
| trigger event `userName` | the address on a native `PreSignUp_SignUp`; `Google_<id>` on a federated sign-up |

Measured 2026-11-16 with the QA identity (`aws` request ids are given so the read
can be re-run and checked):

```text
DescribeUserPool request-id=6743ec1e-0cf1-4f10-b299-76cfef5f5422
                          UsernameAttributes=['email']  AutoVerifiedAttributes=None
ListUsers request-id=8be598f5-8b94-4717-859d-6a536caa4082
                          26 users; Username == sub for 25 of them
outlier                     Username=Google_111807007628636882761  sub=24f8f4e8-7021-70a9-9cf3-cf38ce4258fe
admin_get_user(qa-show-sell-admin@dev.kernelworx.app)  Username=94187428-20e1-70d6-94cb-7f68f80c72dd  request-id=a8ff6a9a-1c0d-4f96-80df-03477e421863
admin_get_user(test-owner@dev.kernelworx.app)          Username=54f8a468-d041-700e-50f9-1a3f854bd6fc  request-id=6c3f9177-ade4-4894-854d-17626a4db74f
```

Three consequences:

- **`Username` is not a join key.** For the four fixture accounts, and for the
  users `scripts/create-test-users.sh` admin-creates with `--username "$email"`,
  the stored `Username` is the UUID, not the address: the `--username` value is
  accepted as a handle and aliased, not kept. Join on `sub` (or `email`);
  `scripts/qa_fixture.py:pool_users` keys by address for exactly this reason.
- **The address still works as a handle.** `admin_get_user`,
  `admin_set_user_password` and `admin_delete_user` all accept it — that is how
  the script can pass `Username=qa-show-sell-admin@…` and succeed while the pool
  holds a UUID. "The address resolves" and "the address is stored in `Username`"
  are different claims, and only the first is true.
- **The federated row is the trap behind the trap.** `Google_111807007628636882761`
  has neither an address nor a UUID in `Username`, so code that assumes either
  shape breaks on it; `src/handlers/pre_signup.py` splits that value on `_`
  precisely because of it. The two logging tests
  (`tests/unit/test_handlers_structured_logging.py:111`, `:144`) assert the
  *trigger event's* `userName` is the address on a native sign-up — that is the
  event field, not the stored attribute, and the two readings are consistent.

## The app-client hazard

The dev pool held **18 app clients, all named `KernelWorx-Web`**, when measured
on 2026-11-16. Only one is the tofu-managed client
(`aws_cognito_user_pool_client.web` in `tofu/application/modules/cognito/main.tf`,
published as the `cognito_client_id` environment output and the deploy job's
`client_id` output); the rest are orphans that carry different
`ExplicitAuthFlows`. So:

- Resolve the client by the tofu output id, never by name. `frontend/deploy.sh`
  and the deploy job's TOTP step already do, and fail with a named error rather
  than guessing (since `#567`).
- A name lookup with more than one match is a coin flip. `status` prints the
  count so the drift is visible instead of inferred.
- `scripts/qa_fixture.py` proves sign-in by *trying* clients and reporting the
  id that answered, because it cannot read the flows (see the permission table
  above). Knowing which client answered is the point: a proof that passes on an
  orphan client does not prove the deployed frontend's client works.
- Removing the orphans needs `cognito-idp:DeleteUserPoolClient` plus
  `DescribeUserPoolClient`, which the QA user does not hold. That deletion is a
  pool-owner action, not a lane action.

### Not closed by this card — two named items

Both are acceptance items on WORK-201. They are recorded here as owned work, not
as done work:

1. **`app clients named KernelWorx-Web: 1` — pool-owner action, owned by Dave
   (pool `us-east-1_sDiuCOarb`).** Measured 18 of 18 clients named
   `KernelWorx-Web`. The QA identity cannot read a client, so it cannot tell the
   tofu-managed one from an orphan, and deleting a live app client blind breaks
   the deployed frontend — the failure class `#567` already records. Verbatim, as
   the calls fail:

   ```text
   AccessDeniedException: User: arn:aws:iam::750620721302:user/kernelworx-qa-ue1-dev
     is not authorized to perform: cognito-idp:DescribeUserPoolClient because
     no identity-based policy allows the cognito-idp:DescribeUserPoolClient action
   AccessDeniedException: ... is not authorized to perform:
     cognito-idp:ListTagsForResource on aws_cognito_user_pool_client/<id>
   ```

   The safe teardown is: read `module.cognito.client_id` from the dev stack
   outputs, delete every other client named `KernelWorx-Web`, and stop creating
   clients outside `aws_cognito_user_pool_client.web`. No IAM change was made
   here, and no client was deleted here.
2. **`leaked users across two consecutive e2e runs: 0` — measured by QA as its
   own criterion.** This lane did not run the two e2e runs: the committed smoke
   suite needs the `TEST_OWNER_EMAIL`/`TEST_OWNER_PASSWORD` GitHub secrets, which
   no dev lane holds, and the Show & Sell journey is a `slow` Playwright run whose
   rows land in tables `down` does not sweep yet (see the known gap above). What
   is measured instead, at the pool rather than inferred from `git log`:

   - Zero users in a named leak class exist after cleanup (`leaked strays=0`).
   - No `e2e-signup-*` user has ever been created after 2026-07-30, while
     `Post-deploy smoke tests (dev)` ran green on every `Deploy Dev` of 2026-11-09,
     11-13 (three times), 11-14 and 11-15 — the committed suite is not the leak
     source, and the 35 rows came from one July session.
   - The committed native-signup path (`tests/e2e/test_smoke_signup.py`) is gated
     off by `RUN_NATIVE_SIGNUP` and deletes its user in a `finally`; the pool holds
     none of its addresses.

   QA should read `status` before and after two consecutive runs of the suite it
   executes and record both counts. `status` prints the number, so the evidence is
   one line per run.

## Pool hygiene, as measured

`status` counts leak classes so a recurrence is visible. Measured 2026-11-16,
before cleanup: 66 users, 42 `UNCONFIRMED`.

| Class | Count | Created | Finding |
| --- | --- | --- | --- |
| `e2e-signup-*@example.com` | 35, all `UNCONFIRMED` | 2026-07-29 13:45 → 2026-07-30 14:40 | one testing session, not per run: the string `e2e-signup` appears nowhere in the repository's tracked history (`git log --all -S e2e-signup` is empty), and no `e2e-signup-*` user had been created since 2026-07-30 while dozens of e2e runs landed since |
| `qa-wave2-*` / `qa-probe-delivery` | 5, all `UNCONFIRMED` | 2026-11-15 15:43 → 17:30 | strays from the blocked attempt this runbook replaces |
| `smoke+*@example-test.invalid` | 0 | — | the committed native-signup path (`tests/e2e/test_smoke_signup.py`, gated by `RUN_NATIVE_SIGNUP`) creates one per run and deletes it in a `finally`; the pool holding none is the evidence it cleans up after itself |

Executed on 2026-11-16: the 35 `e2e-signup-*@example.com` rows were listed,
printed as a plan, and deleted with `AdminDeleteUser`; the recount showed
`leaked-in-named-classes=0` and the pool down from 57 to 22 users. The five
`qa-wave2-*` / `qa-probe-delivery` strays were present in the first read of that
session and already gone in the next — deleted by whoever ran the fixture
teardown in between — so they are recorded rather than claimed. Two unconfirmed
addresses were deliberately **left alone** because they are not a named leak
class: `kwpod3c6c830@maxxspace.com`, `test123@example.com`.

Re-read at 06:20Z the same day, the pool is 26 users with `leaked strays=0`. The
users in it are accounted for rather than unexplained: the four fixture
identities, the `create-test-users.sh` roles (`test-owner@dev.kernelworx.app`,
and `smoke@example.com`, CONFIRMED, whose 2026-11-06 creation matches the
`TEST_SMOKE_EMAIL` role), one `Google_…` federated sign-in, five
`kw-lifecycle-verify-*@example.com`, and the two unconfirmed addresses above.
None of them is a per-run leak class, so none of them is deleted by a lane that
cannot ask their owner.

`up` then created the four identities and proved sign-in:

```text
sign-in ok via client 19fblmi4vkfu5r6uq9mmi1ltab: groups=['show-sell-preview'] mfa=False
qa-show-sell-admin@dev.kernelworx.app    CONFIRMED verified=true preview=yes want=True
qa-show-sell-admin2@dev.kernelworx.app   CONFIRMED verified=true preview=yes want=True
qa-show-sell-scout@dev.kernelworx.app    CONFIRMED verified=true preview=no  want=False
qa-show-sell-outside@dev.kernelworx.app  CONFIRMED verified=true preview=no  want=False
users total=26  leaked strays=0
```

That transcript is the state as created on 2026-11-16, and the scout's row reads
`preview=no want=False` because the script's table said so at that moment. The scout
holds the group in the pool now — re-read later the same day, and the add was not
made by this script:

```text
pool us-east-1_sDiuCOarb  group show-sell-preview  members: ['qa-show-sell-admin2@dev.kernelworx.app', 'qa-show-sell-admin@dev.kernelworx.app', 'qa-show-sell-scout@dev.kernelworx.app']
qa-show-sell-scout@dev.kernelworx.app        CONFIRMED  verified=true  preview=yes  want=True
qa-show-sell-outside@dev.kernelworx.app      CONFIRMED  verified=true  preview=no   want=False
app clients named KernelWorx-Web: 18 of 18 (a name lookup is only safe when this is 1)
users total=26  leaked strays=0
```

That out-of-band add is exactly the drift the old table would have undone: an `up`
run against it would have removed the scout from the group and broken the journey's
step-2 precondition. The table above is the contract now, so `up` asserts the scout
as a member and the drift cannot come back on a run.

Because `up` generates a **new password every run**, rotating on purpose is
fine but rotating by accident is not: if the passwords are already distributed
to a QA environment and only the group membership has drifted, repair the
membership with `admin-add-user-to-group` / `admin-remove-user-from-group`
instead of re-running `up`.
