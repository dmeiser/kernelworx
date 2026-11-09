# Show & Sell invite-discovery consistency deviation — wave-2 decision record

Status: RECORDED (wave 2, r1 review CHANGES item, documentation-only; no
code change). Applies to `redeemUnitInvite` in
`src/handlers/unit_operations.py`.

## The deviation

Spec DATA_MODEL §6.1 directs consistent reads for grant authorization and
redemption lookups. Wave-2 invite redemption discovers the invite by code
through the units table's
`metadataKey-createdAt-index` — an **eventually consistent GSI**.

## Why the layout forces it

The units table is keyed by `unitId` (hash) + `itemKey` (range). Invite
rows must live under their Unit (metadata, counts, and authorization are
same-hash reads), yet redemption arrives with only a code — a code that
must be globally unique. A consistent GetItem needs the hash key, which
the caller does not have. The alternatives all fail:

- A code-keyed base row in the units table: the hash key IS `unitId`, so
  a code lookup without the unit id cannot be a base-table read.
- Scanning for the code: forbidden (no-Scan invariant).
- A separate invite-by-code table: a sixth table for one lookup class,
  duplicating invite state with a new consistency hazard of its own.

The impact map sanctions the aggregate layout (§4.1); within it, the GSI
is the only discovery path. Everything AFTER discovery is consistent and
conditioned: the invite `Update` carries
`#status = :active AND expiresAtEpoch > :now` under the base hash, the
grant `Put` is conditioned on absence, and the Unit METADATA counts update
is conditioned — the transaction re-validates every fact it acts on.

## The residual (named, not smoothed over)

Create-then-immediate-redeem inside the GSI's inconsistency window returns
NOT_FOUND **and burns one throttle attempt** — a failure the caller did
not cause. Ten such spurious misses inside one UTC hour trip
`RATE_LIMIT_EXCEEDED` and lock the account out of redemption for the rest
of the window. This is a real, if narrow, availability hazard: a Unit
Admin who creates an invite and hands it to someone standing next to them
can produce it on demand.

## Mitigations already in place

- Only **failed** redemptions increment; a replayed success never counts.
- The invite TTL is 14 days: the window for the race is the GSI
  propagation lag (seconds), not the invite lifetime.
- The throttle counter is per account-hour, so the lockout decays in under
  an hour.

## Monitoring stance

If redemption NOT_FOUND rates ever justify it, the remediation is a
code-keyed base row in a dedicated lookup structure (accepting the state
duplication) — NOT a relaxation of the throttle or the no-Scan invariant.
Until then: this record is the standing acknowledgment; the residual is
accepted for the dev integration and MUST be revisited before production
smoke (integration plan §3 step 8, scale readiness).
