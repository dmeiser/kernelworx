# Popcorn Sales Manager - TODO

**Status:** Phase 0 - Infrastructure & Foundation (In Progress)  
**Last Updated:** 2025-11-30

---

## Phase 0: Infrastructure & Foundation

### Step 1: Local Development Environment Setup ✅ COMPLETE
- [x] Install uv for Python package management (`pip install uv` or platform-specific installer) - v0.9.11 ✅
- [x] Install AWS CLI - v2.32.3 ✅
- [x] Install Docker (for optional LocalStack later) - v28.5.1-ce ✅
- [x] Install Node.js/npm (for frontend tooling later) - Node v22.15.1, npm 10.9.2 ✅

### Step 2: AWS Account Setup
- [ ] Create AWS account or select target region (single US region)
- [ ] Configure AWS CLI with credentials locally
- [ ] Set up billing alerts and budget monitoring
- [ ] Configure AWS Budgets with $50-$100/month alert for production
- [ ] Set up AWS Budget alerts ($10-20/month for dev account)
- [ ] Set up CloudTrail for audit logging

### Step 3: Repository & Project Initialization ✅ COMPLETE
- [x] Initialize Git repository locally - main branch ✅
- [x] Create GitHub repository - (defer to manual step)
- [x] Create `.gitignore` for Node, Python, IaC secrets, CDK outputs ✅
- [x] Decide: monorepo structure or separate repos for frontend/backend - monorepo ✅
- [x] Add LICENSE file (MIT) ✅
- [x] Create initial README with project overview ✅
- [x] Add AGENT.md with AI assistant context and guidelines ✅
- [x] Add GitHub Copilot instructions file for code generation consistency ✅
- [ ] Push initial commit to GitHub

### Step 4: Apply for LocalStack Pro OSS License (Can run in parallel with Step 5)
- [ ] Visit https://localstack.cloud/pricing or contact info@localstack.cloud
- [ ] Provide GitHub repo URL, project description, MIT license info
- [ ] Explain use case: local development for volunteer-run Scouting America project
- [ ] Wait 1-2 weeks for response
- [ ] If approved: add "Powered by LocalStack" badge to README
- [ ] If approved: proceed with LocalStack Pro setup (Step 8)
- [ ] If denied: use AWS dev account for integration testing (already planned)

### Step 5: Python Project Setup with uv ✅ COMPLETE
- [x] Navigate to backend/infrastructure directory ✅
- [x] Initialize project with CDK (creates Python structure) ✅
- [x] CDK CLI installed locally (v2.1033.0) ✅
- [x] CDK Python app initialized in cdk/ directory ✅
- [x] Virtual environment created (.venv) ✅
- [x] Requirements files created ✅
- [ ] Configure tool settings in `pyproject.toml` (to be added with uv)
- [ ] Run `uv sync` to install all dependencies
- [ ] Create `uv.lock` file and commit to repository
- [ ] (Optional) Add pre-commit hooks for Black, isort, mypy
- [ ] Document uv usage in README (`uv sync`, `uv run`, `uv add`)

### Step 6: CDK Infrastructure Code - Foundational Resources ✅ IN PROGRESS
- [x] Initialize CDK app structure (`cdk init app --language python`) ✅
- [ ] Create CDK stack for core infrastructure
- [ ] Define DynamoDB table `PsmApp`:
  - [ ] Primary key: PK (string), SK (string)
  - [ ] GSI1: GSI1PK, GSI1SK (shares by target account)
  - [ ] GSI2: GSI2PK, GSI2SK (orders by profile)
  - [ ] GSI3: GSI3PK, GSI3SK (catalog ownership)
  - [ ] Enable Point-in-Time Recovery (PITR)
  - [ ] Use on-demand billing mode
  - [ ] Configure TTL attribute
- [ ] Define S3 buckets:
  - [ ] Static assets bucket (for SPA)
  - [ ] Reports/exports bucket
  - [ ] Enable versioning
  - [ ] Set lifecycle policy for reports (90-day or 1-year expiration)
  - [ ] Configure encryption at rest
- [ ] Define IAM roles and policies:
  - [ ] Lambda execution role
  - [ ] AppSync service role
  - [ ] Principle of least privilege
- [ ] Run `cdk synth` to validate infrastructure code
- [ ] Commit CDK code to repository

### Step 7: CDK Infrastructure Code - Auth & API Layer
- [ ] Define Cognito User Pool:
  - [ ] Configure user attributes (email)
  - [ ] Set up user groups (ADMIN, USER)
  - [ ] Enable social login providers:
    - [ ] Google (required)
    - [ ] Facebook (required)
    - [ ] Apple (required)
  - [ ] Configure password policies
  - [ ] Set up hosted UI (optional for v1)
  - [ ] Configure COPPA compliance warnings
- [ ] Define AppSync GraphQL API:
  - [ ] Set authentication mode: Cognito User Pools
  - [ ] Upload GraphQL schema from planning docs
  - [ ] Configure API-level settings
- [ ] Define CloudFront distribution:
  - [ ] Origin: S3 static assets bucket
  - [ ] Enable HTTPS-only
  - [ ] Configure custom domain (optional for v1)
  - [ ] Set caching policies
  - [ ] Configure default root object (index.html)
- [ ] Define Kinesis Firehose:
  - [ ] Destination: S3 bucket for audit logs
  - [ ] Configure buffering and compression
  - [ ] Set S3 lifecycle policy (~1 year retention)
- [ ] Run `cdk synth` to validate
- [ ] Commit CDK code to repository

### Step 8: (Optional) LocalStack Pro Setup - Only if OSS License Approved
- [ ] Install LocalStack Pro with license key
- [ ] Create `docker-compose.yml` for LocalStack services:
  - [ ] Cognito
  - [ ] AppSync
  - [ ] DynamoDB
  - [ ] Lambda
  - [ ] S3
  - [ ] CloudFront
  - [ ] SNS/SES
  - [ ] EventBridge
  - [ ] Kinesis Firehose
- [ ] Configure CDK for LocalStack endpoints (environment-based switching)
- [ ] Test LocalStack setup: `docker-compose up`
- [ ] Validate services are running
- [ ] Document LocalStack usage in README

### Step 9: Deploy to AWS (Dev Environment)
- [ ] Configure AWS CLI profiles for dev and prod environments
- [ ] Review CDK diff: `cdk diff`
- [ ] Deploy foundational stack to dev: `cdk deploy --profile dev`
- [ ] Verify resources in AWS Console:
  - [ ] DynamoDB table created with GSIs
  - [ ] S3 buckets created
  - [ ] Cognito User Pool created with social providers
  - [ ] AppSync API created
  - [ ] CloudFront distribution created
- [ ] Test basic connectivity and authentication
- [ ] Document manual CDK deployment process in README
- [ ] Create deployment checklist (synth, diff, deploy)

### Step 10: AWS Backup Configuration (Production Only, Can Defer)
- [ ] Configure AWS Backup for weekly backups:
  - [ ] DynamoDB tables (1-year retention)
  - [ ] S3 buckets (1-year retention)
  - [ ] Cross-region replication to secondary US region
- [ ] Test backup and restore process
- [ ] Document backup/restore procedures

### Notes
- **CI/CD pipeline deferred to post-v1** - all deployments are manual for now
- **Testing strategy:** Unit tests use moto mocks; integration tests use LocalStack Pro (if approved) or AWS dev account
- **Cost awareness:** Use AWS Free Tier where applicable; monitor spending closely

---

## Phase 1: Backend - Core API & Data Layer

### DynamoDB Schema Implementation
- [ ] Create table with physical schema from `dynamodb_physical_schema_v1.md`
- [ ] Implement GSI1 (Profiles Shared With Me)
- [ ] Implement GSI2 (Orders by Profile)
- [ ] Implement GSI3 (Catalog Ownership)
- [ ] Add TTL configuration for ProfileInvite and CatalogShareInvite items
- [ ] Test key access patterns with sample data

### AppSync GraphQL API
- [ ] Deploy AppSync API with Cognito User Pools auth
- [ ] Implement complete schema from `graphql_schema_v1.md`
- [ ] Create direct DynamoDB resolvers for:
  - [ ] `me` query
  - [ ] `listProfiles`, `getProfile`
  - [ ] `listSeasons`, `getSeason`
  - [ ] `listOrders`, `getOrder`
  - [ ] `listCatalogs`, `getCatalog`
  - [ ] Simple CRUD mutations (createProfile, updateProfile, createSeason, etc.)
- [ ] Implement authorization checks in VTL or Lambda resolvers
  - [ ] Owner-based access (ownerAccountId)
  - [ ] Share-based access (READ/WRITE permissions)
  - [ ] Admin override with logging

### Lambda Functions (Python)
- [ ] Set up Lambda layer for shared dependencies (boto3, openpyxl, etc.)
- [ ] Create shared utilities module:
  - [ ] JSON logging helper with correlation IDs
  - [ ] Error handling utilities (errorCode + message pattern)
  - [ ] Authorization helper functions (owner/share checks)
- [ ] Implement Lambda resolvers:
  - [ ] Profile sharing (`createProfileInvite`, `redeemProfileInvite`, `shareProfileDirect`, `revokeShare`)
  - [ ] Catalog sharing (`createCatalogShareInvite`, `redeemCatalogShareInvite`)
  - [ ] Catalog corrections (`createCatalogCorrection`, `acceptCatalogCorrection`, `rejectCatalogCorrection`)
  - [ ] Report generation (`requestSeasonReport` - CSV/XLSX export)
- [ ] Define customer input validation rules:
  - [ ] Name (required)
  - [ ] Phone and/or Address (at least one required, both allowed)
  - [ ] Phone format validation (US: 10 digits with optional formatting)
  - [ ] Address validation (all fields required if address provided)
- [ ] Define report CSV/XLSX layout using `Popcorn 2025 - anonymized.xlsx` as reference format
- [ ] Set default invite expiration: 14 days for both profile and catalog invites (single-use)
- [ ] Add `lastActivityAt` to Season schema
- [ ] Implement background job (EventBridge + Lambda) to mark seasons READ_ONLY after 90 days of inactivity

### Lambda Testing & Quality
- [ ] **Target: 100% unit test coverage for all Lambda functions**
- [ ] Write comprehensive unit tests with pytest:
  - [ ] All Lambda resolvers (profile sharing, catalog sharing, corrections, reports)
  - [ ] All utility functions (logging, error handling, authorization)
  - [ ] All validation logic (customer input, invite expiration, etc.)
  - [ ] Mock AWS services using moto (DynamoDB, S3, SNS/SES, EventBridge)
  - [ ] Use pytest fixtures for common test data and AWS resource mocking
  - [ ] Test all authorization paths (owner, shared READ/WRITE, admin)
  - [ ] Test all error handling and edge cases
  - [ ] Test happy paths and failure scenarios
- [ ] Configure pytest-cov for coverage reporting
- [ ] Set up coverage requirements in pytest configuration (100% threshold)
- [ ] Run mypy for type checking on all Lambda code (strict mode)
- [ ] Run Black for code formatting
- [ ] Run isort for import sorting
- [ ] Create comprehensive test fixtures for:
  - [ ] Mock DynamoDB tables with test data
  - [ ] Mock S3 buckets and objects
  - [ ] Sample accounts, profiles, seasons, orders
  - [ ] Auth contexts (owner, contributor, admin)
- [ ] Add coverage reports to CI/CD (when implemented)
- [ ] Note: Unit tests use moto; integration tests use LocalStack Pro (if approved) or AWS dev account

### Audit & Logging
- [ ] Set up Kinesis Firehose → S3 pipeline for application events
- [ ] Implement event emission for:
  - [ ] Profile ownership transfers
  - [ ] Participant additions/removals
  - [ ] Catalog corrections acceptance/rejection
  - [ ] Order deletions/restores
  - [ ] Admin actions
- [ ] Configure CloudWatch log groups with retention policies
- [ ] Set up S3 lifecycle policies for audit logs (~1 year retention)

### Notifications
- [ ] Configure Amazon SES or SNS for email notifications
- [ ] Implement email templates for:
  - [ ] Profile invite created
  - [ ] Profile invite accepted
  - [ ] Catalog correction notification
- [ ] Test email delivery in sandbox and production modes

---

## Phase 2: Frontend - React SPA

### Project Setup
- [ ] Initialize Vite + React + TypeScript project
- [ ] Install dependencies:
  - [ ] MUI (Material UI) for components
  - [ ] Apollo Client for GraphQL
  - [ ] react-router for routing
  - [ ] AWS Amplify libraries for Cognito auth (or custom)
- [ ] Configure build and dev server
- [ ] Set up environment variables for API endpoints

### Authentication & Auth Context
- [ ] Implement Cognito Hosted UI integration
- [ ] Create AuthProvider context with:
  - [ ] Login/logout flows
  - [ ] Token refresh logic
  - [ ] Current Account state
  - [ ] isAdmin flag
- [ ] Implement protected route wrapper
- [ ] Add COPPA warning on signup/registration page

### Apollo Client Setup
- [ ] Configure Apollo Client with AppSync endpoint
- [ ] Add Cognito JWT to Authorization header
- [ ] Implement global error handling for GraphQL errors
- [ ] Map errorCode to user-facing messages/toasts

### Core Layout & Navigation
- [ ] Create AppLayout component with:
  - [ ] Header (branding, user info, logout)
  - [ ] NavBar (profile selector, navigation)
  - [ ] MainContent (route outlet)
  - [ ] ToastContainer for notifications
- [ ] Implement responsive design (mobile-first)
- [ ] Add accessibility features (WCAG 2.1 AAA aspirational)

### Pages & Components
- [ ] **LoginPage** - Cognito Hosted UI redirect
- [ ] **ProfilesPage** - List owned + shared profiles
  - [ ] ProfileList component
  - [ ] ProfileCard component
  - [ ] Create new profile dialog
- [ ] **ProfileSeasonsPage** - List seasons for a profile
  - [ ] SeasonList component
  - [ ] SeasonCard component
  - [ ] Create new season dialog
- [ ] **SeasonLayout** - Tabbed layout for season views
  - [ ] OrdersPage - List and manage orders
    - [ ] OrderList component
    - [ ] OrderRow component
    - [ ] OrderEditorDialog (add/edit orders)
    - [ ] Payment method selector
    - [ ] Customer picker (saved customers)
  - [ ] SeasonSummaryPage - High-level summary and totals
  - [ ] ReportsPage - Generate and download reports
    - [ ] ReportsPanel component
    - [ ] ExportReportButton (CSV/XLSX)
  - [ ] SeasonSettingsPage - Season metadata, sharing
    - [ ] SharingSettings component
    - [ ] Invite code generation
    - [ ] Revoke share functionality
- [ ] **SettingsPage** - User account settings
- [ ] **AdminPage** - Admin console (visible only when isAdmin)
  - [ ] User & profile management
  - [ ] Orders & deletion management (restore soft-deleted, hard delete)
  - [ ] Admin catalog management (CRUD catalogs and items)

### Soft Delete & Order Management
- [ ] Implement soft delete for orders (isDeleted flag)
- [ ] Create "Deleted Orders" view for contributors
- [ ] Add restore functionality for contributors
- [ ] Prevent hard delete from contributor UI

### Catalog Management
- [ ] List admin-managed catalogs (read-only for users)
- [ ] Create/edit user-owned catalogs
- [ ] Catalog item management (add, edit, deactivate)
- [ ] Catalog share invite code generation
- [ ] Catalog correction acceptance/rejection UI

### Reports & Exports
- [ ] Display report generation status (PENDING, COMPLETED, FAILED)
- [ ] Download link for completed reports
- [ ] Error messaging for failed reports
- [ ] In-app table preview for reports (optional)

### Testing
- [ ] **Target: 100% unit test coverage for React components**
- [ ] Set up Vitest (recommended for Vite projects, faster than Jest)
- [ ] Add comprehensive component tests:
  - [ ] All pages (LoginPage, ProfilesPage, ProfileSeasonsPage, etc.)
  - [ ] All form components (OrderEditorDialog, profile/season creation dialogs)
  - [ ] All list components (ProfileList, SeasonList, OrderList)
  - [ ] AuthProvider and authentication flows
  - [ ] Apollo Client error handling
  - [ ] Authorization-based UI rendering (owner vs shared permissions)
  - [ ] Toast notifications and error states
- [ ] Configure Vitest coverage reporting (100% threshold)
- [ ] Mock GraphQL queries and mutations with MSW or Apollo MockedProvider
- [ ] Test accessibility features (keyboard navigation, ARIA labels)
- [ ] Configure ESLint and Prettier for frontend code
- [ ] Add coverage reports to verify 100% threshold
- [ ] **Playwright E2E Testing (if time allows after 100% unit coverage)**:
  - [ ] Set up Playwright
  - [ ] Critical user flows (account creation, order placement, report download)
  - [ ] Admin flows (ownership transfer, hard delete)
  - [ ] Cross-browser testing (Chromium, Firefox, WebKit)

---

## Phase 3: Integration & Hardening

### End-to-End Testing
- [ ] Set up testing environment (LocalStack Pro if approved, otherwise AWS dev account)
- [ ] Test full user flows in test environment:
  - [ ] Account creation and login (Cognito + social providers)
  - [ ] Profile creation and sharing
  - [ ] Season creation and catalog selection
  - [ ] Order creation, editing, deletion
  - [ ] Report generation and download
  - [ ] Catalog corrections workflow
- [ ] Test admin flows in test environment:
  - [ ] User lookup
  - [ ] Profile ownership transfer
  - [ ] Order restore and hard delete
  - [ ] Admin catalog management
- [ ] Document test accounts and data setup for test environment
- [ ] Create smoke test script for critical paths

### Security Hardening
- [ ] Enable HTTPS-only for CloudFront and AppSync
- [ ] Enable AWS-managed encryption for DynamoDB and S3
- [ ] Review IAM roles and apply least-privilege principles
- [ ] Enable MFA delete for S3 buckets (if applicable)
- [ ] Test authorization rules for edge cases

### Performance Optimization
- [ ] Enable CloudFront caching for static assets
- [ ] Optimize DynamoDB provisioned capacity or use on-demand
- [ ] Add indexes for slow queries (if discovered)
- [ ] Optimize Lambda cold start times (consider Provisioned Concurrency if needed)
- [ ] Compress and minify frontend assets

### Observability & Monitoring
- [ ] Create CloudWatch dashboards for:
  - [ ] API request/error rates
  - [ ] Lambda invocation/error rates
  - [ ] DynamoDB read/write capacity
- [ ] Set up alarms for elevated error rates
- [ ] Test log correlation with requestId/correlationId

### Documentation
- [ ] Update README with deployment instructions
- [ ] Create user guide or help documentation
- [ ] Document admin procedures (ownership transfer, hard delete, etc.)
- [ ] Create runbook for common operational tasks

---

## Phase 4: Launch Preparation

### Data & Privacy
- [ ] Implement profile/season/account cascade deletion (30-day soft delete)
- [ ] Test COPPA warning display
- [ ] Document customer privacy handling (seller-managed)
- [ ] Prepare data retention and deletion policies

### Accessibility
- [ ] Run automated accessibility tests (axe, Lighthouse)
- [ ] Test with screen readers (ad hoc)
- [ ] Validate keyboard navigation
- [ ] Ensure high color contrast

### Legal & Licensing
- [ ] Add MIT license to repository (already added in Phase 0)
- [ ] Create terms of service (optional, volunteer context)
- [ ] Add privacy policy (minimal, acknowledge PII handling)
- [ ] Reference AGENT.md and Copilot instructions for contributor AI assistant usage

### Tip Jar / Sponsorship
- [ ] Select third-party tipping platform (Ko-fi, Buy Me a Coffee, GitHub Sponsors, etc.)
- [ ] Add link to app (on login or settings page)
- [ ] Create sponsorship tiers (optional)

### Beta Testing
- [ ] Recruit beta testers from local units
- [ ] Collect feedback on usability and bugs
- [ ] Iterate on UX based on feedback

---

## Phase 5: Post-Launch

### Operational Tasks
- [ ] Monitor CloudWatch logs and alarms
- [ ] Respond to user support requests
- [ ] Perform weekly backup verification
- [ ] Review AWS costs and optimize where possible

### Incremental Enhancements (Future Scope)
- [ ] Add unit-level reporting and Unit Kernel role
- [ ] Implement structured council/district/unit directory (if data source available)
- [ ] Add client-side CSV/XLSX export (browser-based)
- [ ] Add PDF report generation
- [ ] Implement automated reminders (undelivered orders, season ending soon)
- [ ] Add SMS notifications (if budget allows)
- [ ] Explore multi-region active failover (if donations support it)
- [ ] Add analytics and aggregated reporting across profiles (global reporting)
- [ ] Implement PWA-style offline mode with queuing

---

## Notes

- **Volunteer Context:** This is a volunteer-run project with limited resources. Prioritize MVP features and simplicity.
- **Cost Awareness:** Use AWS Free Tier where possible; monitor costs closely.
- **Community Contributions:** Accept pull requests and community feedback once open source.
- **Iteration Over Perfection:** Ship a functional v1 and iterate based on real-world usage.

---

## Gap Analysis Summary

See `GAP_ANALYSIS.md` for a detailed comparison of planning documents vs. this TODO.
