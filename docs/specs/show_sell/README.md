# Show & Sell and inventory design package

This directory contains the product requirements, technical design, acceptance scenarios, integration analysis, and delivery plan for the Show & Sell and inventory feature.

**Status:** Design and planning only. No production data migration or backfill is required because there are no production users. No resolver, infrastructure, or application implementation has been added by this package.

## Reading order

1. [Product requirements and MoSCoW specification](SHOW_AND_SELL_INVENTORY_SPECIFICATION.md)
2. [Logical and physical data model](SHOW_AND_SELL_DATA_MODEL.md)
3. [GraphQL resolver contracts](SHOW_AND_SELL_GRAPHQL_API.md)
4. [Transaction sequence diagrams](SHOW_AND_SELL_SEQUENCE_DIAGRAMS.md)
5. [Existing-application impact map](SHOW_AND_SELL_EXISTING_APPLICATION_IMPACT.md)
6. [Business-workflow smoke test plan](SHOW_AND_SELL_SMOKE_TEST_PLAN.md)
7. [Endpoint E2E test descriptions](SHOW_AND_SELL_GRAPHQL_E2E_TEST_DESCRIPTIONS.md)
8. [Browser-only reporting architecture](BROWSER_REPORTING_ARCHITECTURE.md)
9. [Delivery checklist](SHOW_AND_SELL_DELIVERY_CHECKLIST.md)

## Document guide

| Document | What it contains | When to use it |
| --- | --- | --- |
| [Show & Sell and inventory: MoSCoW and specification](SHOW_AND_SELL_INVENTORY_SPECIFICATION.md) | Confirmed product requirements, domain terms, MoSCoW priorities, security and business rules, reporting requirements, acceptance criteria, and decision-resolution log | Start here for what the product must do and what is explicitly out of scope |
| [Show & Sell and inventory data model](SHOW_AND_SELL_DATA_MODEL.md) | Logical entities and fields, ER diagram, enums, relationships, invariants, derived formulas, DynamoDB keys/indexes, state transitions, and model acceptance checks | Use when implementing persistence, authorization checks, transactions, and reconciliation |
| [Show & Sell and inventory GraphQL API contract](SHOW_AND_SELL_GRAPHQL_API.md) | Query/mutation inputs and outputs, caller roles, resource scoping, validation, pagination, versioning, idempotency, limits, and error semantics | Use when defining GraphQL SDL and resolver behavior or reviewing API security |
| [Show & Sell and inventory transaction sequence diagrams](SHOW_AND_SELL_SEQUENCE_DIAGRAMS.md) | Mermaid diagrams for signup, allocation, sale, finalization, reopen/re-finalization, and individual/Scout-custody fulfillment, including reads, conditions, writes, retries, and write-set accounting | Use for transaction implementation and concurrency/failure-path review |
| [Existing-application impact map](SHOW_AND_SELL_EXISTING_APPLICATION_IMPACT.md) | File-by-file integration analysis for backend, frontend, infrastructure, IAM, deletion, cleanup, recovery, CI, and tests, plus implementation order and remaining policy decisions | Use to avoid regressions in the current application and to plan integration work |
| [Show & Sell and inventory smoke test plan](SHOW_AND_SELL_SMOKE_TEST_PLAN.md) | Named personas, synthetic Units/Scouts/products, deterministic workflow steps, expected balances, fixture acceptance criteria, parallel test-lane model, and cleanup requirements | Use for end-to-end acceptance testing and fixture implementation |
| [Show & Sell GraphQL endpoint E2E test descriptions](SHOW_AND_SELL_GRAPHQL_E2E_TEST_DESCRIPTIONS.md) | Endpoint-level positive and negative tests for authorization, validation, versions, idempotency, pagination, outputs, and limits | Use for live GraphQL integration and security testing |
| [Browser-only reporting and document generation](BROWSER_REPORTING_ARCHITECTURE.md) | Global browser-only reporting rule, data-loading and validation responsibilities, CSV/XLSX/print/ICS generation, security, performance, and legacy-report migration phases | Use for all report UI, exports, printable documents, and frontend-generated calendar invites |
| [Show & Sell and inventory delivery checklist](SHOW_AND_SELL_DELIVERY_CHECKLIST.md) | Nine delivery stages broken into bounded work orders, ownership constraints, testing and validation gates, and release-readiness criteria | Use for implementation planning, work assignment, and stage-completion review |

## Design invariants

These decisions apply across the package:

- **Unit Admin and Unit Kernel are synonyms** for one Unit-scoped role.
- **Catalog → Inventory → Show & Sell** is the product relationship. There is no event-wide product-count cap.
- **All reporting and document generation happens in the browser**, including CSV/XLSX, printable documents, and ICS files.
- **No production data migration or backfill** is needed.
- New operations must preserve tenant isolation, stock/custody invariants, idempotency, exact-cent Scout credit, and complete audit history.
- Existing application behavior, deletion flows, IAM scoping, and recovery paths must be updated deliberately rather than bypassed.

## Related source material

The package also includes links among the documents themselves. The requirements specification links to the data model, API contract, reporting architecture, sequence diagrams, E2E descriptions, delivery checklist, and existing-application impact map.
