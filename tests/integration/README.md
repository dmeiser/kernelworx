# Integration Tests for AppSync Resolvers

## Overview

Integration tests validate AppSync resolvers by making real GraphQL requests against the deployed dev environment. These tests cover the 10 AppSync resolvers that replaced Lambda functions.

## Setup

### Prerequisites

1. **Deploy to dev environment:**
   ```bash
   cd cdk
   cdk deploy --profile dev
   ```

2. **Install dependencies:**
   ```bash
   npm install --save-dev @apollo/client graphql aws-amplify
   ```

3. **Create test Cognito users:**
   ```bash
   # Owner account
   aws cognito-idp admin-create-user \
     --user-pool-id <USER_POOL_ID> \
     --username integration-test-owner@example.com \
     --temporary-password 'TempPass123!' \
     --message-action SUPPRESS
   
   # Contributor account
   aws cognito-idp admin-create-user \
     --user-pool-id <USER_POOL_ID> \
     --username integration-test-contributor@example.com \
     --temporary-password 'TempPass123!' \
     --message-action SUPPRESS
   ```

4. **Set environment variables:**
   ```bash
   export APPSYNC_ENDPOINT="https://your-api-id.appsync-api.us-east-1.amazonaws.com/graphql"
   export USER_POOL_ID="us-east-1_xxxxxxxxx"
   export USER_POOL_CLIENT_ID="xxxxxxxxxxxxxxxxxxxxxxxxxx"
   export TEST_OWNER_EMAIL="integration-test-owner@example.com"
   export TEST_OWNER_PASSWORD="PermPass123!"
   export TEST_CONTRIBUTOR_EMAIL="integration-test-contributor@example.com"
   export TEST_CONTRIBUTOR_PASSWORD="PermPass123!"
   ```

## Running Tests

```bash
# Run all integration tests (from root directory)
npx vitest run tests/integration/

# Run specific test file
npx vitest run tests/integration/resolvers/catalogCrud.integration.test.ts

# Watch mode
npx vitest tests/integration/
```

**Note**: Environment variables are loaded from `.env` in the project root via the setup file.

## Test Structure

```
tests/integration/
├── README.md                           # This file
├── setup/
│   ├── apolloClient.ts                 # Apollo Client factory
│   ├── cognitoAuth.ts                  # Cognito authentication
│   └── testData.ts                     # Test data cleanup utilities
├── resolvers/
│   ├── profileSharing.integration.test.ts    # Share/invite/revoke tests
│   ├── orderOperations.integration.test.ts   # Create/update/delete order
│   ├── campaignOperations.integration.test.ts  # Update/delete campaigngn
│   └── queries.integration.test.ts           # List queries (VTL resolvers)
└── workflows/
    └── completeWorkflow.integration.test.ts  # End-to-end scenarios
```

## Writing Tests

### Basic Pattern

```typescript
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { createAuthenticatedClient } from '../setup/apolloClient';
import { cleanupTestData } from '../setup/testData';

describe('ShareProfileDirect Pipeline Resolver', () => {
  let ownerClient: ApolloClient;
  let contributorClient: ApolloClient;
  let testProfileId: string;
  
  beforeEach(async () => {
    ownerClient = await createAuthenticatedClient('owner');
    contributorClient = await createAuthenticatedClient('contributor');
    
    // Create test profile
    const { data } = await ownerClient.mutate({
      mutation: CREATE_PROFILE,
      variables: { name: 'Integration Test Profile' }
    });
    testProfileId = data.createProfile.profileId;
  });
  
  afterEach(async () => {
    await cleanupTestData(testProfileId);
  });
  
  it('shares profile with contributor by email', async () => {
    const { data } = await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        profileId: testProfileId,
        targetEmail: process.env.TEST_CONTRIBUTOR_EMAIL,
        permissions: ['READ']
      }
    });
    
    expect(data.shareProfileDirect.share).toBeDefined();
    expect(data.shareProfileDirect.share.permissions).toContain('READ');
  });
});
```

## Test Data Cleanup

All tests MUST clean up after themselves to prevent pollution:

1. **Track created resources** in test context
2. **Delete in reverse order** of creation (shares → orders → campaigngns → profiles)
3. **Use try/finally** to ensure cleanup even on test failure

## CI/CD Integration

Integration tests run in GitHub Actions against the dev environment:

```yaml
- name: Run integration tests
  env:
    APPSYNC_ENDPOINT: ${{ secrets.DEV_APPSYNC_ENDPOINT }}
    USER_POOL_ID: ${{ secrets.DEV_USER_POOL_ID }}
    USER_POOL_CLIENT_ID: ${{ secrets.DEV_USER_POOL_CLIENT_ID }}
    TEST_OWNER_EMAIL: ${{ secrets.TEST_OWNER_EMAIL }}
    TEST_OWNER_PASSWORD: ${{ secrets.TEST_OWNER_PASSWORD }}
  run: npm run test:integration
```

## Troubleshooting

### Authentication Errors
- Verify user pool credentials are correct
- Check if test users need password reset
- Ensure client ID has proper auth flows enabled

### GraphQL Errors
- Check AppSync logs in CloudWatch
- Verify resolver configurations in CDK
- Test query manually in AppSync console

### Data Cleanup Issues
- Run cleanup script manually: `npm run test:cleanup`
- Check DynamoDB for orphaned test data
- Verify test data uses `TEST#` prefix

## Coverage Goals

- **Pipeline Resolvers**: 90%+ (all paths including errors)
- **VTL Resolvers**: 80%+ (happy path + common errors)
- **JavaScript Resolvers**: 85%+ (logic branches)

## Next Steps

1. Implement basic setup utilities (Apollo client, Cognito auth)
2. Write tests for high-risk resolvers (createOrder, shareProfileDirect, redeemProfileInvite)
3. Add error case coverage
4. Set up CI/CD integration
5. Expand to full workflow tests
