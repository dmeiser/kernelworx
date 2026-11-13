# DynamoDB Tables Module
# Schema matches actual existing AWS tables
#
# NOTE: server_side_encryption.enabled must be false to use the AWS-owned key.
# enabled = true (or omitting kms_key_arn inside the block) defaults to the
# AWS-managed key (alias/aws/dynamodb), which incurs per-request KMS charges.
# DynamoDB encryption at rest is always on; enabled = false just selects the
# no-additional-cost AWS-owned key.

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type        = string
}

variable "region_abbrev" {
  description = "Short region code used in table names (e.g., ue1)"
  type        = string
}

variable "name_prefix" {
  description = "Global name prefix for DynamoDB tables"
  type        = string
}

variable "enable_point_in_time_recovery" {
  description = "Enable DynamoDB point-in-time recovery (recommended for production)"
  type        = bool
  default     = false
}

variable "prevent_destroy" {
  description = "Set to false for ephemeral environments that must be destroyed after use."
  type        = bool
  default     = true
}

variable "enable_deletion_protection" {
  description = "Enable AWS deletion protection on DynamoDB tables. Disable for ephemeral environments."
  type        = bool
  default     = true
}

locals {
  table_suffix = "-${var.region_abbrev}-${var.environment}"
  tags = {
    Environment = var.environment
    ManagedBy   = "opentofu"
    Project     = var.name_prefix
  }
}

# ============================================================================
# Accounts Table
# PK: accountId
# GSI: email-index (email)                      -- exact email lookup
# GSI: emailSearchIndex (emailSearchKey, email)  -- email prefix search
#
# emailSearchIndex is a prefix-segment index: a constant HASH key plus `email`
# as the RANGE key, which is what makes `begins_with(email, :prefix)` a legal
# key condition (email-index is HASH-only, so a Query key condition there must
# be an equality and cannot answer a partial email).
#
# The index is SPARSE: an account item is only searchable once it carries
# `emailSearchKey`. Deployment order for this index is therefore:
#   1. deploy the account write path (post_authentication sets `emailSearchKey`),
#   2. run the backfill for pre-existing rows
#      (scripts/backfill_email_search_key.py, then --verify to confirm zero
#      remaining rows), and only then
#   3. apply this table change.
# Skipping step 2 makes existing accounts invisible to prefix search.
# ============================================================================
resource "aws_dynamodb_table" "accounts" {
  name                        = "${var.name_prefix}-accounts${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "accountId"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "accountId"
    type = "S"
  }

  attribute {
    name = "email"
    type = "S"
  }

  attribute {
    name = "emailSearchKey"
    type = "S"
  }

  global_secondary_index {
    name            = "email-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "email"
      key_type       = "HASH"
    }
  }

  global_secondary_index {
    name            = "emailSearchIndex"
    projection_type = "ALL"

    key_schema {
      attribute_name = "emailSearchKey"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "email"
      key_type       = "RANGE"
    }
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Catalogs Table
# PK: catalogId
# GSI: isPublic-createdAt-index (isPublicStr, createdAt)
# GSI: ownerAccountId-index (ownerAccountId)
# ============================================================================
resource "aws_dynamodb_table" "catalogs" {
  name                        = "${var.name_prefix}-catalogs${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "catalogId"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "catalogId"
    type = "S"
  }

  attribute {
    name = "ownerAccountId"
    type = "S"
  }

  attribute {
    name = "isPublicStr"
    type = "S"
  }

  attribute {
    name = "createdAt"
    type = "S"
  }

  global_secondary_index {
    name            = "ownerAccountId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "ownerAccountId"
      key_type       = "HASH"
    }
  }

  global_secondary_index {
    name            = "isPublic-createdAt-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "isPublicStr"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "createdAt"
      key_type       = "RANGE"
    }
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Profiles Table
# PK: ownerAccountId, SK: profileId
# GSI: profileId-index (profileId)
# ============================================================================
resource "aws_dynamodb_table" "profiles" {
  name                        = "${var.name_prefix}-profiles${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "ownerAccountId"
  range_key                   = "profileId"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "ownerAccountId"
    type = "S"
  }

  attribute {
    name = "profileId"
    type = "S"
  }

  attribute {
    name = "unitType"
    type = "S"
  }

  attribute {
    name = "unitNumber"
    type = "N"
  }

  global_secondary_index {
    name            = "profileId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "profileId"
      key_type       = "HASH"
    }
  }

  global_secondary_index {
    name            = "unitType-unitNumber-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "unitType"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "unitNumber"
      key_type       = "RANGE"
    }
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Campaigns Table
# PK: profileId, SK: campaignId
# GSI: campaignId-index, catalogId-index, unitCampaignKey-index, profileId-createdAt-index
# ============================================================================
resource "aws_dynamodb_table" "campaigns" {
  name                        = "${var.name_prefix}-campaigns${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "profileId"
  range_key                   = "campaignId"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "profileId"
    type = "S"
  }

  attribute {
    name = "campaignId"
    type = "S"
  }

  attribute {
    name = "catalogId"
    type = "S"
  }

  attribute {
    name = "unitCampaignKey"
    type = "S"
  }

  attribute {
    name = "createdAt"
    type = "S"
  }

  global_secondary_index {
    name            = "campaignId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "campaignId"
      key_type       = "HASH"
    }
  }

  global_secondary_index {
    name            = "catalogId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "catalogId"
      key_type       = "HASH"
    }
  }

  global_secondary_index {
    name            = "unitCampaignKey-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "unitCampaignKey"
      key_type       = "HASH"
    }
  }

  global_secondary_index {
    name            = "profileId-createdAt-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "profileId"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "createdAt"
      key_type       = "RANGE"
    }
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Orders Table
# PK: campaignId, SK: orderId
# GSI: orderId-index
# ============================================================================
resource "aws_dynamodb_table" "orders" {
  name                        = "${var.name_prefix}-orders${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "campaignId"
  range_key                   = "orderId"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "campaignId"
    type = "S"
  }

  attribute {
    name = "orderId"
    type = "S"
  }

  global_secondary_index {
    name            = "orderId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "orderId"
      key_type       = "HASH"
    }
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Shares Table
# PK: profileId, SK: targetAccountId
# GSI: targetAccountId-index (targetAccountId)
# ============================================================================
resource "aws_dynamodb_table" "shares" {
  name                        = "${var.name_prefix}-shares${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "profileId"
  range_key                   = "targetAccountId"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "profileId"
    type = "S"
  }

  attribute {
    name = "targetAccountId"
    type = "S"
  }

  global_secondary_index {
    name            = "targetAccountId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "targetAccountId"
      key_type       = "HASH"
    }
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Invites Table
# PK: inviteCode
# GSI: profileId-index (profileId)
# TTL: expiresAt
# ============================================================================
resource "aws_dynamodb_table" "invites" {
  name                        = "${var.name_prefix}-invites${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "inviteCode"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "inviteCode"
    type = "S"
  }

  attribute {
    name = "profileId"
    type = "S"
  }

  global_secondary_index {
    name            = "profileId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "profileId"
      key_type       = "HASH"
    }
  }

  ttl {
    attribute_name = "expiresAt"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Shared Campaigns Table
# PK: sharedCampaignCode
# GSI: GSI1 (createdBy, createdAt)
# GSI: GSI2 (unitCampaignKey)
# GSI: catalogId-index (catalogId) - used to enforce catalog delete constraints
# ============================================================================
resource "aws_dynamodb_table" "shared_campaigns" {
  name                        = "${var.name_prefix}-shared-campaigns${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "sharedCampaignCode"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "sharedCampaignCode"
    type = "S"
  }

  attribute {
    name = "createdBy"
    type = "S"
  }

  attribute {
    name = "createdAt"
    type = "S"
  }

  attribute {
    name = "unitCampaignKey"
    type = "S"
  }

  attribute {
    name = "catalogId"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    projection_type = "ALL"

    key_schema {
      attribute_name = "createdBy"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "createdAt"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "GSI2"
    projection_type = "ALL"

    key_schema {
      attribute_name = "unitCampaignKey"
      key_type       = "HASH"
    }
  }

  global_secondary_index {
    name            = "catalogId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "catalogId"
      key_type       = "HASH"
    }
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Public Order Throttles Table
# PK: key ("<shareToken>#<windowStartEpoch>")
# TTL: expiresAt (epoch seconds)
#
# Abuse guard for the anonymous publicCreateOrder write path (SEC-6): one small
# item per (share token, 60s window), atomically ADDed by the pipeline's
# throttle step. TTL is load-bearing only for storage reclamation - the window
# in the key means an expired item is never read. No GSIs: reads are GetItem-
# free (the throttle is a blind UpdateItem keyed by construction).
# ============================================================================
resource "aws_dynamodb_table" "public_order_throttles" {
  name                        = "${var.name_prefix}-public-order-throttles${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "key"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "key"
    type = "S"
  }

  ttl {
    attribute_name = "expiresAt"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Units Table (Show & Sell wave 1 — docs/specs/show_sell/SHOW_AND_SELL_DATA_MODEL.md §6.1)
# PK: pk   ("UNIT#<unitId>" | "INVITE#<inviteCode>")
# SK: sk   ("METADATA" | "GRANT#<accountId>" | "PAYMENT#<normalizedName>" | "UNIT#<unitId>")
# Item families (single table, prefixed keys):
#   UNIT#<unitId>       / METADATA                  Unit
#   UNIT#<unitId>       / GRANT#<accountId>         UnitAccessGrant
#   UNIT#<unitId>       / PAYMENT#<normalizedName>  UnitPaymentMethod
#   INVITE#<inviteCode> / UNIT#<unitId>             UnitInvite (TTL: expiresAtEpoch)
# GSI: accountId-unitId-index   (accountId, unitId)  -- "my Units" discovery
# GSI: unitId-createdAt-index   (unitId, createdAt)  -- invites for Unit administration
# GSI: metadataKey-createdAt-index (metadataKey, createdAt) -- duplicate lookup ONLY;
#      never authorization, never uniqueness (data model §5.1/§6.1).
# Direct grant authorization and invite redemption use consistent base-table
# reads, not GSIs. Every GSI is naturally sparse (items without the key
# attribute are not indexed).
# ============================================================================
resource "aws_dynamodb_table" "units" {
  name                        = "${var.name_prefix}-units${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  range_key                   = "sk"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  attribute {
    name = "accountId"
    type = "S"
  }

  attribute {
    name = "unitId"
    type = "S"
  }

  attribute {
    name = "createdAt"
    type = "S"
  }

  attribute {
    name = "metadataKey"
    type = "S"
  }

  global_secondary_index {
    name            = "accountId-unitId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "accountId"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "unitId"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "unitId-createdAt-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "unitId"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "createdAt"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "metadataKey-createdAt-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "metadataKey"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "createdAt"
      key_type       = "RANGE"
    }
  }

  # Shared numeric epoch-seconds TTL attribute (DynamoDB allows exactly one TTL
  # attribute per table, so expiry-carrying item families share it and set it to
  # their own horizon:
  #   - UnitInvite rows: created_at + up to 14 days (data model §5.3).
  #   - Idempotency-marker rows: created_at + 7 days — the common marker
  #     convention every aggregate table carries
  #     (SHOW_AND_SELL_EXISTING_APPLICATION_IMPACT.md §4.1/§4.4 decision "one
  #     numeric epoch-seconds attribute representing seven days across all
  #     aggregate tables", §8.9 markers). Markers and invites are distinguished
  #     by the value written, never by separate attributes.
  # Application-side expiry validation remains load-bearing — TTL deletion is eventual.
  ttl {
    attribute_name = "expiresAtEpoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Unit Campaigns Table (Show & Sell wave 1 — data model §6.2)
# PK: pk ("UNIT_CAMPAIGN#<unitCampaignId>" | "UNIT_CAMPAIGN#<id>#SCOUT_CAMPAIGN#<campaignId>"
#         | "PROFILE#<profileId>" | "JOIN_CODE#<joinCode>" | "SCOUT_CAMPAIGN#<campaignId>")
# SK: sk ("METADATA" | "MEMBERSHIP#<profileId>" | "COMMITMENT_GUARD"
#         | "COMMITMENT#<startAt>#<unitCampaignId>#<slotId>" | "UNIT_CAMPAIGN#<unitCampaignId>"
#         | "MEMBERSHIP_GUARD" | "SHOW_AND_SELL_TOTAL")
# Item families: UnitCampaign, UnitCampaignMembership, ScoutCommitmentGuard,
# ScoutCommitment projection (consistent cross-campaign conflict queries on the
# PROFILE partition), join-code pointer, ScoutCampaignMembershipGuard
# (authoritative active-join lock), ScoutCampaignShowAndSellTotal.
# GSI: unitId-createdAt-index      (unitId, createdAt) -- Unit Campaign list
# GSI: campaignId-index            (campaignId)        -- membership by Scout Campaign
# GSI: profileId-unitCampaignId-index (profileId, unitCampaignId) -- membership/commitment discovery
# GSI: catalogId-index             (catalogId)         -- catalog-usage delete guard,
#      never authorization.
# Join-code and membership checks in mutations use consistent base-table reads.
# ============================================================================
resource "aws_dynamodb_table" "unit_campaigns" {
  name                        = "${var.name_prefix}-unit-campaigns${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  range_key                   = "sk"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  attribute {
    name = "unitId"
    type = "S"
  }

  attribute {
    name = "createdAt"
    type = "S"
  }

  attribute {
    name = "campaignId"
    type = "S"
  }

  attribute {
    name = "profileId"
    type = "S"
  }

  attribute {
    name = "unitCampaignId"
    type = "S"
  }

  attribute {
    name = "catalogId"
    type = "S"
  }

  global_secondary_index {
    name            = "unitId-createdAt-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "unitId"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "createdAt"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "campaignId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "campaignId"
      key_type       = "HASH"
    }
  }

  global_secondary_index {
    name            = "profileId-unitCampaignId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "profileId"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "unitCampaignId"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "catalogId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "catalogId"
      key_type       = "HASH"
    }
  }

  # Common seven-day idempotency-marker TTL (marker-bearing aggregate table,
  # §8.9; same expiresAtEpoch convention as the units table — see the units
  # ttl block comment for the full marker/invite contract).
  ttl {
    attribute_name = "expiresAtEpoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Inventory Table (Show & Sell wave 1 — data model §6.3)
# PK: pk ("UNIT_CAMPAIGN#<unitCampaignId>")  -- one campaign partition allows a
#                                              consistent current-inventory report
# SK: sk ("PRODUCT#<productId>#BALANCE"                          InventoryBalance
#         | "PRODUCT#<productId>#EVENT#<showAndSellId>"          EventInventoryAllocation
#         | "PRODUCT#<productId>#CUSTODY#<profileId>"            ScoutCustodyBalance
#         | "PRODUCT#<productId>#MOVEMENT#<occurredAt>#<movementId>"  InventoryMovement (append-only))
# GSI: showAndSellId-index       (showAndSellId) -- event-allocation discovery for display;
#      authoritative finalization uses ShowAndSell.productIds + consistent
#      product-prefix queries, never this eventually consistent index.
# GSI: profileId-unitCampaignId-index (profileId, unitCampaignId) -- per-Scout custody discovery
# GSI: movementType-occurredAt-index  (movementType, occurredAt)  -- audit filtering only,
#      not required for balance correctness.
# Transactional shape (data model §8.4): balance-serialized conditional writes
# (InventoryBalance.version) — the AppSync service-role grant set (including
# ConditionCheckItem for transaction condition checks) covers these tables via
# the table_arns map wiring in each environment.
# ============================================================================
resource "aws_dynamodb_table" "inventory" {
  name                        = "${var.name_prefix}-inventory${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  range_key                   = "sk"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  attribute {
    name = "showAndSellId"
    type = "S"
  }

  attribute {
    name = "profileId"
    type = "S"
  }

  attribute {
    name = "unitCampaignId"
    type = "S"
  }

  attribute {
    name = "movementType"
    type = "S"
  }

  attribute {
    name = "occurredAt"
    type = "S"
  }

  global_secondary_index {
    name            = "showAndSellId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "showAndSellId"
      key_type       = "HASH"
    }
  }

  global_secondary_index {
    name            = "profileId-unitCampaignId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "profileId"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "unitCampaignId"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "movementType-occurredAt-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "movementType"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "occurredAt"
      key_type       = "RANGE"
    }
  }

  # Common seven-day idempotency-marker TTL (marker-bearing aggregate table,
  # §8.9; same expiresAtEpoch convention as the units table). Balance,
  # allocation, custody, and append-only movement rows never carry expiry.
  ttl {
    attribute_name = "expiresAtEpoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Order Fulfillments Table (Show & Sell wave 1 — data model §6.5)
# PK: pk ("ORDER#<orderId>")
# SK: sk ("FULFILLMENT#<createdAt>#<fulfillmentId>"        OrderFulfillment (append-only)
#         | "REVERSAL#<reversalOfFulfillmentId>")          deterministic at-most-once
#                                                        reversal key: a reversal
#                                                        for the same fulfillment
#                                                        collides on this SK and
#                                                        cannot be written twice.
# Existing Orders stay in the orders table and are updated transactionally with
# these rows (fulfillmentVersion guard, §5.19/§8.5).
# GSI: campaignId-createdAt-index (campaignId, createdAt) -- Campaign fulfillment history.
# ============================================================================
resource "aws_dynamodb_table" "order_fulfillments" {
  name                        = "${var.name_prefix}-order-fulfillments${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  range_key                   = "sk"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  attribute {
    name = "campaignId"
    type = "S"
  }

  attribute {
    name = "createdAt"
    type = "S"
  }

  global_secondary_index {
    name            = "campaignId-createdAt-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "campaignId"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "createdAt"
      key_type       = "RANGE"
    }
  }

  # Common seven-day idempotency-marker TTL (marker-bearing aggregate table,
  # §8.9; same expiresAtEpoch convention as the units table). Fulfillment and
  # reversal records never carry expiry — only marker rows set the attribute.
  ttl {
    attribute_name = "expiresAtEpoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Show And Sells Table (Show & Sell wave 1 — data model §6.4)
# PK: pk ("SHOW_AND_SELL#<showAndSellId>")
# SK: sk ("METADATA"                                                      ShowAndSell
#         | "SLOT#<slotId>"                                               ShowAndSellSlot
#         | "SIGNUP#<slotId>#<profileId>"                                 ShowAndSellSignup
#         | "SALE#<saleId>"                                               current ShowAndSellSale revision
#         | "SALE#<saleId>#REVISION#<revision>"                           immutable prior-revision audit
#         | "FINALIZATION#<finalizationId>"                               ShowAndSellFinalization
#         | "FINALIZATION#<finalizationId>#RETURN#<productId>"            ReturnReconciliationLine
#         | "FINALIZATION#<finalizationId>#SALE#<saleId>"                 FinalizationSaleSnapshot
#         | "FINALIZATION#<finalizationId>#WORK#<slotId>#<profileId>"     FinalizationWorkSnapshot
#         | "CREDIT#<finalizationId>#<profileId>"                         ScoutSalesAllocation
#         | "WE_OWE#<weOweId>"                                            WeOweObligation
#         | "WE_OWE#<weOweId>#FULFILLMENT#<fulfillmentId>")               WeOweFulfillment
# The SALE/FINALIZATION/CREDIT/WE_OWE namespaces are declared now so later
# waves never migrate keys; nothing writes them yet.
# GSI: unitCampaignId-startAt-index (unitCampaignId, startAt) -- event scheduling/list
# GSI: saleId-index                 (saleId)        -- direct sale lookup
# GSI: weOweId-index                (weOweId)       -- direct obligation lookup
# GSI: campaignId-status-index      (campaignId, status) -- approved credit history/report
# GSI: unitCampaignId-status-index  (unitCampaignId, status) -- open/closed We Owe + operational reports
# Current approved Scout totals use the ScoutCampaignShowAndSellTotal record in
# unit_campaigns, never this eventually consistent credit GSI alone.
# ============================================================================
resource "aws_dynamodb_table" "show_and_sells" {
  name                        = "${var.name_prefix}-show-and-sells${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  range_key                   = "sk"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  attribute {
    name = "unitCampaignId"
    type = "S"
  }

  attribute {
    name = "startAt"
    type = "S"
  }

  attribute {
    name = "saleId"
    type = "S"
  }

  attribute {
    name = "weOweId"
    type = "S"
  }

  attribute {
    name = "campaignId"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  global_secondary_index {
    name            = "unitCampaignId-startAt-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "unitCampaignId"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "startAt"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "saleId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "saleId"
      key_type       = "HASH"
    }
  }

  global_secondary_index {
    name            = "weOweId-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "weOweId"
      key_type       = "HASH"
    }
  }

  global_secondary_index {
    name            = "campaignId-status-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "campaignId"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "status"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "unitCampaignId-status-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "unitCampaignId"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "status"
      key_type       = "RANGE"
    }
  }

  # Common seven-day idempotency-marker TTL (marker-bearing aggregate table,
  # §8.9; same expiresAtEpoch convention as the units table). Business rows
  # (events, sales, finalizations, credits, We Owe) never carry expiry.
  ttl {
    attribute_name = "expiresAtEpoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = false
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = var.prevent_destroy
  }
}

# ============================================================================
# Outputs
# ============================================================================
output "table_arns" {
  description = "Map of all DynamoDB table ARNs"
  value = {
    accounts               = aws_dynamodb_table.accounts.arn
    catalogs               = aws_dynamodb_table.catalogs.arn
    profiles               = aws_dynamodb_table.profiles.arn
    campaigns              = aws_dynamodb_table.campaigns.arn
    orders                 = aws_dynamodb_table.orders.arn
    shares                 = aws_dynamodb_table.shares.arn
    invites                = aws_dynamodb_table.invites.arn
    shared_campaigns       = aws_dynamodb_table.shared_campaigns.arn
    public_order_throttles = aws_dynamodb_table.public_order_throttles.arn
    units                  = aws_dynamodb_table.units.arn
    unit_campaigns         = aws_dynamodb_table.unit_campaigns.arn
    inventory              = aws_dynamodb_table.inventory.arn
    order_fulfillments     = aws_dynamodb_table.order_fulfillments.arn
    show_and_sells         = aws_dynamodb_table.show_and_sells.arn
  }
}

output "table_names" {
  description = "Map of all DynamoDB table names"
  value = {
    accounts               = aws_dynamodb_table.accounts.name
    catalogs               = aws_dynamodb_table.catalogs.name
    profiles               = aws_dynamodb_table.profiles.name
    campaigns              = aws_dynamodb_table.campaigns.name
    orders                 = aws_dynamodb_table.orders.name
    shares                 = aws_dynamodb_table.shares.name
    invites                = aws_dynamodb_table.invites.name
    shared_campaigns       = aws_dynamodb_table.shared_campaigns.name
    public_order_throttles = aws_dynamodb_table.public_order_throttles.name
    units                  = aws_dynamodb_table.units.name
    unit_campaigns         = aws_dynamodb_table.unit_campaigns.name
    inventory              = aws_dynamodb_table.inventory.name
    order_fulfillments     = aws_dynamodb_table.order_fulfillments.name
    show_and_sells         = aws_dynamodb_table.show_and_sells.name
  }
}

# Individual table name outputs for module references
output "accounts_table_name" {
  description = "Name of the accounts DynamoDB table"
  value       = aws_dynamodb_table.accounts.name
}

output "catalogs_table_name" {
  description = "Name of the catalogs DynamoDB table"
  value       = aws_dynamodb_table.catalogs.name
}

output "profiles_table_name" {
  description = "Name of the profiles DynamoDB table"
  value       = aws_dynamodb_table.profiles.name
}

output "campaigns_table_name" {
  description = "Name of the campaigns DynamoDB table"
  value       = aws_dynamodb_table.campaigns.name
}

output "orders_table_name" {
  description = "Name of the orders DynamoDB table"
  value       = aws_dynamodb_table.orders.name
}

output "shares_table_name" {
  description = "Name of the shares DynamoDB table"
  value       = aws_dynamodb_table.shares.name
}

output "invites_table_name" {
  description = "Name of the invites DynamoDB table"
  value       = aws_dynamodb_table.invites.name
}

output "shared_campaigns_table_name" {
  description = "Name of the shared campaigns DynamoDB table"
  value       = aws_dynamodb_table.shared_campaigns.name
}

# Show & Sell wave 1 — the five individual table-name outputs are the
# documented downstream wiring interface (SHOW_AND_SELL_EXISTING_APPLICATION_IMPACT.md
# §4.1): later waves' Lambda environment variables and resolver wiring resolve
# names through these outputs, not through the aggregate maps.
output "units_table_name" {
  description = "Name of the units DynamoDB table"
  value       = aws_dynamodb_table.units.name
}

output "unit_campaigns_table_name" {
  description = "Name of the unit campaigns DynamoDB table"
  value       = aws_dynamodb_table.unit_campaigns.name
}

output "inventory_table_name" {
  description = "Name of the inventory DynamoDB table"
  value       = aws_dynamodb_table.inventory.name
}

output "show_and_sells_table_name" {
  description = "Name of the show and sells DynamoDB table"
  value       = aws_dynamodb_table.show_and_sells.name
}

output "order_fulfillments_table_name" {
  description = "Name of the order fulfillments DynamoDB table"
  value       = aws_dynamodb_table.order_fulfillments.name
}
