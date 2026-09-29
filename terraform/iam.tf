# -----------------------------------------------------------------------------
# Audit Lambda IAM Role (Least Privilege)
# -----------------------------------------------------------------------------
resource "aws_iam_role" "audit_lambda_role" {
  name = "${var.project_name}-audit-lambda-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_policy" "audit_lambda_least_privilege" {
  name        = "${var.project_name}-audit-lambda-policy-${var.environment}"
  description = "Least privilege permissions for operational Audit Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # 1. CloudWatch Logging
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/*"
      },
      # 2. S3 Read of Raw Traces
      {
        Sid    = "S3ReadRawTraces"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.traces.arn,
          "${aws_s3_bucket.traces.arn}/traces/*"
        ]
      },
      # 3. S3 Write of Analytics Results
      {
        Sid    = "S3WriteAnalyticsResults"
        Effect = "Allow"
        Action = [
          "s3:PutObject"
        ]
        Resource = [
          "${aws_s3_bucket.analytics_results.arn}/results/*"
        ]
      },
      # 4. DynamoDB Write
      {
        Sid    = "DynamoDBWriteAuditResults"
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:UpdateItem"
        ]
        Resource = [
          aws_dynamodb_table.audit_results.arn
        ]
      },
      # 5. SNS Publish for High/Critical Alerts
      {
        Sid    = "SNSPublishAlerts"
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = [
          aws_sns_topic.high_risk_alerts.arn
        ]
      },
      # 6. SQS Event Source Trigger (Receive and delete processed trace events)
      {
        Sid    = "SQSConsumeTraceEvents"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = [
          aws_sqs_queue.traces_queue.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "audit_lambda_attach" {
  role       = aws_iam_role.audit_lambda_role.name
  policy_arn = aws_iam_policy.audit_lambda_least_privilege.arn
}

# -----------------------------------------------------------------------------
# Read Lambdas IAM Role (Least Privilege - Read Only)
# -----------------------------------------------------------------------------
resource "aws_iam_role" "read_lambdas_role" {
  name = "${var.project_name}-read-lambdas-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_policy" "read_lambdas_least_privilege" {
  name        = "${var.project_name}-read-lambdas-policy-${var.environment}"
  description = "Least privilege read-only permissions for List and Get Trace Lambdas"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # 1. CloudWatch Logging
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/*"
      },
      # 2. DynamoDB Read Only
      {
        Sid    = "DynamoDBReadAuditResults"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Scan",
          "dynamodb:Query"
        ]
        Resource = [
          aws_dynamodb_table.audit_results.arn,
          "${aws_dynamodb_table.audit_results.arn}/index/*"
        ]
      },
      # 3. S3 Read of Raw Traces (for Get Trace execution timeline retrieval)
      {
        Sid    = "S3ReadRawTracesTimeline"
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = [
          "${aws_s3_bucket.traces.arn}/traces/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "read_lambdas_attach" {
  role       = aws_iam_role.read_lambdas_role.name
  policy_arn = aws_iam_policy.read_lambdas_least_privilege.arn
}
