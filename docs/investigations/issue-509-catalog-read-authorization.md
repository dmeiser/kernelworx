# #509 investigation record — catalog read paths and ownership checks

**Status:** investigation only. The fix for #509 is **not** implemented.
This file preserves the reachability map so a clean session can implement the fix
without re-deriving it. The commit that adds this file is an investigation record,
not the fix.

## The defect (issue #509, verbatim severity)

Private catalogs (`isPublic == false`) are readable by ID by **any** authenticated
user. The stated mitigation is UUID obscurity, which is not a durable boundary
because `Campaign.catalog` returns the full catalog item (including soft-deleted
catalogs) and campaigns are readable by anyone holding a share on the profile.

The fix must add the ownership/public check to the by-ID catalog read path(s):
return the catalog when `isPublic == true`, OR `catalogType == 'ADMIN_MANAGED'`,
OR `ownerAccountId == 'ACCOUNT#' + ctx.identity.sub`; otherwise refuse (null).

## Reachability map — catalog read paths, and which lack an ownership check

### 1. `getCatalog` GraphQL QUERY — **the by-ID read path, NO ownership check (defect)**

- Resolver: `tofu/application/modules/appsync/resolvers_queries.tf:271`
  (`resource "aws_appsync_resolver" "get_catalog"`, `type = "Query"`,
  `field = "getCatalog"`).
- **VTL / VTemplate path** (not a JavaScript resolver):
  - request: `tofu/application/appsync/mapping-templates/get_catalog_request.vtl`
  - response: `tofu/application/appsync/mapping-templates/get_catalog_response.vtl`
- Behavior: unauthenticated-free — any authenticated Cognito user can call
  `getCatalog(catalogId:)` and the response template emits the item for any
  existing catalog, with no ownership/public check. This is the defect.
- **Note for the fix:** the response template needs the caller identity.
  `$ctx.identity` is available in AppSync response mapping templates; no request
  template change is strictly required to read it. (No existing VTL response
  template in this repo currently references `$ctx.identity`, so this is the
  first — verify the harness/test supplies `ctx.identity`.)

### 2. `createOrder` pipeline step — JavaScript resolver, NO catalog-ownership check, **but already gated by profile write access**

- Function: `aws_appsync_function.get_catalog` → code
  `tofu/application/appsync/js-resolvers/get_catalog_fn.js`
  (defined in `functions_orders.tf:107`).
- **JavaScript resolver path** (APPSYNC_JS 1.0.0).
- Used in **exactly one** place: the `createOrder` pipeline,
  `tofu/application/modules/appsync/resolvers_mutations.tf:298`. It is **not**
  the `getCatalog` query.
- The pipeline is:
  `verify_profile_write_access` → `verify_profile_write_access_step2` →
  `check_share_permissions` → `validate_payment_method_appsync` →
  `get_campaign_for_order` → `get_catalog` → `create_order`.
- `verify_profile_write_access` + `check_share_permissions` already authorize the
  caller as **profile owner OR a WRITE share-holder** before `get_catalog` runs.
  `get_catalog_fn.js` then reads the campaign's catalog and stashes it so
  `create_order_fn.js` can price line items (it uses the catalog to compute
  totals; it does not return the catalog to the client).
- **Consequence for the fix (CRITICAL — do not regress):** the caller of
  `get_catalog_fn.js` is *not* necessarily the catalog owner. A WRITE share-holder
  (a helper) legitimately places an order on a campaign whose catalog is the
  profile owner's *private* (`isPublic == false`, `catalogType == 'USER_CREATED'`)
  catalog. If the ownership check from #509 is applied verbatim to
  `get_catalog_fn.js` (allow only `isPublic || ADMIN_MANAGED || owner==caller`),
  that helper's order placement would start failing
  (`create_order_fn.js` sees a null catalog and errors
  "Catalog could not be loaded for this campaign"). The createOrder step is
  already authorized by profile write access; adding a catalog-ownership check
  there would change behavior beyond the reported defect. The reported defect
  (any authenticated user reading a catalog by ID) is **not** reachable through
  createOrder, because createOrder requires a campaign + profile write access.

## Fix scope conclusion (for the implementing session)

- The reported "readable by ID by any authenticated user" defect is the
  **`getCatalog` query (path 1, VTL response template)**. That is the path with
  no authorization at all.
- `get_catalog_fn.js` (path 2) is a shared createOrder step, already gated by
  profile write access. Adding the ownership check there breaks legitimate
  order placement by non-catalog-owners (WRITE share-holders). See the
  "CRITICAL" note above.
- Decide with firstmate whether the fix is:
  (a) VTL response template only (fixes the exposed by-ID read; leaves createOrder
  as-is, already authorized), or
  (b) both files — which requires the createOrder step to keep working for
  non-catalog-owner callers (i.e., the ownership check there must not deny a
  caller who is authorized via profile write access).
- Regression test must use a **different** authenticated caller (not the owner)
  and prove the denial (null / refusal), failing before the fix and passing after.

## Files and line references

- Defect (no check, by-ID read API):
  - `tofu/application/appsync/mapping-templates/get_catalog_response.vtl:7-9`
  - `tofu/application/modules/appsync/resolvers_queries.tf:271-278`
- Shared createOrder step (no catalog-ownership check, but profile-gated):
  - `tofu/application/appsync/js-resolvers/get_catalog_fn.js:5-6,33-34`
  - `tofu/application/modules/appsync/functions_orders.tf:107-118`
  - `tofu/application/modules/appsync/resolvers_mutations.tf:284-302` (pipeline)
- Existing tests to extend alongside:
  - `tofu/application/appsync/js-resolvers/get_catalog_fn.test.js`
  - `tests/unit/catalog_request_vtl.test.ts` (VTL harness usage reference)
  - `tests/unit/appsync_vtl_harness.ts` (harness; may need `$util.toJson`,
    the `+` string-concat operator, and `.isEmpty` on maps to render a
    response template)

## Schema doc comment that becomes factually wrong after the fix

`tofu/application/schema/schema.graphql:197` and the generated
`frontend/src/types/graphql-generated.ts:189` both state:
"Catalogs are visible to any authenticated user by ID (getCatalog performs no
ownership check)." After the fix, the by-ID read enforces ownership/public.
