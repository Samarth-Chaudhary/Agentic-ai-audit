# REST API Gateway Definition
resource "aws_api_gateway_rest_api" "audit_api" {
  name        = "${var.project_name}-governance-api-${var.environment}"
  description = "REST API for AI Agent Governance & Audit Results"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

# -----------------------------------------------------------------------------
# /traces Endpoint (Collection)
# -----------------------------------------------------------------------------
resource "aws_api_gateway_resource" "traces" {
  rest_api_id = aws_api_gateway_rest_api.audit_api.id
  parent_id   = aws_api_gateway_rest_api.audit_api.root_resource_id
  path_part   = "traces"
}

# GET /traces
resource "aws_api_gateway_method" "list_traces" {
  rest_api_id   = aws_api_gateway_rest_api.audit_api.id
  resource_id   = aws_api_gateway_resource.traces.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "list_traces" {
  rest_api_id             = aws_api_gateway_rest_api.audit_api.id
  resource_id             = aws_api_gateway_resource.traces.id
  http_method             = aws_api_gateway_method.list_traces.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.list_traces.invoke_arn
}

resource "aws_lambda_permission" "allow_apigw_list_traces" {
  statement_id  = "AllowAPIGatewayInvokeListTraces"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.list_traces.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.audit_api.execution_arn}/*/*"
}

# -----------------------------------------------------------------------------
# /traces/{trace_id} Endpoint (Item)
# -----------------------------------------------------------------------------
resource "aws_api_gateway_resource" "trace_id" {
  rest_api_id = aws_api_gateway_rest_api.audit_api.id
  parent_id   = aws_api_gateway_resource.traces.id
  path_part   = "{trace_id}"
}

# GET /traces/{trace_id}
resource "aws_api_gateway_method" "get_trace" {
  rest_api_id   = aws_api_gateway_rest_api.audit_api.id
  resource_id   = aws_api_gateway_resource.trace_id.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "get_trace" {
  rest_api_id             = aws_api_gateway_rest_api.audit_api.id
  resource_id             = aws_api_gateway_resource.trace_id.id
  http_method             = aws_api_gateway_method.get_trace.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.get_trace.invoke_arn
}

resource "aws_lambda_permission" "allow_apigw_get_trace" {
  statement_id  = "AllowAPIGatewayInvokeGetTrace"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.get_trace.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.audit_api.execution_arn}/*/*"
}

# -----------------------------------------------------------------------------
# API Deployment & Stage
# -----------------------------------------------------------------------------
resource "aws_api_gateway_deployment" "audit_deployment" {
  rest_api_id = aws_api_gateway_rest_api.audit_api.id

  depends_on = [
    aws_api_gateway_integration.list_traces,
    aws_api_gateway_integration.get_trace,
  ]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "audit_stage" {
  deployment_id = aws_api_gateway_deployment.audit_deployment.id
  rest_api_id   = aws_api_gateway_rest_api.audit_api.id
  stage_name    = var.environment
}
