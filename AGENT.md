# AGENT.md — Rules and behaviors for AI agents

This file contains repository-specific agent rules. Agents should follow these when making changes to the Popcorn Sales Manager project.

## CRITICAL GIT RULES

- **NEVER push directly to main branch** - All changes MUST go through pull requests
- **NEVER use `git push origin main`** - This bypasses branch protection and CI/CD
- **NEVER approve PRs** - PR approval requires human judgment and review
- **NEVER merge PRs** - PR merging is a human decision with accountability
- Always work on feature branches and create PRs for review
- Let humans review, approve, and merge PRs
- Let GitHub Actions workflows validate changes before merging (when CI/CD is implemented)

## Project Overview

**Purpose**: Volunteer-run web application to help Scouts and families manage in-person popcorn sales for fundraising.

**Tech Stack**:
- **Frontend**: React + TypeScript + Vite + MUI + Apollo Client + react-router
- **Backend**: AWS AppSync (GraphQL) + Lambda (Python) + DynamoDB
- **Infrastructure**: AWS CDK (Python)
- **Auth**: Amazon Cognito (User Pools with Google/Facebook/Apple social login)
- **Storage**: Amazon S3 (static assets, report exports)
- **Notifications**: Amazon SES/SNS (email)
- **Audit**: Kinesis Firehose → S3
- **Package Management**: uv for Python, npm for frontend
- **License**: MIT (open source)
- **Context**: Volunteer-run, cost-conscious, targeting Scouting America community

## Development Principles

- **Minimal changes**: Keep edits surgical and self-contained. Prefer adding new files over editing many unrelated files.
- **Environment-first config**: Use environment variables for configuration (API keys, region, profile IDs, etc.).
- **Security**: Never commit secrets or API keys. Use AWS Secrets Manager or environment variables.
- **Cost awareness**: Use AWS Free Tier where possible. Monitor spending. Optimize for serverless/pay-per-use.
- **Volunteer-friendly**: Document everything. Make setup easy. Avoid complex tooling.
- **Privacy-first**: Treat all user and customer data as sensitive PII. Encrypt in-flight and at-rest.
- **Accessibility**: Target WCAG 2.1 AAA (aspirational). High contrast, keyboard navigation, screen reader support.
- **Testing**: 100% unit test coverage required. No exceptions.

## Code Quality Standards

All code changes must meet the following quality metrics before work is considered complete.

### 1. Python Code Formatting and Type Checking

**Workflow Order**:
1. Make code changes
2. Write/update tests
3. Run formatters: `isort` → `ruff format`
4. Run type checker: `mypy` (fix any errors)
5. Run tests and validation
6. **If any code changes are needed after validation, repeat the formatting steps**

**Commands**:
```bash
# 1. Organize imports
uv run isort src/ tests/

# 2. Format code
uv run ruff format src/ tests/

# 3. Type checking
uv run mypy src/
```

**Configuration** (in `pyproject.toml`):
- **ruff**: line-length = 120
- **isort**: profile = "black" (compatibility)
- **mypy**: strict mode, ignore missing imports where necessary

The last commits before a successful validation run MUST be formatting/type-checking changes only.

### 2. Python Unit Test Coverage Requirements

**CRITICAL**: All unit tests must pass with 100% success rate. Failing tests are NEVER acceptable.

**Coverage Target: 100%**
- **Project-wide**: 100% code coverage
- **Per-file**: 100% coverage (no exceptions)
- **Per-function**: 100% coverage

**Running Coverage**:
```bash
# Generate coverage report
uv run pytest tests/unit --cov=src --cov-report=term-missing --cov-report=html --cov-fail-under=100

# View HTML report
open htmlcov/index.html
```

**Coverage Validation**:
- Check overall percentage in terminal output (must be 100%)
- Review HTML report for per-file coverage
- Ensure every file shows 100%
- **All tests must pass** - zero failures, zero errors

**Test Cleanup Requirements**:
- **CRITICAL**: All automated tests (unit, integration, and any other) must clean up after themselves
- Each test must delete any DynamoDB records created during testing
- Each test must delete any S3 objects created during testing
- Before marking a test as "complete", verify cleanup by:
  1. Running the test successfully
  2. Checking DynamoDB/S3 to confirm all test data has been deleted
- Use `@mock_dynamodb` and `@mock_s3` decorators from `moto` to ensure proper cleanup
- Tests that leave orphaned data are considered INCOMPLETE and must be fixed before merge
- **Global cleanup** (integration tests): The global teardown process (`globalTeardown.ts`) deletes all data created by test users EXCEPT their Account records and Cognito user profiles. This allows tests to reuse the same test user accounts across multiple test runs while cleaning up all generated data (campaigns, orders, shares, invites, catalogs, shared campaigns, seller profiles)

**Mocking Strategy**:
- Use `moto` for mocking AWS services (DynamoDB, S3, SNS/SES, EventBridge)
- Use `pytest` fixtures for common test data
- Mock external API calls (AppSync, Cognito)
- Create comprehensive test fixtures for accounts, profiles, campaigns, orders

### 3. TypeScript/React Testing Requirements

**Coverage Target: 100%**
- All React components must have 100% test coverage
- All custom hooks must have 100% test coverage
- All utility functions must have 100% test coverage

**Testing Framework**: Vitest (recommended for Vite projects)

**Running Tests**:
```bash
# Run all tests with coverage
npm run test -- --coverage

# Run tests in watch mode during development
npm run test -- --watch
```

**Testing Strategy**:
- **Unit tests**: Test components in isolation with mocked dependencies
- **Integration tests**: Test component interactions and Apollo Client queries/mutations
- **Accessibility tests**: Validate ARIA labels, keyboard navigation, screen reader support
- Use MSW (Mock Service Worker) or Apollo MockedProvider for GraphQL mocking

### 4. Pre-Commit Quality Checklist (Backend/Python)

Before claiming work is complete:

- [ ] Run `uv run isort src/ tests/`
- [ ] Run `uv run ruff format src/ tests/`
- [ ] Run `uv run mypy src/` (0 errors)
- [ ] Run `uv run pytest tests/unit --cov=src --cov-fail-under=100` (100% coverage, ALL tests pass)
- [ ] Review HTML coverage report: all files 100%
- [ ] Commit formatting changes as final commit before validation

**CRITICAL**: If ANY check fails, fix the issues and restart from step 1. Continue iterating until 100% of quality standards are met with zero failures.

### 5. Pre-Commit Quality Checklist (Frontend/TypeScript)

Before claiming work is complete:

- [ ] Run `npm run lint` (0 errors, 0 warnings)
- [ ] Run `npm run format` (Prettier)
- [ ] Run `npm run typecheck` (0 TypeScript errors)
- [ ] Run `npm run test -- --coverage` (100% coverage, ALL tests pass)
- [ ] Verify accessibility with automated tools
- [ ] Commit formatting changes as final commit before validation

## Testing Strategy

### Backend Testing (Lambda Functions)

**Unit Tests** (`tests/unit/`):
- Fast, isolated tests with mocked AWS services
- Mock DynamoDB, S3, SNS/SES, EventBridge using `moto`
- Test all business logic paths (owner, shared READ/WRITE, admin)
- Test all error handling and edge cases
- Test all validation logic (customer input, invite expiration, etc.)
- **Required**: 100% code coverage, all tests pass

**Integration Testing**:
- Test against AWS dev account or LocalStack Pro (if approved)
- Validate end-to-end flows (auth, GraphQL, Lambda, DynamoDB)
- Test report generation and S3 uploads
- Test email notifications

### Frontend Testing (React)

**Unit/Component Tests** (`src/**/__tests__/`):
- Test all pages (LoginPage, ProfilesPage, OrdersPage, etc.)
- Test all form components (OrderEditorDialog, profile/campaign dialogs)
- Test all list components (ProfileList, CampaignList, OrderList)
- Test AuthProvider and authentication flows
- Test Apollo Client error handling
- Test authorization-based UI rendering (owner vs shared permissions)
- Test toast notifications and error states
- **Required**: 100% code coverage, all tests pass

**E2E Tests (Optional, Playwright)**:
- If time allows after 100% unit coverage is achieved
- Test critical user flows (account creation, order placement, report download)
- Test admin flows (ownership transfer, hard delete)
- Cross-browser testing (Chromium, Firefox, WebKit)

## AWS Development Environment

**Testing Environments**:
- **Unit tests**: Use `moto` for local AWS service mocking
- **Integration tests**: Use LocalStack Pro (if OSS license approved) or AWS dev account
- **Cost controls**: DynamoDB on-demand, AWS Budget alerts ($10-20/month for dev)

**LocalStack Pro (Optional)**:
- Apply for OSS license (free for open source projects)
- If approved, use for local Cognito/AppSync/CloudFront testing
- If denied, use AWS dev account

## Architecture Notes

**GraphQL Schema**: Defined in `Planning Documents/graphql_schema_v1.md`
**DynamoDB Schema**: Defined in `Planning Documents/dynamodb_physical_schema_v1.md`
**Authorization Model**: Owner-based + Share-based (READ/WRITE permissions)
**Auth Flow**: Cognito User Pools → AppSync → Lambda/VTL/JS resolvers

## Lambda Simplification Initiative

**Status**: Phase 2 Complete - 53% reduction achieved (see `TODO_SIMPLIFY_LAMBDA.md`)

The project initially had 15 Lambda functions. After Phase 1 and Phase 2 implementations, it now has 7 Lambda functions (53% reduction). The goal is to reduce to 2-3 functions (only those that truly require Lambda).

### Resolver Types (Prefer in This Order)

1. **VTL Resolvers** - Best for simple GetItem/PutItem/Query/DeleteItem
2. **JavaScript Resolvers** - Best for computed fields, ID generation, simple logic
3. **Pipeline Resolvers** - Best for multi-step operations (Query GSI → Update/Delete)
4. **Lambda Resolvers** - Only for external dependencies (S3, Excel, email) or complex transactions

### Lambda Functions to KEEP (2-3 total)

| Function | Reason |
|----------|--------|
| `kernelworx-post-auth` | Cognito trigger (not AppSync) |
| `kernelworx-request-report` | Requires openpyxl, S3 operations |
| `kernelworx-create-profile` | DynamoDB transaction (optional - could be pipeline) |

### Lambda Functions to REMOVE (10-12 total)

Replace with VTL/JS/Pipeline resolvers. See `TODO_SIMPLIFY_LAMBDA.md` for detailed migration plan.

**Quick Wins (VTL/JS)** - ✅ COMPLETED:
- ✅ `list-orders-by-campaign` → VTL Query (DEPLOYED)
- ✅ `revoke-share` → VTL DeleteItem (DEPLOYED)
- ⏸️ `create-invite` → JS resolver (DEFERRED - kept as Lambda due to AppSync JS issues)

**Pipeline Resolvers** - ✅ COMPLETED:
- ✅ `update-campaign` → Query GSI7 → UpdateItem (DEPLOYED)
- ✅ `update-order` → Query GSI6 → UpdateItem (DEPLOYED)
- ✅ `delete-campaign` → Query GSI7 → DeleteItem (DEPLOYED)
- ✅ `delete-order` → Query GSI6 → DeleteItem (DEPLOYED)
- `delete-order` → Query GSI6 → DeleteItem
- `create-order` → GetItem catalog → PutItem order (with JS for line item enrichment)

### AppSync Resolver Patterns

**VTL Query Pattern** (use for list operations):
```vtl
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "PK = :pk AND begins_with(SK, :sk)",
        "expressionValues": {
            ":pk": $util.dynamodb.toDynamoDBJson($ctx.args.campaignId),
            ":sk": $util.dynamodb.toDynamoDBJson("ORDER#")
        }
    }
}
```

**JavaScript Resolver Pattern** (use for computed values):
```javascript
export function request(ctx) {
    const inviteCode = util.autoId().substring(0, 8).toUpperCase();
    return {
        operation: "PutItem",
        key: util.dynamodb.toMapValues({ PK: ctx.args.profileId, SK: `INVITE#${inviteCode}` }),
        attributeValues: util.dynamodb.toMapValues({
            inviteCode,
            expiresAt: util.time.nowEpochSeconds() + (14 * 24 * 60 * 60),
            // ...
        }),
        condition: { expression: "attribute_not_exists(PK)" }
    };
}

export function response(ctx) {
    return ctx.result;
}
```

**Pipeline Resolver Pattern** (use for GSI lookup → mutation):
```python
# In CDK - create pipeline with two functions
pipeline = api.create_resolver(
    "UpdateCampaignPipeline",
    type_name="Mutation",
    field_name="updateCampaign",
    pipeline_config=[lookup_function, update_function],
    # request/response templates pass data between functions
)
```

### Key Principle: Avoid Lambda When Possible

**Before creating a Lambda resolver, ask:**
1. Can this be a single DynamoDB operation? → Use VTL
2. Does it need ID generation or simple computation? → Use JS resolver
3. Does it need to query then update/delete? → Use Pipeline resolver
4. Does it need external services (S3, email) or transactions? → Use Lambda

## Key Files

- `TODO.md`: Track progress and current phase
- `TODO_SIMPLIFY_LAMBDA.md`: Lambda reduction analysis and migration plan
- `Planning Documents/`: Complete requirements, architecture, schemas
- `docs/VTL_RESOLVER_NOTES.md`: VTL resolver capabilities and limitations
- `GAP_ANALYSIS.md`: Planning completeness assessment
- `AGENT.md`: This file - AI agent rules and guidelines
- `.github/copilot-instructions.md`: GitHub Copilot specific instructions

## Safety Rules

- **NEVER delete user data** without explicit confirmation
- **NEVER commit secrets** (API keys, credentials)
- **Test data only**: Use test/dev accounts for integration testing
- **Privacy**: Handle all customer PII with care
- **Cost monitoring**: Check AWS costs regularly, set budget alerts

## Common Patterns

**Add new Lambda function**:
1. Create function in `src/lambdas/`
2. Add to CDK stack with appropriate IAM permissions
3. Create unit tests with 100% coverage using `moto` mocks
4. Run formatters: `isort` → `ruff format` → `mypy`
5. Deploy to dev environment and test

**Add new GraphQL mutation/query**:
1. Update GraphQL schema
2. Create AppSync resolver (direct DynamoDB or Lambda)
3. Add authorization checks (owner/share/admin)
4. Create unit tests for resolver logic
5. Test with Apollo Client in frontend

**Add new React component**:
1. Create component in `src/components/`
2. Add TypeScript types
3. Create unit tests with Vitest
4. Test accessibility (keyboard nav, ARIA labels)
5. Achieve 100% coverage

## When in Doubt

- **Ask the repo owner** before making large design changes
- **Refer to planning documents** for requirements and architecture decisions
- **Follow the TODO.md** for current phase and priorities
- **Maintain 100% test coverage** - no exceptions
