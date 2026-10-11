## Developer Workflow Guide

Audience: contributors working on KernelWorx. Focuses on day-to-day commands, quality bars, and deployment steps. Infra coverage is intentionally excluded from coverage gates per project policy.

### Testing

#### Backend Lambdas (Python)
- Unit tests (100% enforced):
  ```bash
  uv run pytest tests/unit --cov=src --cov-fail-under=100
  ```

#### Frontend (TypeScript)
- Unit/component tests with coverage:
  ```bash
  npm run test -- --coverage
  ```

#### E2E Smoke Tests (Python + Playwright)

End-to-end tests run against the **deployed dev environment** (`https://dev.kernelworx.app`) using Playwright for Python (Chromium). See [`tests/e2e/README.md`](../tests/e2e/README.md) for full setup instructions.

**Prerequisites** (one-time):
1. Dev environment deployed (`./tofu/application/scripts/deploy.sh dev apply` from the repo root)
2. Test users created: `bash scripts/create-test-users.sh`
3. At least one admin-managed catalog exists in the dev app
4. `.env` populated with e2e credentials and DynamoDB table names (see `.env.example`)
5. Playwright browsers installed: `uv run playwright install chromium`

**Running e2e tests**:
```bash
# Full suite
uv run pytest tests/e2e/ --ignore=tests/unit -v

# Single file
uv run pytest tests/e2e/test_smoke_auth.py -v
```

**Test coverage**: see the *Test file overview* table in [`tests/e2e/README.md`](../tests/e2e/README.md) — the per-suite list is maintained there, not duplicated here.

**Cleanup**: after each run, a `global_cleanup` fixture deletes all DynamoDB records owned by the test users (profiles, campaigns, orders, shares, invites) while preserving Cognito users and Account records.

### Code Quality
- **Python (app)**: `uv run ruff check src tests` • `uv run ruff check --select I --fix src/ tests/` • `uv run ruff format src/ tests/` • `uv run mypy src`
- **Frontend**: `cd frontend && npm run lint` • `cd frontend && npm run format` • `cd frontend && npm run typecheck`
- Coverage bars: app code is 100% (src, frontend).

### Deployment
- **Backend/OpenTofu (dev only)**:
  - From the repo root (after `npm install`): `./tofu/application/scripts/deploy.sh dev apply` (the helper bundles resolver JS automatically)
  - Preview first when making infra changes: `./tofu/application/scripts/deploy.sh dev plan` (respect dev-only deployment rule).
- **Frontend**:
  - From `frontend/`: `./deploy.sh` (ensure build succeeds locally with `npm run build`).

### Notes & Conventions
- Always use feature branches and PRs; never push directly to main.
- Scope `--cov` to application packages (e.g., `--cov=src`).
- Prefer moto for AWS mocks in backend unit tests; LocalStack or AWS dev account for integration as needed.

---

## Code Patterns & Conventions

This section documents the key patterns and shared utilities used throughout the codebase.

### Backend Python Patterns

#### Resolver argument and unit validation (`src/utils/appsync_types.py`, `src/utils/validation.py`)

Lambda handlers that read resolver arguments should use the shared readers, which enforce the schema types and bounds before the handler indexes into the raw event, raising a typed `INVALID_INPUT` `AppError`:

```python
from utils.appsync_types import require_int, require_str, require_unit_number

# Require a non-empty string argument
profile_id = require_str(input_args, "profileId")

# Require an integer argument
campaign_year = require_int(arguments, "campaignYear")

# Require a scout unit number (positive integer)
unit_number = require_unit_number(arguments, "unitNumber")
```

The caller ID is read with `get_caller_id(event)` from the same module; never hand-inline `event["identity"]["sub"]`, which raises `KeyError` on an unauthenticated invocation (`tests/unit/test_caller_id_helper.py` guards this).

Validation failures raise `AppError` with `ErrorCode.INVALID_INPUT`. The equivalent rules are also enforced in the AppSync JS resolvers in `tofu/application/appsync/js-resolvers/`.

#### Cognito user filters (`src/utils/cognito_filters.py`)

Cognito's `ListUsers` `Filter` is a string-interpolated query language, so never hand-write one. Build every user filter with the shared formatter, which validates the value and returns the finished expression:

```python
from utils.cognito_filters import cognito_user_filter

cognito.list_users(UserPoolId=pool_id, Filter=cognito_user_filter("sub", account_id), Limit=1)
cognito.list_users(UserPoolId=pool_id, Filter=cognito_user_filter("email_prefix", query), Limit=50)
cognito.list_users(UserPoolId=pool_id, Filter=cognito_user_filter("email", email, email_shape="strict"), Limit=1)
```

Fields are `sub`, `email`, and `email_prefix` (`email ^=`, starts-with); `email_shape` is `loose` (default) or `strict` and only applies to `email`. See the module docstring for the rules and `tests/unit/test_cognito_filter_call_sites.py` for the call-site table.

#### DynamoDB Utilities (`src/utils/dynamodb.py`)

Use the centralized `tables` singleton for table access:

```python
from utils.dynamodb import tables

# Access a table by name
accounts = tables.accounts
profiles = tables.profiles
```

Each table property returns a boto3 `Table` resource. Table names are read from the
`ACCOUNTS_TABLE_NAME`, `PROFILES_TABLE_NAME`, etc. environment variables. For tests,
use `override_table()` to inject mock tables.

Resolution is fail-loud: `get_required_env` raises `ValueError` naming the variable when it
is unset, so a missing table env var surfaces as a Lambda error instead of a plausible but
wrong read. Keep it that way — never give a handler its own `os.environ` lookup with a
hard-coded fallback table name, and never hard-code an environment-specific table name in
`src/`; a fallback silently reads the wrong environment's table and returns a normal-looking
result. When a handler needs the name for a raw call (e.g. `BatchGetItem` on the resource),
read it from the accessor: `tables.catalogs.table_name`.

#### AWS Clients (`src/utils/boto.py`)

Build S3 and admin-Cognito clients with the shared factories, not a local `boto3.client(...)`:

```python
from utils.boto import get_cognito_client, get_s3_client

cognito = get_cognito_client()
s3 = get_s3_client()
```

Endpoint overrides (`S3_ENDPOINT`, `COGNITO_ENDPOINT`) are read and validated in exactly that
module — a set value must be an `http(s)` URL with a host, so an override is honored
everywhere it applies or raises, never silently dropped by one call site. The `get_s3_client`
override argument exists only for the pre-existing per-module `s3_client` test seam
(`src/utils/payment_methods.py`, `src/handlers/report_generation.py`,
`src/handlers/delete_profile_cascade.py`); production code passes nothing.

Deliberate exceptions: the `pre-token-generation` trigger builds its Cognito client once at
module scope for warm-start connection reuse (#458), and the account-deletion and pre-signup
handlers build per-call Cognito clients. `DYNAMODB_ENDPOINT` is still read unvalidated in
`src/utils/dynamodb.py` (#523).

#### ID Generation (`src/utils/ids.py`)

Use centralized ID normalization helpers for consistent prefixed IDs:

```python
from utils.ids import ensure_prefix, strip_prefix

# Ensure an ID has the correct prefix
profile_id = ensure_prefix("PROFILE", user_input)

# Remove the prefix to get the raw UUID
raw_id = strip_prefix(profile_id)
```

`build_unit_campaign_key` owns the `unitCampaignKey-index` partition-key layout
(`unitType#unitNumber#city#state#campaignName#campaignYear`). Unit reporting, unit catalog
listing, and the campaign write path (`CreateCampaignInput.build_unit_campaign_key`) all use
it, so the layout has exactly one definition and no call site rebuilds the string. The format
cannot change without a data migration.

#### Error Handling (`src/utils/errors.py`)

Use `AppError` for all application errors:

```python
from utils.errors import AppError, ErrorCode

raise AppError(ErrorCode.INVALID_INPUT, "Profile name is required")
raise AppError(ErrorCode.NOT_FOUND, "Campaign not found")
raise AppError(ErrorCode.UNAUTHORIZED, "Not authorized to view this profile")
```

Do not translate a failed DynamoDB/Cognito lookup yourself, and never return the survivors of an
`asyncio.gather(..., return_exceptions=True)` as the answer to a list query: a truncated list reads
as "none in use" and gets acted on. `admin_operations._raise_batch_lookup_error` (one failure) and
`_raise_gather_failures` (a collected list) own that classification — see AGENTS.md.

#### Cognito Retries (`src/utils/cognito.py`)

Do not hand-roll a backoff loop for Cognito User Pool calls; wrap the client method:

```python
from utils.cognito import retry_on_transient_errors

users = retry_on_transient_errors(cognito.list_users, UserPoolId=pool_id, Filter=f'sub = "{sub}"')
```

`retry_on_transient_errors` retries up to 3 attempts on `TooManyRequestsException`,
`InternalErrorException`, and `ProvisionedThroughputExceededException` (0.1s/0.2s backoff) and
re-raises everything else unchanged, so callers keep their own handling of terminal codes
(e.g. `UserNotFoundException`).

### Frontend TypeScript Patterns

#### Form State Hook (`frontend/src/hooks/useFormState.ts`)

For dialog forms with multiple fields, use the `useFormState` hook:

```typescript
import { useFormState } from '../hooks/useFormState';

interface FormValues {
  name: string;
  email: string;
  isActive: boolean;
}

const getInitialValues = (): FormValues => ({
  name: '',
  email: '',
  isActive: true,
});

function MyDialog() {
  const { values, setValue, reset, isDirty } = useFormState(getInitialValues);
  
  return (
    <>
      <TextField
        value={values.name}
        onChange={(e) => setValue('name', e.target.value)}
      />
      <Button onClick={reset}>Reset</Button>
    </>
  );
}
```

The hook provides:
- `values` - Current form state
- `setValue(key, value)` - Update a single field
- `setValues(partial)` - Update multiple fields
- `reset()` - Reset to initial values
- `resetTo(values)` - Reset to specific values
- `isDirty` - Whether form has been modified

**When NOT to use `useFormState`:**
- Complex array state (product lists, line items) - use custom hooks
- Fields with special formatting (phone numbers) - use specialized hooks
- When the existing pattern is already well-organized with custom hooks

#### GraphQL Types (`frontend/src/types/index.ts`)

All GraphQL types are generated by graphql-codegen and centralized in
`frontend/src/types/graphql-generated.ts`, re-exported through `frontend/src/types/index.ts`.
They are prefixed with `Gql` to avoid conflicts and should be imported from the types module:

```typescript
import type { GqlSellerProfile, GqlCampaign, GqlOrder, GqlCatalog } from '../types';
```

### OpenTofu Infrastructure Patterns

#### Helper Utilities (`tofu/application/modules/*/`)

Use centralized modules for resource configuration. The application defines eight
separate DynamoDB tables (not a single-table design); see
`tofu/application/modules/dynamodb/main.tf` for the current schema and indexes.

#### AppSync Resolvers (`tofu/application/modules/appsync/`)

AppSync resolvers are defined in OpenTofu using `aws_appsync_resolver` and `aws_appsync_function` resources. Resolver JavaScript lives in `tofu/application/appsync/js-resolvers/`; OpenTofu reads the bundled output at `tofu/application/appsync/dist/`, produced by `npm run build:resolvers` (esbuild inlines the shared `js-resolvers/lib/` modules). Run the build before any `tofu plan`/`apply`/`import`/`destroy` — the tofu commands fail when `dist/` is missing, and a stale `dist/` deploys outdated resolver code:

```bash
npm run build:resolvers
```

```hcl
# VTL resolver
resource "aws_appsync_resolver" "get_my_account" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "getMyAccount"
  data_source = aws_appsync_datasource.accounts.name

  request_template  = file("${local.mapping_templates_dir}/get_my_account_request.vtl")
  response_template = file("${local.mapping_templates_dir}/get_my_account_response.vtl")
}

# JavaScript resolver
resource "aws_appsync_resolver" "list_items" {
  api_id      = aws_appsync_graphql_api.main.id
  type        = "Query"
  field       = "listItems"
  data_source = aws_appsync_datasource.items.name
  code        = file("${local.js_resolvers_dir}/list_items.js")

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }
}

# Pipeline resolver
resource "aws_appsync_resolver" "create_item" {
  api_id = aws_appsync_graphql_api.main.id
  type   = "Mutation"
  field  = "createItem"
  kind   = "PIPELINE"
  code   = file("${local.js_resolvers_dir}/create_item.js")

  pipeline_config {
    functions = [
      aws_appsync_function.validate.function_id,
      aws_appsync_function.create.function_id,
    ]
  }

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }
}
```