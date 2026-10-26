// Structured code-review fanout for PR #784 (public orders), per the
// code-review-checklist skill: one reviewer per (category x layer).

const REF = 'git diff 3d23131c84b9e95b26134cb6a36c152bb74c46f4..HEAD';

const PREAMBLE = [
  'You are ONE reviewer in a structured, deterministic code review of PR #784 on branch fm/KW-PUBLIC-ORDERS-MEGA-1 in /home/dm/code/kernelworx.',
  '',
  'THE CHANGE UNDER REVIEW',
  '- Diff: `' + REF + '` (merge-base with origin/main .. HEAD). 152 files, +18551/-63, 65 commits.',
  '- Full diff text: /tmp/review/full.diff ; changed-file list: /tmp/review/files.txt',
  '- PR #784 description: "Adds the public-orders feature: buyers can place orders through a public share URL or QR code without an account, and receive a buyer confirmation email." Closes #679. Supersedes a nine-PR chain.',
  '- New surface: API-key-authenticated AppSync queries/mutations (publicGetOrderOffer, publicCreateOrder, publicGetOrderReceipt), owner-only campaign public-order settings (share token minting/rotation), SES confirmation emails, a new `alarms` Terraform module, frontend public order/receipt pages, and an authenticated seller-side "confirm payment" flow on OrdersPage.',
  '',
  'AUTHORITY: READ-ONLY. Do not edit, create, delete, stage, commit or push anything, and do not run mutating commands (no formatters, no test runs that write fixtures). Inspect with git, read, grep/rg. You may run read-only analysis commands.',
  '',
  'PROJECT INVARIANTS (must respect)',
  'Read /home/dm/code/kernelworx/AGENTS.md first. It records load-bearing, deliberately-decided project posture, including: AppSync resolver-only authorization (schema directives do NOT authorize); per-domain Lambda IAM roles with no shared fallback; AppSync JS resolver runtime restrictions (no `in`, no Boolean(), no .call/.apply/.bind, no continue); templatefile() ${...} escaping; resolver bundling from appsync/dist; CloudFront Free-tier trade-offs; "catalogs are never deleted"; DynamoDB transient/permanent error classification. A finding that contradicts a documented deliberate decision in AGENTS.md is INVALID - do not report it.',
  '',
  'SEVERITY RULES',
  'MUST = correctness, security, data loss, crash, or merge-blocker. SHOULD = real defect or tech debt, not urgent, defensible defer. COULD = valid improvement, optional, judgment call. NIT = style/readability, no functional impact. INFO = not a defect: question, note, praise.',
  '',
  'EVIDENCE BAR: verify every claim against source before reporting. Cite file:line for each finding and give a concrete fix. No speculation, no "might", no findings you have not opened the file for. Prefer 3 verified findings over 15 unverified ones.',
  '',
  'STAY IN YOUR LANE: 18 other reviewers cover the other categories. Do not report another category\'s concern, even if you spot it.',
  'WORK EFFICIENTLY: read the in-scope files first, then verify only the claims you intend to report. Do not re-derive the whole feature narrative.',
  '',
  'OUTPUT CONTRACT (obey exactly)',
  'Return ONLY your own category\'s findings, grouped by severity in the order MUST, SHOULD, COULD, NIT, INFO. Number per category starting at 1 (e.g. SEC-1, SEC-2). Tag every finding with its layer: [FE], [BE] or [X-FE/BE]. Omit empty severity groups. If you found nothing, output exactly: "No <CATEGORY> findings." Max 12 findings; if you have more, keep the most important and say how many were dropped. One line per finding (file:line + problem + fix); no preamble, no summary, no methodology narration.',
].join('\n');

const CATS = {
  SCOPE: [
    'CATEGORY: SCOPE - PR scope & hygiene (layer-agnostic; do NOT tag findings with [FE]/[BE]).',
    'Checklist:',
    '1. PR title/description explains what, why, how; links the ticket.',
    '2. Change is one concern; no unrelated files.',
    '3. No accidental config/lockfile/binary changes.',
    '4. Refactor not mixed with feature.',
    '5. Branch is current against main; no stale-merge risk.',
    '6. No TODO/FIXME/XXX left to merge; no debug logs, dead code, commented-out blocks.',
    '7. Reasonable size - under a few hundred changed lines (flag if larger).',
    'Useful commands: `gh pr view 784 --json title,body,files,additions,deletions,commits,mergeable`, `git log --oneline 3d23131..HEAD`, `git diff --stat 3d23131..HEAD`, and grep the diff for TODO/FIXME/XXX/console.log/debug prints/commented-out code.',
  ].join('\n'),

  FUNC: [
    'CATEGORY: FUNC - Functionality & logic.',
    'Checklist:',
    '1. Logic implements the requirement, not just a plausible implementation.',
    '2. Edge cases & boundaries: off-by-one, null/empty, empty collections, zero/negative, missing attributes on pre-feature DynamoDB rows.',
    '3. Loops & recursion terminate; no infinite loop / unbounded recursion (watch pagination, retry loops, UnprocessedKeys loops).',
    '4. Error handling on every fallible operation; specific exception types, not bare `except`.',
    '5. Return values used or intentionally ignored.',
    '6. Control flow clear; not gratuitously complex.',
    '7. Null/empty checks present where values can be absent.',
  ].join('\n'),

  SEC: [
    'CATEGORY: SEC - Security (OWASP Top 10).',
    'Checklist:',
    '1. Injection: SQL/NoSQL/command/LDAP/Filter-expression - parameterized or sanitized (note the cognito_user_filter rule).',
    '2. Broken auth: no hardcoded creds; session/secret handling correct (share tokens, receipt tokens, API key, credentials in CI logs/argv).',
    '3. Sensitive data exposure: secrets, PII (buyer email/phone/address), keys not logged or committed - check structured log fields, SES templates, reports.',
    '4. XML/XXE: external entities disabled.',
    '5. Broken access control: authZ on every endpoint, not just authN. This repo authorizes ONLY in resolvers/handlers - audit every new resolver/function/handler for its ownership/token check, cross-account access, token comparison timing/encoding, enumeration oracles, IDOR on campaignId/orderSuffix/receiptToken, and whether the API key alone can reach data it should not.',
    '6. Security misconfig: no debug mode, no default creds, no verbose errors to prod; robots.txt / noindex posture; IAM policy scope (new SES + public-orders roles).',
    '7. XSS: output encoding/escaping on user-controlled data (React dangerouslySetInnerHTML, SES email templates, receipt/offer rendering, share URL/QR handling).',
    '8. Insecure deserialization: no untrusted pickle/deserialize.',
    '9. Known-vulnerable dependency: check any newly added dependency version (frontend/package.json diff).',
    '10. Insufficient logging/monitoring of security events (failed token checks, abuse of public write path, rate limiting of the unauthenticated write path).',
  ].join('\n'),

  DRY: [
    'CATEGORY: DRY - Duplication & framework coverage.',
    'Checklist:',
    '1. Logic duplicated elsewhere in the codebase (SEARCH before claiming - use rg across src/, tofu/application/appsync/js-resolvers/, frontend/src/).',
    '2. Existing framework/lib/stdlib already provides this - do not reinvent.',
    '3. Multiple implementations of the same concept (e.g. several validation, formatting, token, or error-mapping implementations).',
    '4. Copy-paste with trivial variation that should be a parameter/helper (compare the new JS resolver pairs and the new frontend hooks/components).',
    '5. Utility code that belongs in a shared module, not a one-off local copy.',
    '6. New dependency added when a built-in or existing dep suffices.',
  ].join('\n'),

  ARCH: [
    'CATEGORY: ARCH - Architecture & design.',
    'Checklist:',
    '1. Fits the system\'s existing architecture and patterns (AppSync pipeline function ordering, one-function-ID-once rule, two-phase ownership authz, denormalized pointer invariants, Lambda role split, resolver bundling).',
    '2. Component makes sense in the wider system, not just in isolation.',
    '3. Correct abstraction boundaries; minimal coupling, clear interfaces.',
    '4. Single responsibility at module/class level; no god-objects.',
    '5. Data flows and state ownership are coherent (DynamoDB attribute ownership, share/receipt token lifecycle, order status state machine).',
    '6. No superfluous dependency or over-engineered abstraction.',
    '7. Change is revertable / separable if it goes wrong (schema/IaC migration safety, state moves, alarms module, SES identity setup).',
  ].join('\n'),

  PRIN: [
    'CATEGORY: PRIN - Engineering principles.',
    'Checklist:',
    '1. SOLID: SRP, OCP, LSP, ISP, DIP applied where relevant.',
    '2. Composition over inheritance where appropriate.',
    '3. Law of Demeter respected (do not reach through collaborators).',
    '4. Naming communicates intent; no misleading names (especially error codes: UNAUTHORIZED vs FORBIDDEN semantics in this repo).',
    '5. Pure functions / no hidden side effects where feasible.',
    '6. Principle of least surprise in API design (schema field nullability, error contract, input validation semantics).',
    '7. Consistency with team/org engineering standards as recorded in AGENTS.md.',
  ].join('\n'),

  PERF: [
    'CATEGORY: PERF - Performance.',
    'Checklist:',
    '1. No accidental O(n^2)/O(n^3) where linear exists.',
    '2. No blocking I/O on hot paths where async/streaming fits (Lambda cold path, sequential AWS calls).',
    '3. Queries indexed correctly; no N+1 in DB/API calls (GSI usage, BatchGetItem 100-key caps, per-item GetItem in resolvers, unpaginated catalog product lists).',
    '4. No unnecessary allocations, copies, or repeated computation.',
    '5. Caching/memoization used where it matters; not where it adds invalidation risk (CloudFront behavior for /graphql and public pages, Apollo caching in publicApollo.ts).',
    '6. No premature optimization that hurts readability (COULD/NIT, not a bug).',
    '7. Large payloads/responses bounded or paginated (offer payload, public order count counters, write-cap enforcement).',
  ].join('\n'),

  MAINT: [
    'CATEGORY: MAINT - Maintainability & readability.',
    'Checklist:',
    '1. Code clear on first read; no head-scratching structures.',
    '2. Names meaningful; no `x`, `data`, `temp` where context is lost.',
    '3. Comments explain why, not what; no obvious-state comments.',
    '4. Functions/methods small and self-contained (note the repo complexity gate: xenon max-average A, max-absolute B).',
    '5. Tests cover the change, including the FUNC edge cases (are the new behaviors actually asserted, or only happy paths? are there tests that assert nothing / tautological tests?).',
    '6. No dead code, unused imports, or orphaned paths (schema fields with no resolver, unused functions/variables, unused Terraform variables/outputs).',
    '7. Formatting consistent (defer to linter/formatter where automated - do not report style the toolchain already enforces).',
  ].join('\n'),
};

const LAYERS = {
  FE: 'YOUR LAYER SCOPE = FRONTEND ONLY. Review only: frontend/src/** (new public pages, components, hooks, lib/publicApollo.ts, publicOrderGraphQL.ts, publicOrderSubmit.ts, publicOrderValidation.ts, publicOrders.ts, qrDecode.ts, App.tsx routing, NoIndexMeta.tsx, CampaignSettingsPage.tsx, OrdersPage.tsx), frontend/tests/**, frontend/public/robots.txt, frontend/package.json + package-lock.json, frontend/.env.example. Judge the frontend change on its own terms. Where a concern crosses into the backend and you cannot verify it from the frontend, you may raise it ONCE as an INFO or [X-FE/BE] note - do not speculate.',
  BE: 'YOUR LAYER SCOPE = BACKEND ONLY. Review only: src/handlers/** (public_orders_offer.py, public_orders_receipt.py, public_order_emails.py, campaign_reporting.py, report_generation.py), src/utils/errors.py, tofu/application/schema/schema.graphql, tofu/application/appsync/js-resolvers/** (new public_* / *_public_* functions and lib/public_order.js, lib/public_settings.js, update_order_fn.js), tofu/application/modules/** (appsync, iam, lambda, ses, alarms, environments/*), scripts/**, .github/workflows/deploy-shared.yml, tests/unit/**, tests/integration/**, tests/e2e/**. Judge the backend change on its own terms. Where a concern crosses into the frontend and you cannot verify it from the backend, you may raise it ONCE as an INFO or [X-FE/BE] note - do not speculate.',
  X: 'YOUR LAYER SCOPE = COMBINED / SYSTEM LEVEL ONLY. You own the INTEGRATION SURFACE, not the internals of either layer: the GraphQL contract between frontend/src/lib/publicOrderGraphQL.ts + generated types and tofu/application/schema/schema.graphql + resolver/handler implementations; API-key authN/authZ across the layers (where the API key is minted, injected, exposed to the browser, and what it can reach); the end-to-end data flow share token -> offer -> publicCreateOrder -> receipt token -> receipt page -> SES email -> seller OrdersPage confirm-payment; env/config plumbing (tofu outputs -> scripts/generate_integration_env.py -> .env / frontend/.env.example -> VITE_* -> frontend runtime); and E2E/integration tests that prove the seam. Do NOT re-review pure-frontend or pure-backend internals - other reviewers own those.',
};

const FILESETS = {
  FE: [
    'FILES IN SCOPE (frontend):',
    'frontend/src/App.tsx, components/NoIndexMeta.tsx, components/public/{BuyerContactFields,NoEmailConfirmDialog,PaymentMethodChoice,ProductPicker,PublicOrderSuccess,PublicPageUnavailable,PublicSettingsAckCheckboxes,PublicSettingsActions,PublicSettingsCapNotice,PublicSettingsMethodChecklist,PublicSettingsShareSection,ReceiptStatusChip,publicOrderTypes}.tsx|ts,',
    'hooks/{useCampaignPublicOrderSettings,usePublicOrderForm,usePublicOrderOffer}.ts,',
    'lib/{apollo,graphql,publicApollo,publicOrderGraphQL,publicOrderSubmit,publicOrderValidation,publicOrders,qrDecode}.ts,',
    'pages/{CampaignSettingsPage,OrdersPage,PublicOrderPage,PublicReceiptPage}.tsx, types/graphql-generated.ts,',
    'tests/{CampaignSettingsPage.publicOrders,OrdersPage.confirmPayment,OrdersPage.rowActions}.test.tsx, tests/components/public/*.test.tsx, tests/hooks/useCampaignPublicOrderSettings.test.tsx, tests/lib/{publicOrders,qrDecode}.test.ts,',
    'public/robots.txt, package.json, .env.example, README.md.',
  ].join('\n'),
  BE: [
    'FILES IN SCOPE (backend):',
    'Python: src/handlers/{public_orders_offer,public_orders_receipt,public_order_emails,campaign_reporting,report_generation}.py, src/utils/errors.py.',
    'AppSync JS: tofu/application/appsync/js-resolvers/{create_public_order_fn,get_campaign_public_order_settings_pipeline_resolver,get_profile_for_public_order_fn,increment_public_order_count_fn,locate_campaign_public_settings_fn,lookup_campaign_public_settings_fn,public_create_order_pipeline_resolver,send_public_order_emails_fn,update_campaign_public_order_settings_pipeline_resolver,update_order_fn,validate_campaign_settings_write_fn,validate_payment_method_public_fn,validate_public_settings_catalog_fn,validate_public_token_fn,validate_public_token_step2_fn,verify_public_settings_owner_fn,write_campaign_public_order_settings_fn}.js and lib/{public_order,public_settings}.js (plus their *.test.js).',
    'IaC: tofu/application/schema/schema.graphql, modules/{appsync/{api,datasources_lambda,functions_campaigns,functions_catalogs,functions_orders,functions_profiles,outputs,resolvers_mutations,resolvers_queries}.tf,iam/main.tf,lambda/main.tf,ses/main.tf+templates/*.tpl,alarms/*,environments/{dev,ephemeral,prod}/main.tf}.',
    'Ops/tests: scripts/{ephemeral-env.sh,ephemeral-recover-common.sh,generate_integration_env.py}, .github/workflows/deploy-shared.yml, tests/unit/*.py + tests/unit/check_public_api_key_surface.test.ts, tests/integration/**, tests/e2e/**.',
  ].join('\n'),
  X: [
    'FILES IN SCOPE (integration seam): frontend/src/lib/{publicApollo,publicOrderGraphQL,publicOrderSubmit,publicOrders}.ts + frontend/src/types/graphql-generated.ts <-> tofu/application/schema/schema.graphql + modules/appsync/{api.tf,resolvers_queries.tf,resolvers_mutations.tf,datasources_lambda.tf} + src/handlers/public_orders_*.py; the public API key path (tofu outputs -> scripts/generate_integration_env.py -> .env / frontend/.env.example -> VITE_APPSYNC_API_KEY -> publicApollo.ts -> CloudFront /graphql behavior in modules/cloudfront + .github/workflows/deploy-shared.yml); tests/e2e/{test_smoke_public_orders,test_smoke_auth_boundary}.py + tests/integration/resolvers/publicOrders.integration.test.ts.',
  ].join('\n'),
};

// No run deadline: the built-in 30-minute child backstop killed two reviewers.
// 2147483647 ms is the maximum accepted timeoutMs (~24.8 days), i.e. unbounded
// in practice. The workflow itself stays unbounded at the top level.
const NO_DEADLINE = 2147483647;

function mk(key, label, cat, layer, extra) {
  const task = [PREAMBLE, LAYERS[layer], FILESETS[layer], CATS[cat], extra || ''].filter(Boolean).join('\n\n');
  return {
    key,
    label,
    agent: 'reviewer',
    task,
    output: 'reviews/' + key + '.md',
    outputMode: 'file-only',
    timeoutMs: NO_DEADLINE,
  };
}

const FE_NOTE = 'Layer tag for your findings: [FE].';
const BE_NOTE = 'Layer tag for your findings: [BE].';
const X_NOTE = 'Layer tag for your findings: [X-FE/BE].';

// Concurrency ceiling on this session is 2 subagents, so run a rolling pool of 2.
const TASKS = [
  mk('sec-be', 'Review backend security', 'SEC', 'BE', BE_NOTE),
  mk('sec-x', 'Review cross-layer auth and data-flow security', 'SEC', 'X', X_NOTE),
  mk('sec-fe', 'Review frontend security', 'SEC', 'FE', FE_NOTE),
  mk('func-be', 'Review backend functionality and edge cases', 'FUNC', 'BE', BE_NOTE),
  mk('func-fe', 'Review frontend functionality and edge cases', 'FUNC', 'FE', FE_NOTE),
  mk('arch-be', 'Review backend architecture fit', 'ARCH', 'BE', BE_NOTE),
  mk('arch-x', 'Review system-level architecture and revertability', 'ARCH', 'X', X_NOTE),
  mk('arch-fe', 'Review frontend architecture fit', 'ARCH', 'FE', FE_NOTE),
  mk('perf-be', 'Review backend performance', 'PERF', 'BE', BE_NOTE),
  mk('perf-x', 'Review cross-layer performance and caching', 'PERF', 'X', X_NOTE),
  mk('perf-fe', 'Review frontend performance', 'PERF', 'FE', FE_NOTE),
  mk('dry-be', 'Review backend duplication', 'DRY', 'BE', BE_NOTE),
  mk('dry-fe', 'Review frontend duplication', 'DRY', 'FE', FE_NOTE),
  mk('maint-be', 'Review backend maintainability and tests', 'MAINT', 'BE', BE_NOTE),
  mk('maint-fe', 'Review frontend maintainability and tests', 'MAINT', 'FE', FE_NOTE),
  mk('prin-be', 'Review backend engineering principles', 'PRIN', 'BE', BE_NOTE),
  mk('prin-x', 'Review cross-layer API design consistency', 'PRIN', 'X', X_NOTE),
  mk('prin-fe', 'Review frontend engineering principles', 'PRIN', 'FE', FE_NOTE),
  mk('scope', 'Review PR scope and hygiene', 'SCOPE', 'X', 'Layer-agnostic category: omit layer tags on your findings.'),
];

const all = [];
for (let i = 0; i < TASKS.length; i += 2) {
  const batch = await runs.all(TASKS.slice(i, i + 2));
  for (const r of batch) {
    all.push({
      key: r.key,
      status: r.status,
      outputReference: r.outputReference,
      outputPathMapping: r.outputPathMapping,
      artifactPaths: r.artifactPaths,
    });
  }
}
return { children: all };
