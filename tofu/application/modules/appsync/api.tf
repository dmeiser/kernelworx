# AppSync GraphQL API and Domain

# AppSync GraphQL API
resource "aws_appsync_graphql_api" "main" {
  name                = local.api_name
  authentication_type = "AMAZON_COGNITO_USER_POOLS"

  user_pool_config {
    aws_region     = var.aws_region
    default_action = "ALLOW"
    user_pool_id   = var.user_pool_id
  }

  # Additional auth modes
  additional_authentication_provider {
    authentication_type = "AWS_IAM"
  }

  additional_authentication_provider {
    authentication_type = "API_KEY"
  }

  xray_enabled = true

  # Schema loaded from file
  schema = file("${path.module}/../../schema/schema.graphql")

  lifecycle {
    prevent_destroy = true
  }
}

# AppSync Custom Domain
resource "aws_appsync_domain_name" "api" {
  domain_name     = local.api_domain
  certificate_arn = var.api_certificate_arn

  lifecycle {
    precondition {
      condition     = var.certificate_validation != null ? true : true
      error_message = "Certificate validation must complete before creating AppSync domain"
    }
  }
}

resource "aws_appsync_domain_name_api_association" "api" {
  api_id      = aws_appsync_graphql_api.main.id
  domain_name = aws_appsync_domain_name.api.domain_name
}
