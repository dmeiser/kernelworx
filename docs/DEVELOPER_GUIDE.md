## Developer Workflow Guide

Audience: contributors working on Popcorn Sales Manager. Focuses on day-to-day commands, quality bars, and deployment steps. Infra coverage is intentionally excluded from coverage gates per project policy.

### Testing
- **Backend Lambdas (Python)**
  - Unit tests (100% enforced):
    - From repo root: `uv run pytest tests/unit --cov=src --cov-fail-under=100`
- **Infrastructure/CDK (Python)**
  - No unit tests maintained; CDK coverage is intentionally excluded. Optional synth/snapshot checks are allowed locally but are not required.
- **Frontend (TypeScript)**
  - Unit/component tests with coverage: `npm run test -- --coverage`
  - E2E (optional): `npm run test:e2e` if configured.

### Code Quality
- **Python (app)**: `uv run ruff check src tests` • `uv run isort src/ tests/` • `uv run ruff format src/ tests/` • `uv run mypy src`
- **Python (cdk)**: `cd cdk && uv run ruff check cdk tests` • `uv run mypy cdk`
- **Frontend**: `npm run lint` • `npm run format` • `npm run typecheck`
- Coverage bars: app code is 100% (src, frontend); CDK infra is excluded from coverage enforcement.

### Deployment
- **Backend/OpenTofu (dev only)**:
  - From `tofu/environments/dev/`: `tofu apply`
  - Preview first when making infra changes: `tofu plan` (respect dev-only deployment rule).
- **Frontend**:
  - From `frontend/`: `./deploy.sh` (ensure build succeeds locally with `npm run build`).

### Notes & Conventions
- Always use feature branches and PRs; never push directly to main.
- When running coverage, exclude CDK by scoping `--cov` to application packages (e.g., `--cov=src`).
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

Use the centralized DynamoDB utilities for consistent table access:

```python
from utils.dynamodb import get_table, get_table_name

# Get a boto3 Table resource
table = get_table()

# Get just the table name
table_name = get_table_name()
```

#### ID Generation (`src/utils/ids.py`)

Use centralized ID generation for consistent formatting:

```python
from utils.ids import normalize_id, generate_unique_id

# Normalize user-provided IDs
profile_id = normalize_id(user_input)

# Generate new unique IDs
new_id = generate_unique_id()
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

#### Helper Utilities (`tofu/modules/*/`)

Use centralized modules for resource configuration:

```hcl
# Example from tofu/modules/dynamodb/main.tf
resource "aws_dynamodb_table" "main" {
  name         = "${var.name_prefix}-app-${var.region_abbrev}-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"
}
```

#### AppSync Resolvers (`tofu/modules/appsync/`)

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