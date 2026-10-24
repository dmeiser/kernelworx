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

## Rotation is a hard cutover

AppSync permits one key per API-key mode, and the provider **replaces** the key
resource when `expires` changes. The old value is gone; the deployed frontend
bundle still carries it. So between the apply and the moment the rebuilt bundle
is live, every public call answers `Unauthorized` — buyers see a dead offer
page. The deploy pipeline (`deploy-shared.yml`) applies tofu and then builds and
publishes the frontend in the same run, so the gap is the deploy duration plus
any browser tab that was already open. Accept the gap; do not try to run two
keys side by side, because AppSync will not let you.

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
   seller's public-orders settings. That revokes the leaked URL without breaking
   every open buyer tab.
2. If the key itself is the problem, rotate it: change `expires` (any new value
   mints a new key) and deploy. Expect the cutover gap above.
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
- Dev sends from its own subdomain identity (`orders.dev.kernelworx.app`) with a
  `[DEV] ` subject prefix; the apex zone is never touched from the dev stack.

## Explicit non-goals

No CloudTrail and no X-Ray on this surface — both are excluded from the design
without an explicit decision to add them (`xray_enabled = false` on the API; the
X-Ray KICS query stays excluded in `tofu/.kics.yml`).
