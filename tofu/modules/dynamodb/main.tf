# DynamoDB Tables Module
# Schema matches actual existing AWS tables

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type = string
}

variable "region_abbrev" {
  description = "Short region code used in table names (e.g., ue1)"
  type = string
}

variable "name_prefix" {
  description = "Global name prefix for DynamoDB tables"
  type = string
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
# GSI: email-index (email)
# ============================================================================
resource "aws_dynamodb_table" "accounts" {
  name                        = "${var.name_prefix}-accounts${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "accountId"
  deletion_protection_enabled = true

  attribute {
    name = "accountId"
    type = "S"
  }

  attribute {
    name = "email"
    type = "S"
  }

  global_secondary_index {
    name            = "email-index"
    hash_key        = "email"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = true
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
  deletion_protection_enabled = true

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
    hash_key        = "ownerAccountId"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "isPublic-createdAt-index"
    hash_key        = "isPublicStr"
    range_key       = "createdAt"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = true
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
  deletion_protection_enabled = true

  attribute {
    name = "ownerAccountId"
    type = "S"
  }

  attribute {
    name = "profileId"
    type = "S"
  }

  global_secondary_index {
    name            = "profileId-index"
    hash_key        = "profileId"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = true
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
  deletion_protection_enabled = true

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
    hash_key        = "campaignId"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "catalogId-index"
    hash_key        = "catalogId"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "unitCampaignKey-index"
    hash_key        = "unitCampaignKey"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "profileId-createdAt-index"
    hash_key        = "profileId"
    range_key       = "createdAt"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

# ============================================================================
# Orders Table
# PK: campaignId, SK: orderId
# GSI: orderId-index, profileId-index (profileId, createdAt)
# ============================================================================
resource "aws_dynamodb_table" "orders" {
  name                        = "${var.name_prefix}-orders${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "campaignId"
  range_key                   = "orderId"
  deletion_protection_enabled = true

  attribute {
    name = "campaignId"
    type = "S"
  }

  attribute {
    name = "orderId"
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
    name            = "orderId-index"
    hash_key        = "orderId"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "profileId-index"
    hash_key        = "profileId"
    range_key       = "createdAt"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = true
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
  deletion_protection_enabled = true

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
    hash_key        = "targetAccountId"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = true
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
  deletion_protection_enabled = true

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
    hash_key        = "profileId"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "expiresAt"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

# ============================================================================
# Shared Campaigns Table
# PK: sharedCampaignCode
# GSI: GSI1 (createdBy, createdAt)
# GSI: GSI2 (unitCampaignKey)
# ============================================================================
resource "aws_dynamodb_table" "shared_campaigns" {
  name                        = "${var.name_prefix}-shared-campaigns${local.table_suffix}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "sharedCampaignCode"
  deletion_protection_enabled = true

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

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "createdBy"
    range_key       = "createdAt"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "GSI2"
    hash_key        = "unitCampaignKey"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

# ============================================================================
# Outputs
# ============================================================================
output "table_arns" {
  description = "Map of all DynamoDB table ARNs"
  value = {
    accounts         = aws_dynamodb_table.accounts.arn
    catalogs         = aws_dynamodb_table.catalogs.arn
    profiles         = aws_dynamodb_table.profiles.arn
    campaigns        = aws_dynamodb_table.campaigns.arn
    orders           = aws_dynamodb_table.orders.arn
    shares           = aws_dynamodb_table.shares.arn
    invites          = aws_dynamodb_table.invites.arn
    shared_campaigns = aws_dynamodb_table.shared_campaigns.arn
  }
}

output "table_names" {
  description = "Map of all DynamoDB table names"
  value = {
    accounts         = aws_dynamodb_table.accounts.name
    catalogs         = aws_dynamodb_table.catalogs.name
    profiles         = aws_dynamodb_table.profiles.name
    campaigns        = aws_dynamodb_table.campaigns.name
    orders           = aws_dynamodb_table.orders.name
    shares           = aws_dynamodb_table.shares.name
    invites          = aws_dynamodb_table.invites.name
    shared_campaigns = aws_dynamodb_table.shared_campaigns.name
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
