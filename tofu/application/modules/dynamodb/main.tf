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
# Show & Sell tables (wave 1, integration plan section 5 step 2; impact map
# section 4.1). Base-key convention follows THIS module (natural compound
# keys), not the clean-room PK/SK design — handlers are re-expressed against
# these keys in later waves. Aggregate tables hold multiple entity kinds,
# discriminated by the range-key attribute `itemKey` (e.g. METADATA,
# GRANT#<accountId>, INVITE#<joinCode>, PAYMENT#<paymentMethodId>,
# BALANCE#<productId>, MOVEMENT#<occurredAt>#<movementId>, EVENT#<showAndSellId>,
# SALE#<saleId>, WEOWE#<weOweId>, IDEM#<markerKey>).
#
# TTL: a single numeric epoch-seconds attribute `expiresAtEpoch` per table.
# UnitInvite rows expire at invite expiry; idempotency-marker rows expire at
# commit time + 7 days (the map's common marker convention). Numeric epoch,
# distinct from the legacy string/throttle TTLs elsewhere in this module.
# ============================================================================

# ----------------------------------------------------------------------------
# Units Table
# PK: unitId, SK: itemKey
# Rows: METADATA (one per Unit; carries accountId of the creating owner,
#       createdAt, metadataKey), GRANT#<accountId> (one per granted Account),
#       INVITE#<joinCode> (one per outstanding invite; metadataKey=joinCode
#       enables code redemption through the metadataKey-createdAt-index),
#       PAYMENT#<paymentMethodId> (Unit payment methods),
#       IDEM#<scope>#<markerKey> (idempotency markers).
# GSI: accountId-unitId-index (accountId HASH, unitId RANGE) — an Account's
#      Units via its GRANT rows plus owning METADATA row.
# GSI: unitId-createdAt-index (unitId HASH, createdAt RANGE) — Unit-scoped
#      history ordered by time (metadata/grant/invite audit).
# GSI: metadataKey-createdAt-index (metadataKey HASH, createdAt RANGE) —
#      join-code redemption lookup (INVITE rows) and metadata registry.
# TTL: expiresAtEpoch (UnitInvite rows reap after expiry).
# ----------------------------------------------------------------------------
resource "aws_dynamodb_table" "units" {
  name                        = "${var.name_prefix}-units${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "unitId"
  range_key                   = "itemKey"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "unitId"
    type = "S"
  }

  attribute {
    name = "itemKey"
    type = "S"
  }

  attribute {
    name = "accountId"
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

# ----------------------------------------------------------------------------
# Unit Campaigns Table
# PK: unitCampaignId, SK: itemKey
# Rows: METADATA (one per Unit Campaign; carries unitId, campaignId, catalogId,
#       createdAt), MEMBER#<profileId> (roster; carries profileId, createdAt),
#       COMMIT#<showAndSellId>#<profileId> (slot commitments),
#       GUARD#<guardKey> (ACTIVE roster/guard rows), TOTAL#<profileId> (Scout
#       sales totals), IDEM#<scope>#<markerKey> (idempotency markers).
# GSI: unitId-createdAt-index (unitId HASH, createdAt RANGE) — a Unit's Unit
#      Campaigns in time order.
# GSI: campaignId-index (campaignId HASH) — the joined Scout Campaign's Unit
#      Campaign (authoritative join pointer; impact map 3.3 soft-delete guard).
# GSI: profileId-unitCampaignId-index (profileId HASH, unitCampaignId RANGE) —
#      a Scout's memberships across Units.
# GSI: catalogId-index (catalogId HASH) — catalog usage guard without a Scan.
# ----------------------------------------------------------------------------
resource "aws_dynamodb_table" "unit_campaigns" {
  name                        = "${var.name_prefix}-unit-campaigns${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "unitCampaignId"
  range_key                   = "itemKey"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "unitCampaignId"
    type = "S"
  }

  attribute {
    name = "itemKey"
    type = "S"
  }

  attribute {
    name = "unitId"
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
    name = "profileId"
    type = "S"
  }

  attribute {
    name = "createdAt"
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

# ----------------------------------------------------------------------------
# Inventory Table
# PK: unitCampaignId, SK: itemKey
# Rows: BALANCE#<productId> (on-hand balance; conditional updates are the
#       stock authority), ALLOC#<showAndSellId>#<productId> (event
#       allocations), CUSTODY#<profileId>#<productId> (with-Scout custody),
#       MOVEMENT#<occurredAt>#<movementId> (append-style movement audit),
#       IDEM#<scope>#<markerKey> (idempotency markers).
# GSI: showAndSellId-index (showAndSellId HASH) — an event's allocations.
# GSI: profileId-unitCampaignId-index (profileId HASH, unitCampaignId RANGE) —
#      a Scout's custody across Unit Campaigns.
# GSI: movementType-occurredAt-index (movementType HASH, occurredAt RANGE) —
#      movement audit by type (optional in the map; included — our handlers
#      use it for the audit surfaces).
# ----------------------------------------------------------------------------
resource "aws_dynamodb_table" "inventory" {
  name                        = "${var.name_prefix}-inventory${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "unitCampaignId"
  range_key                   = "itemKey"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "unitCampaignId"
    type = "S"
  }

  attribute {
    name = "itemKey"
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

# ----------------------------------------------------------------------------
# Show & Sells Table (the events aggregate)
# PK: unitCampaignId, SK: itemKey
# Rows: EVENT#<showAndSellId> (event metadata; carries startAt, status,
#       campaignId), SLOT#<showAndSellId>#<slotId> (time slots),
#       SIGNUP#<slotId>#<profileId> (signups/commitments),
#       SALE#<saleId> (sales; carries saleId, status),
#       SALEREV#<saleId>#<revisionId> (sale revisions),
#       FINAL#<finalizationId> (finalization versions),
#       CREDIT#<profileId>#<factId> (credit allocation facts),
#       WEOWE#<weOweId> (We Owe obligations),
#       WEOWEFULF#<weOweId>#<fulfillmentId>,
#       IDEM#<scope>#<markerKey> (idempotency markers).
# GSI: unitCampaignId-startAt-index (unitCampaignId HASH, startAt RANGE) —
#      upcoming/past event listing.
# GSI: saleId-index (saleId HASH) — sale lookup by id.
# GSI: weOweId-index (weOweId HASH) — obligation lookup by bearer id.
# GSI: campaignId-status-index (campaignId HASH, status RANGE).
# GSI: unitCampaignId-status-index (unitCampaignId HASH, status RANGE) —
#      event listing by lifecycle state.
# ----------------------------------------------------------------------------
resource "aws_dynamodb_table" "show_and_sells" {
  name                        = "${var.name_prefix}-show-and-sells${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "unitCampaignId"
  range_key                   = "itemKey"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "unitCampaignId"
    type = "S"
  }

  attribute {
    name = "itemKey"
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
    name = "startAt"
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

# ----------------------------------------------------------------------------
# Order Fulfillments Table
# PK: orderId, SK: fulfillmentId
# Rows: one per fulfillment; reversals are separate rows whose fulfillmentId
# is the deterministic REVERSAL#<originalFulfillmentId> (impact map 4.1),
# never an overwrite — fulfillment history is append-only.
# GSI: campaignId-createdAt-index (campaignId HASH, createdAt RANGE) —
#      campaign-scoped fulfillment listing (spec 10.2 orderFulfillments).
# ----------------------------------------------------------------------------
resource "aws_dynamodb_table" "order_fulfillments" {
  name                        = "${var.name_prefix}-order-fulfillments${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "orderId"
  range_key                   = "fulfillmentId"
  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "orderId"
    type = "S"
  }

  attribute {
    name = "fulfillmentId"
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
    show_and_sells         = aws_dynamodb_table.show_and_sells.arn
    order_fulfillments     = aws_dynamodb_table.order_fulfillments.arn
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
    show_and_sells         = aws_dynamodb_table.show_and_sells.name
    order_fulfillments     = aws_dynamodb_table.order_fulfillments.name
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
