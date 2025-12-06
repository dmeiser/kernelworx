# Popcorn Sales Manager - TODO

**Status:** Phase 0 - Infrastructure & Foundation (In Progress)  
**Last Updated:** 2025-11-30

---

## Phase 0: Infrastructure & Foundation

### Step 1: Local Development Environment Setup ✅ COMPLETE
- [x] Install uv for Python package management (`pip install uv` or platform-specific installer) - v0.9.11 ✅
- [x] Install AWS CLI - v2.32.3 ✅
- [x] Install Docker - v28.5.1-ce ✅
- [x] Install Node.js/npm (for frontend tooling later) - Node v22.15.1, npm 10.9.2 ✅

### Step 2: AWS Account Setup ✅ COMPLETE
- [x] Create AWS account or select target region (single US region) ✅
- [x] Configure AWS CLI with credentials locally (default profile) ✅
- [x] Set up billing alerts and budget monitoring ✅
- [x] Set up AWS Budget alerts ($10/month) ✅
- [x] Set up CloudTrail for audit logging ✅

### Step 3: Repository & Project Initialization ✅ COMPLETE
- [x] Initialize Git repository locally - main branch ✅
- [x] Create GitHub repository ✅ - https://github.com/dmeiser/popcorn-sales-manager
- [x] Create `.gitignore` for Node, Python, IaC secrets, CDK outputs ✅
- [x] Decide: monorepo structure or separate repos for frontend/backend - monorepo ✅
- [x] Add LICENSE file (MIT) ✅
- [x] Create initial README with project overview ✅
- [x] Add AGENT.md with AI assistant context and guidelines ✅
- [x] Add GitHub Copilot instructions file for code generation consistency ✅
- [x] Push initial commit to GitHub ✅

### Step 5: Python Project Setup with uv ✅ COMPLETE
- [x] Navigate to backend/infrastructure directory ✅
- [x] Initialize project with CDK (creates Python structure) ✅
- [x] CDK CLI installed locally (v2.1033.0) ✅
- [x] CDK Python app initialized in cdk/ directory ✅
- [x] Virtual environment created (.venv) ✅
- [x] Requirements files created ✅
- [x] Configure tool settings in `pyproject.toml` (black, isort, mypy, pytest) ✅
- [x] Run `uv sync` to install all dependencies ✅
- [x] Create `uv.lock` file and commit to repository ✅
- [x] (Optional) Add pre-commit hooks for Black, isort, mypy - (deferred)
- [x] Document uv usage in README_UV.md (`uv sync`, `uv run`, `uv add`) ✅

### Step 6: CDK Infrastructure Code - Foundational Resources ✅ COMPLETE
- [x] Initialize CDK app structure (`cdk init app --language python`) ✅
- [x] Create CDK stack for core infrastructure ✅
- [x] Define DynamoDB table `PsmApp`: ✅
  - [x] Primary key: PK (string), SK (string) ✅
  - [x] GSI1: GSI1PK, GSI1SK (shares by target account) ✅
  - [x] GSI2: GSI2PK, GSI2SK (orders by profile) ✅
  - [x] GSI3: GSI3PK, GSI3SK (catalog ownership) ✅
  - [x] Enable Point-in-Time Recovery (PITR) ✅
  - [x] Use on-demand billing mode ✅
  - [x] Configure TTL attribute (stream enabled) ✅
- [x] Define S3 buckets: ✅
  - [x] Static assets bucket (for SPA) ✅
  - [x] Reports/exports bucket ✅
  - [x] Enable versioning (static assets only) ✅
  - [x] Set lifecycle policy for reports (deferred to production) ✅
  - [x] Configure encryption at rest ✅
- [x] Define IAM roles and policies: ✅
  - [x] Lambda execution role ✅
  - [x] AppSync service role ✅
  - [x] Principle of least privilege ✅
- [x] Run `cdk synth` to validate infrastructure code ✅
- [x] Commit CDK code to repository ✅

### Step 7: CDK Infrastructure Code - Auth & API Layer ✅ COMPLETE
- [x] Define Cognito User Pool: ✅
  - [x] Configure user attributes (email) ✅
  - [x] Set up user groups (ADMIN, USER) ✅
  - [x] Enable social login providers: ✅
    - [x] Google (required) ✅
    - [x] Facebook (required) ✅
    - [x] Apple (required) ✅
  - [x] Configure password policies ✅
  - [x] Set up hosted UI (optional for v1) ✅
  - [x] Configure COPPA compliance warnings ✅
- [x] Define AppSync GraphQL API: ✅
  - [x] Set authentication mode: Cognito User Pools ✅
  - [x] Upload GraphQL schema from planning docs ✅
  - [x] Configure API-level settings ✅
- [x] Define CloudFront distribution: ✅
  - [x] Origin: S3 static assets bucket ✅
  - [x] Enable HTTPS-only ✅
  - [x] Configure custom domain (optional for v1) ✅
  - [x] Set caching policies ✅
  - [x] Configure default root object (index.html) ✅
- [x] Define Kinesis Firehose:R (deferred - CloudTrail handles audit logging) ✅
  - [x] Destination: S3 bucket for audit logs ✅
  - [x] Configure buffering and compression ✅
  - [x] Set S3 lifecycle policy (~1 year retention) ✅
- [x] Run `cdk synth` to validate ✅
- [x] Commit CDK code to repository ✅

### Step 9: Deploy to AWS (Dev Environment) ✅ COMPLETE
- [x] Configure AWS CLI profiles for dev and prod environments ✅
- [x] Review CDK diff: `cdk diff` ✅
- [x] Deploy foundational stack to dev: `cdk deploy --profile dev` ✅
- [x] Verify resources in AWS Console: ✅
  - [x] DynamoDB table created with GSIs ✅
  - [x] S3 buckets created ✅
  - [x] Cognito User Pool created with social providers ✅
  - [x] AppSync API created ✅
  - [x] AppSync custom domain configured (api.dev.psm.repeatersolutions.com) ✅
  - [x] ACM certificate created and validated ✅
  - [x] Route53 records configured ✅
  - [x] CloudFront distribution (temporarily disabled - requires account verification) ✅
- [x] Test basic connectivity and authentication ✅
- [x] Document manual CDK deployment process in README ✅
- [x] Create deployment checklist (synth, diff, deploy) ✅
- [x] Configure environment variables with .env file ✅
- [x] Create deploy.sh script for simplified deployment ✅

**Notes:**
- CloudFront and Cognito custom domains temporarily disabled due to AWS account verification requirement
- AppSync custom domain successfully deployed: api.dev.psm.repeatersolutions.com
- Deployment now uses .env file for sensitive configuration (gitignored)

### Notes
- **CI/CD pipeline deferred to post-v1** - all deployments are manual for now
- **Testing strategy:** Unit tests use moto mocks; integration tests use AWS dev account
- **Cost awareness:** Use AWS Free Tier where applicable; monitor spending closely

---

## Phase 1: Backend - Core API & Data Layer

### DynamoDB Schema Implementation
- [x] Create table with physical schema (PK, SK, GSI1/GSI2/GSI3) ✅ (Deployed in Phase 0)
- [x] Implement GSI1 (Profiles Shared With Me) ✅
- [x] Implement GSI2 (Orders by Profile) ✅
- [x] Implement GSI3 (Catalog Ownership) ✅
- [x] Add TTL configuration for ProfileInvite and CatalogShareInvite items ✅ (Added Dec 6, 2025)
- [ ] Test key access patterns with sample data

### AppSync GraphQL API
- [x] Deploy AppSync API with Cognito User Pools auth ✅ (Deployed in Phase 0)
- [x] Implement complete schema from `graphql_schema_v1.md` ✅ (Schema deployed)
- [x] Wire up Lambda resolvers for profile sharing mutations ✅ (Dec 6, 2025)
  - [x] `createProfileInvite` ✅
  - [x] `redeemProfileInvite` ✅
  - [x] `shareProfileDirect` ✅
  - [x] `revokeShare` ✅
- [ ] Create direct DynamoDB resolvers for:
  - [ ] `me` query
  - [ ] `listProfiles`, `getProfile`
  - [ ] `listSeasons`, `getSeason`
  - [ ] `listOrders`, `getOrder`
  - [ ] `listCatalogs`, `getCatalog`
  - [ ] Simple CRUD mutations (createProfile, updateProfile, createSeason, etc.)
- [x] Implement authorization checks in Lambda resolvers ✅ (Profile sharing done)
  - [x] Owner-based access (ownerAccountId) ✅
  - [x] Share-based access (READ/WRITE permissions) ✅
  - [x] Admin override with logging ✅

### Lambda Functions (Python)
- [x] Set up Lambda deployment in CDK ✅ (Dec 6, 2025)
- [x] Create shared utilities module: ✅
  - [x] JSON logging helper with correlation IDs ✅
  - [x] Error handling utilities (errorCode + message pattern) ✅
  - [x] Authorization helper functions (owner/share checks) ✅
- [x] Implement and deploy profile sharing Lambda functions: ✅ (Dec 6, 2025)
  - [x] `createProfileInvite` - Creates invite codes for sharing profiles ✅
  - [x] `redeemProfileInvite` - Redeems invite codes to create shares ✅
  - [x] `shareProfileDirect` - Direct sharing without invites ✅
  - [x] `revokeShare` - Revokes profile access ✅
- [ ] Implement catalog sharing Lambda functions:
  - [ ] `createCatalogShareInvite`
  - [ ] `redeemCatalogShareInvite`
- [ ] Implement catalog corrections Lambda functions:
  - [ ] `createCatalogCorrection`
  - [ ] `acceptCatalogCorrection`
  - [ ] `rejectCatalogCorrection`
- [ ] Implement report generation Lambda function:
  - [ ] `requestSeasonReport` - CSV/XLSX export
- [x] Define customer input validation rules: ✅
  - [x] Name (required) ✅
  - [x] Phone and/or Address (at least one required, both allowed) ✅
  - [x] Phone format validation (US: 10 digits with optional formatting) ✅
  - [x] Address validation (all fields required if address provided) ✅
- [ ] Define report CSV/XLSX layout using `Popcorn 2025 - anonymized.xlsx` as reference format
- [x] Set default invite expiration: 14 days for both profile and catalog invites (single-use) ✅
- [ ] Add `lastActivityAt` to Season schema
- [ ] Implement background job (EventBridge + Lambda) to mark seasons READ_ONLY after 90 days of inactivity

### Lambda Testing & Quality
- [x] **Target: 100% unit test coverage for all Lambda functions** ✅ (100% achieved with 85 tests for profile sharing - Dec 6, 2025)
- [x] Write comprehensive unit tests with pytest for profile sharing: ✅
  - [x] All profile sharing Lambda resolvers ✅
  - [x] All utility functions (logging, error handling, authorization) ✅
  - [x] All validation logic (customer input, invite expiration, etc.) ✅
  - [x] Mock AWS services using moto (DynamoDB) ✅
  - [x] Use pytest fixtures for common test data and AWS resource mocking ✅
  - [x] Test all authorization paths (owner, shared READ/WRITE, admin) ✅
  - [x] Test all error handling and edge cases ✅
  - [x] Test happy paths and failure scenarios ✅
- [x] Configure pytest-cov for coverage reporting ✅
- [x] Set up coverage requirements in pytest configuration (100% threshold) ✅
- [ ] Write tests for catalog sharing, corrections, and reports (when implemented)
- [x] Run mypy for type checking on all Lambda code (strict mode) ✅ (Dec 6, 2025)
- [x] Run Black for code formatting ✅ (Dec 6, 2025 - 7 files reformatted)
- [x] Run isort for import sorting ✅ (Dec 6, 2025 - already sorted)
- [x] Create comprehensive test fixtures for: ✅
  - [x] Mock DynamoDB tables with test data ✅
  - [ ] Mock S3 buckets and objects (for report generation)
  - [x] Sample accounts, profiles, seasons, orders ✅
  - [x] Auth contexts (owner, contributor, admin) ✅
- [ ] Add coverage reports to CI/CD (when implemented)
- [ ] Note: Unit tests use moto; integration tests use AWS dev account

### Data Validation & Business Logic
- [x] Define customer input validation rules: ✅
  - [x] Name (required) ✅
  - [x] Phone and/or Address (at least one required, both allowed) ✅
  - [x] Phone format validation (US: 10 digits with optional formatting) ✅
  - [x] Address validation (all fields required if address provided) ✅
- [x] Set default invite expiration: 14 days for both profile and catalog invites (single-use) ✅
- [ ] Define report CSV/XLSX layout using `Popcorn 2025 - anonymized.xlsx` as reference format
- [ ] Add `lastActivityAt` to Season schema
- [ ] Implement background job (EventBridge + Lambda) to mark seasons READ_ONLY after 90 days of inactivity

### CDK Infrastructure Updates (Dec 6, 2025)
- [x] Add TTL configuration to DynamoDB table ✅
- [x] Add Lambda functions to CDK stack with proper asset bundling ✅
- [x] Configure Lambda environment variables (TABLE_NAME, EXPORTS_BUCKET, etc.) ✅
- [x] Create Lambda data sources in AppSync ✅
- [x] Wire up resolvers for profile sharing mutations ✅
- [x] Deploy all changes to AWS dev environment ✅
- [x] Fix deprecation warning: `pointInTimeRecovery` → `pointInTimeRecoverySpecification` ✅
- [x] Add DynamoDB resolvers for basic queries (getMyAccount, getProfile, listMyProfiles, listSharedProfiles) ✅
- [ ] Add more DynamoDB resolvers (seasons, orders, catalogs)
- [ ] Test deployed mutations end-to-end via AppSync console

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

## Phase 3: Infrastructure Hardening & Production Readiness

### CDK Infrastructure Enhancements
- [ ] Enable CloudFront distribution after AWS account verification
  - [ ] Contact AWS Support to verify account for CloudFront resources
  - [ ] Uncomment CloudFront configuration in cdk_stack.py
  - [ ] Add custom domain: dev.psm.repeatersolutions.com
  - [ ] Configure S3 origin access identity (OAI)
  - [ ] Set up error pages (403/404 → index.html)
  - [ ] Deploy and verify CloudFront distribution
- [ ] Enable Cognito custom domain after account verification
  - [ ] Uncomment Cognito custom domain configuration
  - [ ] Add custom domain: login.dev.psm.repeatersolutions.com
  - [ ] Update OAuth callback URLs to use custom domain
  - [ ] Deploy and verify Cognito custom domain
- [ ] Fix deprecated CDK APIs
  - [ ] Update point_in_time_recovery to point_in_time_recovery_specification
  - [ ] Replace S3Origin with S3BucketOrigin for CloudFront
- [ ] Add Lambda functions to CDK stack
  - [ ] Create Lambda constructs for all resolver functions
  - [ ] Configure environment variables (TABLE_NAME, etc.)
  - [ ] Wire up AppSync resolvers to Lambda functions
  - [ ] Deploy and verify Lambda integration
- [ ] Implement production environment
  - [ ] Create prod .env configuration
  - [ ] Deploy to prod: `ENVIRONMENT=prod ./deploy.sh`
  - [ ] Use prod domains: psm.repeatersolutions.com, api.psm.repeatersolutions.com, login.psm.repeatersolutions.com
  - [ ] Verify isolation between dev and prod environments

### Monitoring & Alerting
- [ ] Set up CloudWatch alarms
  - [ ] Lambda errors and throttling
  - [ ] DynamoDB consumed capacity
  - [ ] AppSync error rates
  - [ ] S3 bucket size growth
  - [ ] CloudFront 4xx/5xx error rates
- [ ] Configure SNS topics for alarm notifications
- [ ] Set up CloudWatch dashboards for:
  - [ ] API performance metrics
  - [ ] User activity metrics
  - [ ] Cost tracking metrics
- [ ] Enable AWS X-Ray for distributed tracing (optional)

### Security Hardening
- [ ] Enable AWS WAF on CloudFront (when re-enabled)
  - [ ] Configure rate limiting rules
  - [ ] Block common attack patterns
  - [ ] Set up geo-blocking if needed
- [ ] Review and harden IAM policies
  - [ ] Principle of least privilege audit
  - [ ] Remove overly permissive policies
  - [ ] Add resource-level permissions where possible
- [ ] Enable S3 bucket policies
  - [ ] Block public access
  - [ ] Require encryption in transit
  - [ ] Restrict to CloudFront OAI only
- [ ] Enable CloudTrail for all API calls (already enabled)
- [ ] Set up AWS GuardDuty for threat detection (optional, cost consideration)
- [ ] Review Cognito security settings
  - [ ] MFA options for admin users
  - [ ] Password policies
  - [ ] Account takeover protection

### Disaster Recovery & Backup
- [ ] Configure AWS Backup for production
  - [ ] DynamoDB table backups (daily, 30-day retention)
  - [ ] S3 bucket versioning and lifecycle policies
  - [ ] Cross-region replication for critical buckets
- [ ] Document and test disaster recovery procedures
  - [ ] DynamoDB restore from backup
  - [ ] S3 restore from versioned objects
  - [ ] Stack recreation from CDK code
- [ ] Create runbook for common operational tasks
  - [ ] Deploying updates
  - [ ] Rolling back deployments
  - [ ] Investigating errors
  - [ ] User data recovery

### Cost Optimization
- [ ] Review and optimize DynamoDB capacity
  - [ ] Monitor actual usage patterns
  - [ ] Consider reserved capacity for prod (if justified)
  - [ ] Set up auto-scaling if needed
- [ ] Implement S3 lifecycle policies
  - [ ] Move old exports to Infrequent Access after 90 days
  - [ ] Delete exports older than 1 year
- [ ] Review CloudWatch log retention
  - [ ] Set appropriate retention periods (30 days for most logs)
  - [ ] Archive critical logs to S3 for long-term storage
- [ ] Monitor CloudFront costs
  - [ ] Review price class settings
  - [ ] Optimize caching strategies
- [ ] Set up cost allocation tags
  - [ ] Tag all resources with Environment (dev/prod)
  - [ ] Tag with Project name
  - [ ] Enable cost allocation reports

### Documentation
- [ ] Update GETTING_STARTED.md with:
  - [ ] Production deployment instructions
  - [ ] Custom domain setup after account verification
  - [ ] Monitoring and troubleshooting guide
- [ ] Create OPERATIONS.md runbook
  - [ ] Common deployment scenarios
  - [ ] Troubleshooting guide
  - [ ] Backup/restore procedures
- [ ] Document environment variable configuration
  - [ ] All .env options
  - [ ] Security considerations
  - [ ] Multi-environment setup
- [ ] Create architecture diagram
  - [ ] AWS service interactions
  - [ ] Data flow
  - [ ] Authentication flow

---

## Phase 4: Feature Development & Testing

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

## Phase 5: Launch & Operations

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

## AWS Backup Configuration (Production Only, Can Defer)
- [ ] Configure AWS Backup for weekly backups:
  - [ ] DynamoDB tables (1-year retention)
  - [ ] S3 buckets (1-year retention)
  - [ ] Cross-region replication to secondary US region
- [ ] Test backup and restore process
- [ ] Document backup/restore procedures

---

## Notes

- **Volunteer Context:** This is a volunteer-run project with limited resources. Prioritize MVP features and simplicity.
- **Cost Awareness:** Use AWS Free Tier where possible; monitor costs closely.
- **Community Contributions:** Accept pull requests and community feedback once open source.
- **Iteration Over Perfection:** Ship a functional v1 and iterate based on real-world usage.

---

## Gap Analysis Summary

See `GAP_ANALYSIS.md` for a detailed comparison of planning documents vs. this TODO.
