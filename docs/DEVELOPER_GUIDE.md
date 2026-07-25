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

**Test coverage**: auth (login/logout), authorization boundaries (unauthenticated redirect, access control), profile viewing, campaign creation and listing, order creation and listing, profile sharing (invite/accept/revoke/read-only), and signup flow.

**Cleanup**: after each run, a `global_cleanup` fixture deletes all DynamoDB records owned by the test users (profiles, campaigns, orders, shares, invites) while preserving Cognito users and Account records.

### Code Quality
- **Python (app)**: `uv run ruff check src tests` • `uv run ruff check --select I --fix src/ tests/` • `uv run ruff format src/ tests/` • `uv run mypy src`
- **Frontend**: `cd frontend && npm run lint` • `cd frontend && npm run format` • `cd frontend && npm run typecheck`
- Coverage bars: app code is 100% (src, frontend).

### Deployment
- **Backend/OpenTofu (dev only)**:
  - From the repo root: `./tofu/application/scripts/deploy.sh dev apply`
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

#### Centralized Validation (`src/utils/validation.py`)

All input validation for Lambda handlers should use the centralized validation module:

```python
from utils.validation import (
    validate_required_fields,
    validate_unit_number,
    validate_unit_fields,
)

# Validate required fields are present
validate_required_fields(data, ["profileId", "campaignName"])

# Validate unit number format (optional field)
validate_unit_number(unit_number, required=False)

# Validate complete unit information
validate_unit_fields(unit_type, unit_number, city, state)
```

All validation functions raise `AppError` with `ErrorCode.INVALID_INPUT` on failure.

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

#### ID Generation (`src/utils/ids.py`)

Use centralized ID normalization helpers for consistent prefixed IDs:

```python
from utils.ids import ensure_prefix, strip_prefix

# Ensure an ID has the correct prefix
profile_id = ensure_prefix("PROFILE", user_input)

# Remove the prefix to get the raw UUID
raw_id = strip_prefix(profile_id)
```

#### Error Handling (`src/utils/errors.py`)

Use `AppError` for all application errors:

```python
from utils.errors import AppError, ErrorCode

raise AppError(ErrorCode.INVALID_INPUT, "Profile name is required")
raise AppError(ErrorCode.NOT_FOUND, "Campaign not found")
raise AppError(ErrorCode.UNAUTHORIZED, "Not authorized to view this profile")
```

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

All GraphQL types are centralized and should be imported from the types module:

```typescript
import type { SellerProfile, Campaign, Order, Catalog } from '../types';
```

### OpenTofu Infrastructure Patterns

#### Helper Utilities (`tofu/application/modules/*/`)

Use centralized modules for resource configuration. The application defines eight
separate DynamoDB tables (not a single-table design); see
`tofu/application/modules/dynamodb/main.tf` for the current schema and indexes.

#### AppSync Resolvers (`tofu/application/modules/appsync/`)

AppSync resolvers are defined in OpenTofu using `aws_appsync_resolver` and `aws_appsync_function` resources:

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