# Dummy placeholder archive for initial zip deployments if container image not specified
data "archive_file" "lambda_zip_placeholder" {
  type        = "zip"
  output_path = "${path.module}/placeholder_lambda.zip"

  source {
    content  = "# Placeholder code for Terraform deployment\ndef handler(event, context):\n    return {'statusCode': 200}\n"
    filename = "handler.py"
  }
}

# -----------------------------------------------------------------------------
# 1. Operational Audit Lambda Function
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "audit_handler" {
  function_name = "${var.project_name}-audit-handler-${var.environment}"
  role          = aws_iam_role.audit_lambda_role.arn
  timeout       = 300
  memory_size   = 3008

  # Container deployment strategy if image URI provided, otherwise zip placeholder
  package_type = var.audit_lambda_image_uri != "" ? "Image" : "Zip"
  image_uri    = var.audit_lambda_image_uri != "" ? var.audit_lambda_image_uri : null
  filename     = var.audit_lambda_image_uri == "" ? data.archive_file.lambda_zip_placeholder.output_path : null
  handler      = var.audit_lambda_image_uri == "" ? "lambda.audit_handler.handler" : null
  runtime      = var.audit_lambda_image_uri == "" ? "python3.11" : null

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.audit_results.name
      RESULTS_BUCKET = aws_s3_bucket.analytics_results.bucket
      SNS_TOPIC_ARN  = aws_sns_topic.high_risk_alerts.arn
    }
  }

  tags = {
    Name = "${var.project_name}-audit-handler-${var.environment}"
  }
}

# SQS -> Audit Lambda Event Source Mapping
resource "aws_lambda_event_source_mapping" "audit_sqs_trigger" {
  event_source_arn = aws_sqs_queue.traces_queue.arn
  function_name    = aws_lambda_function.audit_handler.arn
  batch_size       = 1
  enabled          = true
}

# -----------------------------------------------------------------------------
# 2. List Traces API Lambda Function
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "list_traces" {
  function_name = "${var.project_name}-list-traces-${var.environment}"
  role          = aws_iam_role.read_lambdas_role.arn
  runtime       = "python3.11"
  handler       = "lambda.list_traces.handler"
  filename      = data.archive_file.lambda_zip_placeholder.output_path
  timeout       = 30
  memory_size   = 256

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.audit_results.name
    }
  }

  tags = {
    Name = "${var.project_name}-list-traces-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# 3. Get Trace API Lambda Function
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "get_trace" {
  function_name = "${var.project_name}-get-trace-${var.environment}"
  role          = aws_iam_role.read_lambdas_role.arn
  runtime       = "python3.11"
  handler       = "lambda.get_trace.handler"
  filename      = data.archive_file.lambda_zip_placeholder.output_path
  timeout       = 30
  memory_size   = 512

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.audit_results.name
      TRACE_BUCKET   = aws_s3_bucket.traces.bucket
    }
  }

  tags = {
    Name = "${var.project_name}-get-trace-${var.environment}"
  }
}
