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
# Units Table (Show & Sell Stage 1 — docs/specs/show_sell/SHOW_AND_SELL_DATA_MODEL.md §6.1)
# PK: pk, SK: sk
#   UNIT#<unitId>       / METADATA                    Unit
#   UNIT#<unitId>       / GRANT#<accountId>           UnitAccessGrant
#   UNIT#<unitId>       / PAYMENT#<normalizedName>    UnitPaymentMethod (Stage 4 write path)
#   INVITE#<inviteCode> / UNIT#<unitId>               UnitInvite
#   IDEM#<actorId>#<operationType>#<scope> / IDEM#<idempotencyKey>            idempotency marker
#     (the marker SK is `IDEM#<idempotencyKey>`; the bootstrap scope for
#      createUnit is `BOOTSTRAP`, so the marker never depends on the Unit it
#      creates — data model §8.9)
# GSI: accountId-unitId-index (accountId, unitId)   grants for "my Units" discovery
# GSI: unitId-createdAt-index (unitId, createdAt)   invites for Unit administration;
#      sparse — only invite items carry both attributes
# GSI: metadataKey-createdAt-index (metadataKey, createdAt)
#      possible-duplicate lookup; WARNING ONLY — metadataKey is never unique and
#      never authorizes anything (data model §5.1 invariant)
# TTL: expiresAtEpoch (epoch seconds)
#   Two item classes use this one attribute name with DIFFERENT horizons and
#   must not be confused: a UnitInvite item carries its own expiry (max 14
#   days out, data model §5.3), while an idempotency marker carries the common
#   seven-day marker horizon (impact map §4.1). Application-side expiry checks
#   remain load-bearing — DynamoDB TTL only reclaims storage and can lag.
#
# Direct grant authorization and invite redemption use strongly consistent
# base-table reads (PK/SK are constructed from the credential or the id), never
# a GSI; the GSIs only serve list/discovery pages.
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
# Unit Campaigns Table (Show & Sell Stage 1 — data model §6.2)
# PK: pk, SK: sk
#   UNIT_CAMPAIGN#<unitCampaignId>                                / METADATA                      UnitCampaign
#   UNIT_CAMPAIGN#<unitCampaignId>                                / MEMBERSHIP#<profileId>        UnitCampaignMembership
#   PROFILE#<profileId>                                           / COMMITMENT_GUARD              ScoutCommitmentGuard (Stage 3)
#   PROFILE#<profileId>                                           / COMMITMENT#<startAt>#<unitCampaignId>#<slotId>
#                                                                                                 ScoutCommitment projection (Stage 3)
#   JOIN_CODE#<joinCode>                                          / UNIT_CAMPAIGN#<unitCampaignId> join-code pointer
#   SCOUT_CAMPAIGN#<campaignId>                                   / MEMBERSHIP_GUARD              ScoutCampaignMembershipGuard
#   UNIT_CAMPAIGN#<unitCampaignId>#SCOUT_CAMPAIGN#<campaignId>    / SHOW_AND_SELL_TOTAL           ScoutCampaignShowAndSellTotal (Stage 5)
# GSI: unitId-createdAt-index (unitId, createdAt)          Unit Campaign list
# GSI: campaignId-index (campaignId)                       membership lookup by Scout Campaign
# GSI: profileId-unitCampaignId-index (profileId, unitCampaignId)
#          membership/commitment discovery
# GSI: catalogId-index (catalogId)                         catalog-usage guard for Unit Campaign
#          references (a catalog referenced by any Unit Campaign is in use and
#          cannot be soft-deleted as unused, impact map §3.3); never used for
#          authorization, and its presence is what keeps that guard a Query
#          rather than a Scan.
#
# The join-code pointer, the membership guard, and the membership row are all
# reached by constructed-key strongly consistent base-table reads; join-code and
# membership checks in mutations never read a GSI (data model §6.2).
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

# The throttle table already existed but carried no individual output: the
# Show & Sell Unit-invite redemption throttle reuses it under a distinct key
# contract (data model §6.6, impact map §4.4), and that handler needs the name
# as a single-purpose environment value rather than a map index.
output "public_order_throttles_table_name" {
  description = "Name of the public order throttles DynamoDB table"
  value       = aws_dynamodb_table.public_order_throttles.name
}

output "units_table_name" {
  description = "Name of the Units DynamoDB table"
  value       = aws_dynamodb_table.units.name
}

output "unit_campaigns_table_name" {
  description = "Name of the Unit Campaigns DynamoDB table"
  value       = aws_dynamodb_table.unit_campaigns.name
}
