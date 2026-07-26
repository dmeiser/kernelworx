# REST API Gateway Resources & Custom Domain Configuration
#
# Routes are defined declaratively in local.routes and compiled into a single
# OpenAPI 3.0 spec passed as the REST API body. API Gateway materializes all
# resources/methods/integrations from the spec in one operation, avoiding the
# AWS provider v6 bug where aws_api_gateway_integration with count/for_each
# sends an empty http_method to AWS.

# =============================================================================
# Route table: one row per (path, method, lambda, auth) tuple.
# `auth` = true -> Cognito authorizer; false -> NONE (public).
# `path` is the full API Gateway path (OpenAPI-style, with {param} segments).
# =============================================================================

locals {
  api_name = "${var.name_prefix}-api-${var.region_abbrev}-${var.environment}"

  routes = [
    { path = "/",                                          method = "GET",    lambda = "auth",                   auth = false },
    { path = "/login",                                     method = "GET",    lambda = "auth",                   auth = false },
    { path = "/signup",                                    method = "GET",    lambda = "auth",                   auth = false },
    { path = "/privacy",                                   method = "GET",    lambda = "auth",                   auth = false },
    { path = "/story",                                     method = "GET",    lambda = "auth",                   auth = false },
    { path = "/api/auth/login",                            method = "POST",   lambda = "auth",                   auth = false },
    { path = "/api/auth/signup",                           method = "POST",   lambda = "auth",                   auth = false },
    { path = "/api/auth/session",                          method = "POST",   lambda = "auth",                   auth = false },
    { path = "/scouts",                                    method = "GET",    lambda = "scouts",                 auth = true },
    { path = "/home",                                      method = "GET",    lambda = "scouts",                 auth = true },
    { path = "/catalogs",                                  method = "GET",    lambda = "catalogs",               auth = true },
    { path = "/payment-methods",                           method = "GET",    lambda = "payment-methods",        auth = true },
    { path = "/admin",                                     method = "GET",    lambda = "admin",                  auth = true },
    { path = "/campaigns",                                 method = "GET",    lambda = "campaigns",              auth = true },
    { path = "/orders",                                    method = "GET",    lambda = "orders",                 auth = true },
    { path = "/scout-management",                          method = "GET",    lambda = "sharing",                auth = true },
    { path = "/account/settings",                          method = "GET",    lambda = "sharing",                auth = true },
    { path = "/api/profiles/new-form",                     method = "GET",    lambda = "scouts",                 auth = true },
    { path = "/api/profiles",                              method = "POST",   lambda = "scouts",                 auth = true },
    { path = "/api/profiles/{profileId}",                  method = "DELETE", lambda = "scouts",                 auth = true },
    { path = "/api/profiles/{profileId}/transfer",         method = "POST",   lambda = "transfer-ownership",     auth = true },
    { path = "/api/profiles/{profileId}/cascade-delete",   method = "POST",   lambda = "delete-profile-cascade", auth = true },
    { path = "/api/campaigns/new-form",                    method = "GET",    lambda = "campaigns",              auth = true },
    { path = "/api/campaigns",                             method = "POST",   lambda = "campaigns",              auth = true },
    { path = "/api/campaigns/{campaignId}",                method = "DELETE", lambda = "campaigns",              auth = true },
    { path = "/api/orders",                                method = "GET",    lambda = "orders",                 auth = true },
    { path = "/api/orders",                                method = "POST",   lambda = "orders",                 auth = true },
    { path = "/api/orders/{orderId}",                      method = "DELETE", lambda = "orders",                 auth = true },
    { path = "/api/catalogs/{catalogId}",                  method = "DELETE", lambda = "catalogs",               auth = true },
    { path = "/api/catalogs/in-use",                       method = "GET",    lambda = "list-catalogs-in-use",   auth = true },
    { path = "/api/payment-methods/validate",              method = "POST",   lambda = "validate-payment-method", auth = true },
    { path = "/api/payment-methods/qr-upload-form",        method = "GET",    lambda = "payment-methods",        auth = true },
    { path = "/api/payment-methods/qr-upload",             method = "POST",   lambda = "payment-methods",        auth = true },
    { path = "/api/payment-methods/qr-confirm",            method = "POST",   lambda = "payment-methods",        auth = true },
    { path = "/api/payment-methods/{paymentMethodId}/qr-presigned-url", method = "POST", lambda = "generate-qr-presigned-url", auth = true },
    { path = "/api/shares",                                method = "POST",   lambda = "sharing",                auth = true },
    { path = "/api/invites",                               method = "POST",   lambda = "sharing",                auth = true },
    { path = "/api/admin/search-users",                    method = "GET",    lambda = "admin",                  auth = true },
    { path = "/admin/user-data/{accountId}",               method = "GET",    lambda = "admin",                  auth = true },
    { path = "/api/unit-catalogs",                         method = "GET",    lambda = "list-unit-catalogs",     auth = true },
    { path = "/api/unit-campaign-catalogs",                method = "GET",    lambda = "list-unit-catalogs",     auth = true },
    { path = "/api/account",                               method = "POST",   lambda = "account-operations",     auth = true },
    { path = "/api/account/delete",                        method = "POST",   lambda = "account-operations",     auth = true },
    { path = "/scouts/{profileId}",                        method = "GET",    lambda = "campaigns",              auth = true },
    { path = "/scouts/{profileId}/campaigns",              method = "GET",    lambda = "campaigns",              auth = true },
    { path = "/scouts/{profileId}/campaigns/{campaignId}", method = "GET",    lambda = "orders",                 auth = true },
    { path = "/scouts/{profileId}/campaigns/{campaignId}/orders", method = "GET", lambda = "orders",            auth = true },
    { path = "/scouts/{profileId}/campaigns/{campaignId}/orders/{orderId}/edit", method = "GET", lambda = "orders", auth = true },
    { path = "/scouts/{profileId}/campaigns/{campaignId}/new",   method = "GET", lambda = "orders",              auth = true },
    { path = "/scouts/{profileId}/campaigns/{campaignId}/edit",  method = "GET", lambda = "orders",              auth = true },
    { path = "/scouts/{profileId}/manage",                 method = "GET",    lambda = "sharing",                auth = true },
  ]

  # Per-route OpenAPI operation object. The integration httpMethod is always
  # POST (Lambda Invoke API); the route's HTTP method is the path-level key.
  openapi_operations = {
    for r in local.routes : "${r.path}~${lower(r.method)}" => {
      responses = {
        "200" = { description = "200 response" }
      }
      security = r.auth ? [{ CustomAuthorizer = [] }] : []
      "x-amazon-apigateway-integration" = {
        type                    = "aws_proxy"
        httpMethod              = "POST"
        uri                     = "arn:aws:apigateway:${var.aws_region}:lambda:path/2015-03-31/functions/${var.lambda_function_arns[r.lambda]}/invocations"
        connectionType          = "INTERNET"
        passthroughBehavior     = "when_no_match"
      }
    }
  }

  # Group operations by path so each path key maps to { <method>: <operation> }.
  openapi_paths = {
    for path in distinct([for r in local.routes : r.path]) :
    path => {
      for r in local.routes :
      lower(r.method) => local.openapi_operations["${r.path}~${lower(r.method)}"]
      if r.path == path
    }
  }

  # Health check as a MOCK integration in the OpenAPI spec.
  health_response_template = file("${path.module}/../../../../src/vtl/health_check_response.vtl")

  openapi_paths_with_health = merge(
    local.openapi_paths,
    {
      "/health" = {
        get = {
          responses = {
            "200" = {
              description = "200 response"
              headers = {
                "Content-Type" = {
                  schema = { type = "string" }
                }
              }
              content = {
                "text/html" = {
                  schema = { type = "string" }
                }
              }
            }
          }
          security = []
          "x-amazon-apigateway-integration" = {
            type                = "mock"
            requestTemplates = {
              "application/json" = "{\"statusCode\": 200}"
            }
            responses = {
              "200" = {
                statusCode        = "200"
                responseParameters = {
                  "method.response.header.Content-Type" = "'text/html'"
                }
                responseTemplates = {
                  "text/html" = local.health_response_template
                }
              }
            }
          }
        }
      }
    }
  )

  openapi_spec = {
    openapi = "3.0.1"
    info = {
      title   = local.api_name
      version = "1.0"
    }
    paths = local.openapi_paths_with_health
    components = {
      securitySchemes = {
        CustomAuthorizer = {
          type                           = "apiKey"
          name                           = "Unused"
          in                             = "header"
          "x-amazon-apigateway-authtype" = "custom"
          "x-amazon-apigateway-authorizer" = {
            type             = "request"
            identitySource   = "method.request.header.Cookie"
            resultTtlInSeconds = 0
            authorizerUri    = "arn:aws:apigateway:${var.aws_region}:lambda:path/2015-03-31/functions/${var.authorizer_lambda_arn}/invocations"
            authorizerCredentials = var.apigateway_execution_role_arn
          }
        }
      }
    }
    security = [{ CustomAuthorizer = [] }]
  }
}

# =============================================================================
# REST API: body is the OpenAPI spec. API Gateway creates all
# resources/methods/integrations from it. The Cognito authorizer is referenced
# in the spec by name via the securitySchemes definition; API Gateway resolves
# it to the authorizer created below (same REST API).
# =============================================================================

resource "aws_api_gateway_rest_api" "main" {
  name        = local.api_name
  description = "KernelWorx REST API Gateway for HTMX frontend"

  body = jsonencode(local.openapi_spec)

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

# =============================================================================
# Lambda permissions: allow API Gateway to invoke every app Lambda
# =============================================================================

# kics-scan ignore-line
resource "aws_lambda_permission" "apigw_invoke" {
  for_each = var.lambda_function_arns

  statement_id  = "AllowAPIGatewayInvoke-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = each.value
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*"
}

# kics-scan ignore-line
resource "aws_lambda_permission" "apigw_authorizer_invoke" {
  statement_id  = "AllowAPIGatewayInvoke-authorizer"
  action        = "lambda:InvokeFunction"
  function_name = var.authorizer_lambda_arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*"
}

# kics-scan ignore-line
resource "aws_iam_role_policy" "apigw_authorizer_invoke" {
  name = "apigw-authorizer-invoke"
  role = var.apigateway_execution_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = var.authorizer_lambda_arn
      }
    ]
  })
}

# =============================================================================
# API Deployment & Stage (depends on the REST API body, not individual
# integrations — API Gateway manages methods/integrations internally from spec)
# =============================================================================

resource "aws_api_gateway_deployment" "main" {
  rest_api_id = aws_api_gateway_rest_api.main.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_rest_api.main.body,
      local.routes,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_lambda_permission.apigw_invoke,
    aws_lambda_permission.apigw_authorizer_invoke,
    aws_iam_role_policy.apigw_authorizer_invoke,
  ]
}

resource "aws_api_gateway_stage" "main" {
  deployment_id = aws_api_gateway_deployment.main.id
  rest_api_id   = aws_api_gateway_rest_api.main.id
  stage_name    = var.environment
}

# Custom Domain Name
resource "aws_api_gateway_domain_name" "api" {
  domain_name              = var.api_domain
  regional_certificate_arn = var.api_certificate_arn

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_base_path_mapping" "api" {
  api_id      = aws_api_gateway_rest_api.main.id
  stage_name  = aws_api_gateway_stage.main.stage_name
  domain_name = aws_api_gateway_domain_name.api.domain_name
  base_path   = ""
}