# AppSync None Data Sources

# None data source for computed/passthrough resolvers.
# A NONE data source is stateless and interchangeable, so every passthrough
# resolver/function shares this single declaration (#750).
resource "aws_appsync_datasource" "none" {
  api_id = aws_appsync_graphql_api.main.id
  name   = "NoneDataSource"
  type   = "NONE"
}
