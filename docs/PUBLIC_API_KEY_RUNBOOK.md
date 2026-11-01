# Public-orders API key — renewal, rotation, and the alarms that watch it

Owner: the captain (deploy/ops). This is the runbook named by the public-orders
spec §9 ("ExpiredAPIKeys alarm ... named runbook owner") and Q4 ("365-day
explicit `expires`, manual renewal runbook + on-incident rotation").

## What the key is

`aws_appsync_api_key.public_orders` in
`tofu/application/modules/appsync/api.tf` is AppSync's secondary (API-key) auth
mode for the public buyer surface. It is baked into the public frontend bundle as
`VITE_APPSYNC_API_KEY` and is **expected to be public**: it grants access only to
the `@aws_api_key` root fields, and every one of those still requires the
per-campaign share token, which the resolvers check themselves. Key + leaked
token = anonymous writes to that one campaign until the key expires or the token
rotates.

The `expires` literal is a single module-level value, so **dev, prod, and
ephemeral all share one expiry date** — one renewal edits one line.

Read the live value:

```sh
cd tofu/application/environments/prod
tofu output -raw appsync_api_key_expires
```

Two hard constraints, both pinned by
`tests/unit/test_public_api_key_surface.py`:

- `expires` must be explicit. Omitting it silently gives the provider's 7-day
  default, which kills the public page a week after the deploy.
- `expires` must be within 365 days of the deploy that creates the key, rounded
  down to the hour, and must be a literal — a computed value (`timestamp()`)
  would replace the key on every plan.

That test is a deliberate date gate: it starts failing once the declared expiry
is past or the value is out of the service cap. It is the CI half of the
expiry guard; the runtime half is below.

## Rotation is an add-new → deploy → remove-old sequence

The old version of this runbook claimed that editing `expires` mints a new key.
**That premise was false**: the provider updates `expires` in place via
`UpdateApiKey` and the key material never changes, so a leaked key "rotated"
that way stays valid. An expires-only edit renews lifetime; it does NOT revoke
anything. Do not use it as an incident response.

AppSync's API-key mode genuinely supports multiple keys per API, and the
terraform models both slots explicitly (`var.public_orders_key_slots` in
`tofu/application/modules/appsync/variables.tf`):

- `"a"` (steady state): only slot A (`aws_appsync_api_key.public_orders`)
  exists and the module's `api_key` output reads it.
- `"ab"` (phase 1, ADD NEW): slot B (`aws_appsync_api_key.public_orders_rotation`)
  is created. The module output — and therefore every frontend bundle the
  deploy builds — now reads B, while slot A **stays valid**, so no open buyer
  tab breaks mid-rotation.
- `"b"` (phase 3, REMOVE OLD): slot A is destroyed and the leaked key is
  actually revoked.

There is no `"ba"` convenience state: going back to a single key after a
rotation means setting `"a"` again, which recreates slot A with fresh key
material (and drops B). Between phase 1 and phase 3 the old key stays valid by
design — the cutover of which key the fleet bakes happens at deploy time in
phase 1, and revocation happens only in phase 3, when you ask for it.

## Renewal (planned, before expiry)

1. Edit `expires` in `tofu/application/modules/appsync/api.tf` to a new
   RFC3339 value at hour granularity, within 365 days of the deploy date.
2. Run `tofu validate` in each environment and the unit tests
   (`uv run pytest tests/unit/test_public_api_key_surface.py`).
3. Ship it through the normal deploy. The reminder schedule in
   `tofu/application/modules/alarms/main.tf` is derived from `expires`, so it
   moves by itself — there is no second date to update.
4. Confirm the new bundle: after the deploy, the public page must load an offer
   (`publicGetOrderOffer` with the new `VITE_APPSYNC_API_KEY`), and
   `tofu output -raw appsync_api_key` must match what the built bundle carries.

## On-incident rotation (suspected key or token abuse)

1. Prefer the cheaper remedy first: rotate the **profile's share token** from the
   seller's public-orders settings. That revokes the leaked URL without touching
   the API key at all.
2. If the key itself is compromised, run the three-phase key rotation (an
   expires-only edit is NOT sufficient — see above):
   1. **Add new:** set `public_orders_key_slots = "ab"` and deploy. This creates
      slot B and ships a bundle baking B; slot A remains valid meanwhile.
   2. **Verify the new key:** with the deploy finished, the public page must
      load an offer (`publicGetOrderOffer` using the new `VITE_APPSYNC_API_KEY`
      from `tofu output -raw appsync_api_key`).
   3. **Verify the old key is still live (expected):** a call signed with the
      old slot-A key must still succeed — that is the no-gap property of phase
      1, not a failure of the rotation.
   4. **Remove old:** set `public_orders_key_slots = "b"` and deploy. This
      destroys slot A.
   5. **Verify revocation:** a call signed with the old slot-A key must now
      answer `UNAUTHENTICATED`, and the same call with the new key must
      succeed. If the old key still works, the wrong slot was destroyed —
      stop and reconcile `tofu state list | grep appsync_api_key` against the
      console before proceeding.
3. Check the alarm history and the AppSync `4XXError` metric for the flood's
   shape before and after.

## The alarms (prod unless stated)

CloudWatch alarms can only notify an SNS topic, so
`tofu/application/modules/alarms/` owns one ops topic per environment
(`aws_sns_topic.ops_alerts`) with a direct email subscription to `alert_email`
(the same address the bootstrap cost budgets notify).

**One-time manual step:** the email subscription is created unconfirmed. Confirm
it from the link in the first delivery email, or the alarms fire with nowhere to
go. This is out of band, like the SES identity verification.

| Alarm | Scope | Catches |
|-------|-------|---------|
| `kernelworx-alarms-<env>-appsync-4xx` | dev + prod | AppSync `4XXError` sum ≥ 100 per 300s. Bad/expired API key, bad share tokens, and throttled public calls all land in this metric. |
| `kernelworx-alarms-<env>-public-token-mismatch` | dev + prod | ≥ 20 `PUBLIC_ORDER_TOKEN_MISMATCH` resolver log lines per 300s. A share-token probe flood: bad tokens answer HTTP 200, so this signal is invisible to the 4xx alarm. Metric filter: `tofu/application/modules/alarms/main.tf`. |
| `kernelworx-alarms-<env>-public-cap-rejected` | dev + prod | ≥ 10 cap/throttle rejections per 300s (`PUBLIC_ORDER_CAP_REJECTED` resolver log lines). An order-flood attempt against one or more campaigns, including the per-token 5-creates/60s throttle. |
| `kernelworx-alarms-prod-ses-bounce-rate` | prod | SES `Reputation.BounceRate` ≥ 5% (1h average). |
| `kernelworx-alarms-prod-ses-complaint-rate` | prod | SES `Reputation.ComplaintRate` ≥ 0.1% (1h average). |
| `kernelworx-alarms-prod-public-api-key-expiry` | prod | Scheduled reminder 30 days before the key's `expires`. |

Two honest limits, both verified against the live account's CloudWatch metric
list rather than assumed:

- **AWS publishes no `ExpiredAPIKeys` metric.** `AWS/AppSync` vends `4XXError`,
  `5XXError`, `Latency`, `Requests`, `TokensConsumed`, and the
  subscription/enhanced metrics — none of them key expiry. So the spec's named
  alarm ships as the scheduled reminder (advance warning, zero compute), and the
  day-zero symptom is caught by the 4xx alarm, because an expired key makes
  every public call answer `Unauthorized`.
- **`4XXError` carries only the `GraphQLAPIId` dimension** — there is no
  auth-mode dimension — so the 4xx alarm is API-wide, not key-scoped. Cognito
  client errors count toward it too. The threshold is a starting point; tune it
  against the metric once real buyer traffic exists.

Two abuse signals the 4xx metric cannot see are covered by the
`public-token-mismatch` and `public-cap-rejected` alarms above: resolver-level
rejections (bad share token, cap/throttle) answer HTTP 200 with a GraphQL
error body, so they never touch `4XXError`. Those two alarms read dedicated
`console.error` markers the APPSYNC_JS resolvers emit into the AppSync resolver
log group (`PUBLIC_ORDER_TOKEN_MISMATCH`, `PUBLIC_ORDER_CAP_REJECTED`), via
CloudWatch metric filters in `tofu/application/modules/alarms/main.tf`.

The SES reputation alarms are prod-only because reputation and suppression are
account-level (spec Q3). Bounce handling is SES's built-in account-level
suppression plus these alarms — there is no custom SNS→Lambda suppression
pipeline in v1.

Ephemeral environments do not instantiate the alarms module at all (the #665 WAF
and SES pattern): zero alarm objects, zero cost.

## Pre-launch gate: SES production access for `kernelworx.app`

**A new SES identity starts in the SES sandbox in every region and account,
including prod, until production access is granted.** Until that request lands,
buyer confirmation emails to arbitrary addresses are rejected;
`confirmationEmailSent: true` can only be asserted against sandbox-verified
recipients.

- **Gate:** request SES production access for the prod sending identity
  `kernelworx.app` (spec Q1: the apex domain is the single prod sending
  identity).
- **Owner:** the captain. This is a named pre-launch task, not a dev task.
- **Not done here:** this slice does not submit the request, does not create the
  prod SES identity, and does not enable anything in prod. The prod SES identity
  and its DNS are their own pre-launch slice.
- **DNS warning for that slice:** the apex zone carries live MX/SPF mail
  routing. Verification is DKIM-based, the DKIM records are additive CNAMEs, and
  `include:amazonses.com` must be **merged into** the existing SPF value — read
  the live record set and report it before the first apply, never replace an
  existing record.
- Dev sends from its environment-zone identity (`dev.kernelworx.app`, from
  `orders@dev.kernelworx.app`) with a `[DEV] ` subject prefix; the apex zone is
  never touched from the dev stack.

## Explicit non-goals

No CloudTrail and no X-Ray on this surface — both are excluded from the design
without an explicit decision to add them (`xray_enabled = false` on the API; the
X-Ray KICS query stays excluded in `tofu/.kics.yml`).
