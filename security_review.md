# Comprehensive Security Review and Audit Report: KernelWorx

This report presents a detailed security audit of the `kernelworx` repository. The codebase implements a popcorn sales management application designed to coordinate fundraising campaigns for Scout units. The application uses a modern serverless stack built with AWS AppSync (GraphQL), AWS Lambda (Python), DynamoDB, Amazon S3, and AWS Cognito, with a React-based frontend.

---

## Executive Summary

The KernelWorx architecture incorporates robust baseline security controls, including automated encryption at-rest, strict transport encryption, fine-grained IAM roles, and a granular owner-based and shared authorization design. This review identified several gaps; as of the latest verification the cascade-deletion and input-validation issues are resolved, the deprecated `xlsx` dependency is updated, and the federated auto-link path now requires a verified email. Live findings that still require attention are the COPPA compliance posture and a partial user-enumeration leak in the share lookup resolver.

---

## 1. Access Control and Authorization Model

### 1.1 Owner-Based and Share-Based Access Control
The application implements a two-tier permission system for Scout profiles:
1. **Owners:** The user account that created the profile has full read and write access.
2. **Shared Users:** Other authenticated users who are granted explicit access (either `READ` or `WRITE`) via profile sharing.

This model is enforced consistently across both python backend Lambdas and AppSync JS resolvers:
- **Lambda Verification:** [auth.py](file:///home/dm/code/kernelworx/src/utils/auth.py) implements the logic via direct lookups. The `profiles` table is queried using the `profileId-index` GSI to check the owner, and the `shares` table is queried to check granted permissions.
- **AppSync JS Verification:** JS resolvers (such as [check_profile_read_auth_fn.js](file:///home/dm/code/kernelworx/tofu/application/appsync/js-resolvers/check_profile_read_auth_fn.js) and [check_share_permissions_fn.js](file:///home/dm/code/kernelworx/tofu/application/appsync/js-resolvers/check_share_permissions_fn.js)) implement the same logic directly in pipeline resolvers, minimizing DynamoDB queries by stashing the profile metadata across functions.

### 1.2 Cascade Deletion Bug (Major / Critical) — Fixed
The cascade-deletion logic was moved from the AppSync JS resolvers cited below into the Python Lambda `src/handlers/delete_profile_cascade.py`. The JS resolver files (`delete_profile_shares_fn.js`, `delete_profile_campaigns_fn.js`, `delete_profile_invites_fn.js`) no longer exist in the deployed pipeline.

**Status:** Resolved. The original first-record-only deletion path has been replaced.
### 1.3 User Enumeration via Share API (Minor) — Partially Fixed
The API endpoint for direct sharing ([lookup_account_by_email_fn.js](file:///home/dm/code/kernelworx/tofu/application/appsync/js-resolvers/lookup_account_by_email_fn.js#L20-L22)) queries the accounts table via the `email-index` GSI. If the account does not exist, it throws a specific error:
```javascript
    if (!ctx.result.items || ctx.result.items.length === 0) {
        util.error('No account found with email ' + ctx.args.input.targetAccountEmail, 'NotFound');
    }
```
**Impact:** Any authenticated user can enumerate registered users on the system by calling `shareProfileDirect` with different emails and analyzing the returned errors.

**Status:** Partially fixed. The resolver still distinguishes registered vs. unregistered accounts through success/error responses, so the enumeration channel remains open. A uniform response (e.g., a generic success with no account details) is needed to close it completely.
---

## 2. Secrets Management

### 2.1 Configuration and Git Status
Local environment secrets are managed via [ .env](file:///home/dm/code/kernelworx/.env), which contains API keys, identity provider credentials (`google_client_secret`), and test passwords.
- **Git Protection:** The `.env` file is properly gitignored under `.env*` rules in [ .gitignore](file:///home/dm/code/kernelworx/.gitignore#L97-L98).
- **Terraform / OpenTofu Variables:** Secrets like `google_client_secret` are defined as `sensitive = true` variables in [main.tf](file:///home/dm/code/kernelworx/tofu/application/environments/dev/main.tf#L97) and [main.tf](file:///home/dm/code/kernelworx/tofu/application/modules/cognito/main.tf#L36). This ensures they are not logged to stdout during pipeline runs.

### 2.2 IAM Least Privilege
The IAM module ([main.tf](file:///home/dm/code/kernelworx/tofu/application/modules/iam/main.tf)) maintains a tight permission model:
- **Lambda IAM Role:** Restricts S3 actions specifically to the `exports` bucket and DynamoDB actions to the application tables.
- **AppSync Service Role:** Limits `lambda:InvokeFunction` specifically to the designated application Lambdas (complying with KICS recommendations) rather than using a wildcard (`*`).

---

## 3. Input Validation

### 3.1 Backend Validation Bypass (Major) — Fixed
The Python file [validation.py](file:///home/dm/code/kernelworx/src/utils/validation.py) contains robust input validation rules, including:
- E.164 phone number formatting via [normalize_phone](file:///home/dm/code/kernelworx/src/utils/validation.py#L92)
- Detailed ZIP code matching via [validate_address](file:///home/dm/code/kernelworx/src/utils/validation.py#L119)
- Completeness checks via [validate_customer_input](file:///home/dm/code/kernelworx/src/utils/validation.py#L157)

The `createOrder` and `updateOrder` mutations now enforce validation in the AppSync JS resolver path. The raw pass-through snippet shown below has been replaced with validation that normalizes phone numbers and checks address structure before writing to DynamoDB.

**Status:** Resolved. Backend input validation is now enforced for order mutations.
### 3.2 Frontend Validation (Minor)
The frontend validation in [OrderEditorPage.tsx](file:///home/dm/code/kernelworx/frontend/src/pages/OrderEditorPage.tsx#L130-L150) is basic. It validates that a customer name is present and at least one line item is added, but depends entirely on the component's formatting wrapper rather than validating state format constraints (like phone and address components) prior to submission.

---

## 4. Dependency Security

### 4.1 Vulnerable SheetJS Dependency (Minor / Medium) — Fixed
The frontend [package.json](file:///home/dm/code/kernelworx/frontend/package.json#L37) now pins the official SheetJS distribution:
```json
    "xlsx": "https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz"
```
Version `0.20.3` is the current official release and replaces the deprecated public `0.18.5` package that was affected by Prototype Pollution (CVE-2023-30533).

**Status:** Resolved.
### 4.2 Python Dependencies
Python dependencies in [pyproject.toml](file:///home/dm/code/kernelworx/pyproject.toml#L6-L10) are clean. `openpyxl` is locked at `3.1.5` in [uv.lock](file:///home/dm/code/kernelworx/uv.lock#L878) which is not subject to known critical vulnerabilities.

---

## 5. Encryption and Transport Security

### 5.1 Encryption In-Transit
Transport security is properly configured:
- CloudFront restricts viewer protocols to redirect-to-https.
- The CloudFront viewer certificate restricts the minimum protocol version to `TLSv1.2_2021` in [main.tf](file:///home/dm/code/kernelworx/tofu/application/modules/cloudfront/main.tf#L132).
- GraphQL endpoints and static file downloads are served exclusively over HTTPS.

### 5.2 Encryption At-Rest
Encryption at-rest is configured for all data stores:
- **DynamoDB:** DynamoDB encrypts tables at rest by default; this module selects the AWS-owned key (no per-request KMS charges) in [tofu/application/modules/dynamodb/main.tf](tofu/application/modules/dynamodb/main.tf#L60).
- **S3 Buckets:** Both static and exports buckets use server-side encryption with default `SSE-S3` (`AES256`) in [main.tf](file:///home/dm/code/kernelworx/tofu/application/modules/s3/main.tf#L46).
- **Signed URL Expirations:** Payment method QR codes use a strict 15-minute expiration in [payment_methods.py](file:///home/dm/code/kernelworx/src/utils/payment_methods.py#L686), and export reports expire in 7 days via S3 lifecycle policies in [main.tf](file:///home/dm/code/kernelworx/tofu/application/modules/s3/main.tf#L101).

---

## 6. Compliance Issues (COPPA)

### 6.1 Child Privacy Risks (Major)
KernelWorx stores Scout profiles, which represent children, many of whom are under 13 years old. 

- **Data Collected:** The application collects child identifiers such as `sellerName` (the Scout's name), `unitType`/`unitNumber` (pack/troop identifier), and sales performance stats.
- **COPPA Scope:** The application's privacy policy states: *"This service is designed for use by adults... We do not knowingly collect personal information from children under 13."* ([PrivacyPolicyPage.tsx](file:///home/dm/code/kernelworx/frontend/src/pages/PrivacyPolicyPage.tsx#L120-L124)). 
- **The Risk:** While adult leaders/parents input this data, the application operator still *acquires actual knowledge* that they are collecting personal information (PII) of children under 13. COPPA rules require verifiable parental consent (VPC) for such collection unless the data is heavily pseudonymized.

**Recommendations:**
1. **Pseudonymization:** Update UI components to explicitly instruct parents to enter only the Scout's first name and last initial (or a pseudonym), preventing the collection of full child names.
2. **Consent Checkpoint:** Add a checkbox confirmation during Scout profile creation asserting that the user is the child's parent/legal guardian (or has obtained direct parental permission) to enter the name.

### 6.2 Pre-Sign-Up Auto-Link Risk (Minor) — Fixed
The Cognito pre-sign-up trigger ([pre_signup.py](file:///home/dm/code/kernelworx/src/handlers/pre_signup.py)) now links social identity providers to native Cognito accounts only when both of the following conditions are met:

1. The federated provider explicitly asserts `email_verified = "true"` (or boolean `True`).
2. The provider-supplied email passes validation before it is interpolated into the Cognito `ListUsers` filter.

If the email is unverified or invalid/unsafe, the trigger still auto-confirms the new federated account but does **not** link it to an existing native account and does not auto-verify the email.

```python
    if not _is_email_verified(user_attributes):
        logger.warning("Federated provider did not verify email, skipping auto-link")
        return _auto_confirm_event(event, verify_email=False)

    validated_email = _validate_email(email)
    if not validated_email:
        logger.warning("Invalid or unsafe email from federated provider, skipping auto-link")
        return _auto_confirm_event(event, verify_email=False)
```

**Status:** Resolved.
---

## Summary of Findings

| Severity | ID | Title | File Reference | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Major** | SEC-01 | Cascade Deletion Logic Bug Leaves Orphaned Campaigns & Shares | `src/handlers/delete_profile_cascade.py` (JS resolvers removed) | Fixed |
| **Major** | SEC-02 | Backend Input Validation Bypass for Customer Phone & Address | [create_order_fn.js](file:///home/dm/code/kernelworx/tofu/application/appsync/js-resolvers/create_order_fn.js#L106) | Fixed |
| **Major** | SEC-03 | COPPA Compliance Risks for Child (Scout) Personal Information | [PrivacyPolicyPage.tsx](file:///home/dm/code/kernelworx/frontend/src/pages/PrivacyPolicyPage.tsx#L120) | **Live** |
| **Minor** | SEC-04 | Deprecated `xlsx` Frontend Dependency (Known Vulnerabilities) | [package.json](file:///home/dm/code/kernelworx/frontend/package.json#L37) | Fixed |
| **Minor** | SEC-05 | User Enumeration / Account Existence Leak in Sharing API | [lookup_account_by_email_fn.js](file:///home/dm/code/kernelworx/tofu/application/appsync/js-resolvers/lookup_account_by_email_fn.js#L20) | Partially fixed |
| **Minor** | SEC-06 | Cognito External IdP Auto-Link without Email Verification Check | [pre_signup.py](file:///home/dm/code/kernelworx/src/handlers/pre_signup.py) | Fixed |
| **Info** | SEC-07 | AWS WAF Disabled due to Budget Constraints | [ .kics.yml](file:///home/dm/code/kernelworx/tofu/.kics.yml#L5) | Unchanged (accepted trade-off) |
| **Info** | SEC-08 | Inconsistent Invite Code Generation Logic between JS and Python | [create_invite_fn.js](file:///home/dm/code/kernelworx/tofu/application/appsync/js-resolvers/create_invite_fn.js#L13) | Not a live risk (duplicate Python path is dead code; see SF-32) |
