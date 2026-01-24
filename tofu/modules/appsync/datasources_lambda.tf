# AppSync Lambda Data Sources

# Lambda Data Sources - one per Lambda function that AppSync calls

resource "aws_appsync_datasource" "list_my_shares" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "ListMySharesDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["list-my-shares"]
  }
}

resource "aws_appsync_datasource" "list_catalogs_in_use" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "ListCatalogsInUseDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["list-catalogs-in-use"]
  }
}

resource "aws_appsync_datasource" "create_profile" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "CreateProfileDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["create-profile"]
  }
}

resource "aws_appsync_datasource" "request_report" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "RequestReportDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["request-report"]
  }
}

resource "aws_appsync_datasource" "unit_reporting" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "UnitReportingDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["unit-reporting"]
  }
}

resource "aws_appsync_datasource" "list_unit_catalogs" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "ListUnitCatalogsDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["list-unit-catalogs"]
  }
}

resource "aws_appsync_datasource" "list_unit_campaign_catalogs" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "ListUnitCampaignCatalogsDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["list-unit-campaign-catalogs"]
  }
}

resource "aws_appsync_datasource" "campaign_operations" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "CampaignOperationsDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["campaign-operations"]
  }
}

resource "aws_appsync_datasource" "delete_profile_orders_cascade" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "DeleteProfileOrdersCascadeDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["delete-profile-orders-cascade"]
  }
}

resource "aws_appsync_datasource" "update_account" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "UpdateAccountDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["update-account"]
  }
}

resource "aws_appsync_datasource" "delete_account" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "DeleteAccountDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["delete-account"]
  }
}

resource "aws_appsync_datasource" "transfer_ownership" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "TransferOwnershipDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["transfer-ownership"]
  }
}

resource "aws_appsync_datasource" "request_qr_upload" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "RequestQRUploadDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["request-qr-upload"]
  }
}

resource "aws_appsync_datasource" "confirm_qr_upload" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "ConfirmQRUploadDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["confirm-qr-upload"]
  }
}

resource "aws_appsync_datasource" "generate_qr_presigned_url" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "GenerateQRPresignedUrlDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["generate-qr-code-presigned-url"]
  }
}

resource "aws_appsync_datasource" "delete_qr_code" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "DeleteQRCodeDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["delete-qr-code"]
  }
}

resource "aws_appsync_datasource" "validate_payment_method" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "ValidatePaymentMethodDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["validate-payment-method"]
  }
}

resource "aws_appsync_datasource" "admin_operations" {
  api_id           = aws_appsync_graphql_api.main.id
  name             = "AdminOperationsDS"
  type             = "AWS_LAMBDA"
  service_role_arn = var.appsync_service_role_arn

  lambda_config {
    function_arn = var.lambda_function_arns["admin-operations"]
  }
}

# Map of Lambda data sources
locals {
  lambda_datasources = {
    list_my_shares               = aws_appsync_datasource.list_my_shares.name
    list_catalogs_in_use         = aws_appsync_datasource.list_catalogs_in_use.name
    create_profile               = aws_appsync_datasource.create_profile.name
    request_report               = aws_appsync_datasource.request_report.name
    unit_reporting               = aws_appsync_datasource.unit_reporting.name
    list_unit_catalogs           = aws_appsync_datasource.list_unit_catalogs.name
    list_unit_campaign_catalogs  = aws_appsync_datasource.list_unit_campaign_catalogs.name
    campaign_operations          = aws_appsync_datasource.campaign_operations.name
    delete_profile_orders_cascade = aws_appsync_datasource.delete_profile_orders_cascade.name
    update_account               = aws_appsync_datasource.update_account.name
    delete_account               = aws_appsync_datasource.delete_account.name
    transfer_ownership           = aws_appsync_datasource.transfer_ownership.name
    request_qr_upload            = aws_appsync_datasource.request_qr_upload.name
    confirm_qr_upload            = aws_appsync_datasource.confirm_qr_upload.name
    generate_qr_presigned_url    = aws_appsync_datasource.generate_qr_presigned_url.name
    delete_qr_code               = aws_appsync_datasource.delete_qr_code.name
    validate_payment_method      = aws_appsync_datasource.validate_payment_method.name
    admin_operations             = aws_appsync_datasource.admin_operations.name
  }
}
