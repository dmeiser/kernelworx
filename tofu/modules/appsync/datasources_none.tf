# AppSync None Data Sources

# None data source for computed/passthrough resolvers
resource "aws_appsync_datasource" "none" {
  api_id = aws_appsync_graphql_api.main.id
  name   = "NoneDataSource"
  type   = "NONE"
}

# Additional None data sources for payment methods
resource "aws_appsync_datasource" "payment_methods_none" {
  api_id = aws_appsync_graphql_api.main.id
  name   = "PaymentMethodsNoneDataSource"
  type   = "NONE"
}

resource "aws_appsync_datasource" "filter_payment_methods_none" {
  api_id = aws_appsync_graphql_api.main.id
  name   = "FilterPaymentMethodsNoneDataSource"
  type   = "NONE"
}
