````instructions
# Popcorn Sales Manager - GitHub Copilot Instructions

Essential knowledge for GitHub Copilot when working on this volunteer-run Scouting America popcorn sales management application.

## 0. CRITICAL GIT RULES

**NEVER push directly to main branch!**

- ❌ NEVER use `git push origin main`
- ❌ NEVER bypass pull requests
- ❌ NEVER approve PRs (`gh pr review --approve`)
- ❌ NEVER merge PRs (`gh pr merge`)
- ✅ ALWAYS work on feature branches
- ✅ ALWAYS create PRs for all changes
- ✅ Let humans review and approve PRs
- ✅ Let humans merge PRs after approval

## 1. Project Architecture

**Full-stack serverless application**:
- **Frontend**: React + TypeScript + Vite + MUI + Apollo Client
- **API**: AWS AppSync (GraphQL)
- **Functions**: AWS Lambda (Python 3.13)
- **Data**: Amazon DynamoDB (single-table design)
- **Auth**: Amazon Cognito User Pools (Google/Facebook/Apple social login)
- **Infrastructure**: AWS CDK (Python)
- **Package Management**: uv (Python), npm (frontend)

**Key Design Patterns**:
- **Single-table DynamoDB**: `PK`/`SK` with GSI1, GSI2, GSI3 (see `Planning Documents/dynamodb_physical_schema_v1.md`)
- **GraphQL schema**: See `Planning Documents/graphql_schema_v1.md`
- **Authorization**: Owner-based + Share-based (READ/WRITE permissions)
- **100% test coverage**: No exceptions, all tests must pass

## 2. Domain Model (Quick Reference)

**Core Entities**:
- **Account**: Cognito user + app metadata (`isAdmin`)
- **SellerProfile**: Individual seller (Scout), owned by Account
- **Season**: Fundraising season for a SellerProfile
- **Catalog**: Product catalog (admin-managed or user-created)
- **Order**: Customer order with line items, payment method
- **Share**: Per-profile access grant (READ or WRITE permissions)

**Key Relationships**:
- Account owns multiple SellerProfiles
- SellerProfile has multiple Seasons
- Season uses one Catalog and has multiple Orders
- Share grants Account access to another Account's SellerProfile

## 3. Python Code Standards (Backend)

**CRITICAL**: 100% test coverage required. All tests must pass.

**Development Workflow**:
1. Write code
2. Write tests (100% coverage)
3. Run: `uv run isort src/ tests/`
4. Run: `uv run black src/ tests/`
5. Run: `uv run mypy src/` (0 errors)
6. Run: `uv run pytest tests/unit --cov=src --cov-fail-under=100` (100% coverage, all pass)

**Configuration** (`pyproject.toml`):
```toml
[tool.black]
line-length = 100
target-version = ["py313"]

[tool.isort]
profile = "black"

[tool.mypy]
strict = true
```

**Testing with moto**:
```python
from moto import mock_dynamodb
import boto3

@mock_dynamodb
def test_create_profile():
    # Create mock DynamoDB table
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.create_table(
        TableName='PsmApp',
        KeySchema=[
            {'AttributeName': 'PK', 'KeyType': 'HASH'},
            {'AttributeName': 'SK', 'KeyType': 'RANGE'}
        ],
        # ... GSIs, etc.
    )
    # Test your function
    result = create_profile(...)
    assert result['profileId'] is not None
```

## 4. TypeScript/React Code Standards (Frontend)

**CRITICAL**: 100% test coverage required. All tests must pass.

**Development Workflow**:
1. Write component
2. Write tests (100% coverage)
3. Run: `npm run lint`
4. Run: `npm run format`
5. Run: `npm run typecheck`
6. Run: `npm run test -- --coverage` (100% coverage, all pass)

**Testing with Vitest**:
```typescript
import { render, screen } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing';
import { ProfileCard } from './ProfileCard';

test('renders profile card with owner badge', () => {
  const mocks = [/* Apollo mocks */];
  
  render(
    <MockedProvider mocks={mocks}>
      <ProfileCard profileId="123" isOwner={true} />
    </MockedProvider>
  );
  
  expect(screen.getByText('Owner')).toBeInTheDocument();
});
```

**Accessibility Requirements**:
- All interactive elements must have ARIA labels
- Support keyboard navigation (Tab, Enter, Escape)
- High contrast colors (WCAG 2.1 AAA aspirational)
- Test with screen readers when possible

## 5. AWS CDK Patterns

**Stack Organization**:
```python
from aws_cdk import (
    Stack,
    aws_dynamodb as dynamodb,
    aws_cognito as cognito,
    aws_appsync as appsync,
)

class PopcornSalesStack(Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        
        # DynamoDB table with GSIs
        table = dynamodb.Table(self, "PsmApp",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.ON_DEMAND,  # Cost-effective
            point_in_time_recovery=True,
        )
        
        # Add GSI1, GSI2, GSI3...
```

**Environment-specific configuration**:
```python
# Use CDK context for environment switching
if self.node.try_get_context("environment") == "localstack":
    # LocalStack endpoints
else:
    # AWS endpoints
```

## 6. Authorization Pattern

**Access Control Logic**:
```python
def check_profile_access(caller_account_id: str, profile_id: str, action: str) -> bool:
    """
    Check if caller can perform action on profile.
    
    Actions: 'read', 'write', 'admin'
    
    Returns True if:
    - Caller is owner (ownerAccountId == caller_account_id)
    - Caller has Share with appropriate permissions
    - Caller is admin (for override scenarios)
    """
    # Check ownership
    profile = get_profile(profile_id)
    if profile['ownerAccountId'] == caller_account_id:
        return True
    
    # Check shares
    share = get_share(profile_id, caller_account_id)
    if share:
        if action == 'read' and 'READ' in share['permissions']:
            return True
        if action == 'write' and 'WRITE' in share['permissions']:
            return True
    
    # Check admin override
    account = get_account(caller_account_id)
    if account.get('isAdmin') and action == 'admin':
        return True
    
    return False
```

## 7. GraphQL Resolver Pattern

**AppSync Lambda Resolver**:
```python
import json
from typing import Any, Dict

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AppSync Lambda resolver handler.
    
    event['info']['fieldName'] = GraphQL field name
    event['arguments'] = GraphQL arguments
    event['identity'] = Cognito identity
    """
    field_name = event['info']['fieldName']
    arguments = event['arguments']
    caller_account_id = event['identity']['sub']
    
    # Authorization check
    if not check_profile_access(caller_account_id, arguments['profileId'], 'read'):
        raise Exception("Forbidden")
    
    # Business logic
    if field_name == 'getProfile':
        return get_profile(arguments['profileId'])
    elif field_name == 'createOrder':
        return create_order(arguments['profileId'], arguments['seasonId'], arguments)
    # ...
    
    raise Exception(f"Unknown field: {field_name}")
```

## 8. Common Patterns

**DynamoDB Query Pattern** (single-table):
```python
# Get all seasons for a profile
response = table.query(
    KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
    ExpressionAttributeValues={
        ':pk': f'PROFILE#{profile_id}',
        ':sk': 'SEASON#'
    }
)
seasons = response['Items']
```

**S3 Report Generation**:
```python
import openpyxl
from io import BytesIO

def generate_report(profile_id: str, season_id: str) -> str:
    """Generate XLSX report and upload to S3. Returns download URL."""
    # Create workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    
    # Add data...
    
    # Save to BytesIO
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    
    # Upload to S3
    s3_key = f'reports/{profile_id}/{season_id}/report.xlsx'
    s3_client.put_object(Bucket='exports-bucket', Key=s3_key, Body=buffer.getvalue())
    
    # Return pre-signed URL
    return s3_client.generate_presigned_url('get_object', Params={'Bucket': '...', 'Key': s3_key})
```

## 9. Testing Requirements

**Backend (Python)**:
- 100% code coverage (enforced with `--cov-fail-under=100`)
- All tests must pass (zero failures)
- Use `moto` for AWS mocking
- Use `pytest` fixtures for test data

**Frontend (TypeScript/React)**:
- 100% code coverage
- All tests must pass
- Use Vitest for component tests
- Use MSW or Apollo MockedProvider for GraphQL mocking
- Test accessibility (ARIA labels, keyboard nav)

**Integration Tests** (Optional):
- Test against LocalStack Pro (if OSS license approved) or AWS dev account
- Validate end-to-end flows

## 10. Key Files Reference

- `TODO.md`: Current phase and task tracking
- `AGENT.md`: Detailed AI agent rules and quality standards
- `Planning Documents/`: Complete requirements and architecture
  - `graphql_schema_v1.md`: GraphQL API definition
  - `dynamodb_physical_schema_v1.md`: DynamoDB table design
  - `auth_and_sharing_model.md`: Authorization rules
  - `Popcorn Manager.md`: Original requirements
- `GAP_ANALYSIS.md`: Planning completeness assessment

## 11. Safety & Privacy Rules

- **NEVER commit secrets** (API keys, credentials)
- **NEVER delete user data** without explicit confirmation
- **Treat all PII as sensitive** (encrypt at rest and in-flight)
- **Test with test data only** (never production data)
- **Monitor AWS costs** (set budget alerts, use Free Tier)
- **COPPA compliance**: Warn users that only 13+ may create accounts

## 12. Volunteer Context

**Remember**:
- This is a volunteer-run project with limited resources
- Optimize for simplicity and maintainability over perfection
- Document everything for future contributors
- Prefer AWS-managed services over custom solutions
- Cost-consciousness is critical (use serverless/pay-per-use)
- 100% test coverage ensures quality despite limited maintainer time

## 13. Quick Command Reference

**Backend (Python/CDK)**:
```bash
# Install dependencies
uv sync

# Format code
uv run isort src/ tests/ && uv run black src/ tests/

# Type check
uv run mypy src/

# Test with coverage
uv run pytest tests/unit --cov=src --cov-fail-under=100

# Deploy CDK
cdk diff
cdk deploy --profile dev
```

**Frontend (React/TypeScript)**:
```bash
# Install dependencies
npm install

# Dev server
npm run dev

# Format & lint
npm run format && npm run lint

# Type check
npm run typecheck

# Test with coverage
npm run test -- --coverage
```

## 14. When in Doubt

- **Refer to planning documents** in `Planning Documents/`
- **Check AGENT.md** for detailed quality standards
- **Follow TODO.md** for current phase priorities
- **Ask the repo owner** before making large design changes
- **Maintain 100% test coverage** - no exceptions!
````
