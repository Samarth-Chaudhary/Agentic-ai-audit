# Dead Letter Queue (DLQ)
resource "aws_sqs_queue" "traces_dlq" {
  name                      = "${var.project_name}-traces-dlq-${var.environment}"
  message_retention_seconds = 1209600 # 14 days retention for troubleshooting failed traces
  sqs_managed_sse_enabled   = true
}

# Primary Trace Ingestion Queue
resource "aws_sqs_queue" "traces_queue" {
  name                       = "${var.project_name}-traces-queue-${var.environment}"
  visibility_timeout_seconds = 300   # 5 minutes to accommodate NLP inference and cold starts
  message_retention_seconds  = 345600 # 4 days retention
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.traces_dlq.arn
    maxReceiveCount     = 3
  })
}

# SQS Queue Policy allowing S3 to send messages
resource "aws_sqs_queue_policy" "allow_s3_to_send_messages" {
  queue_url = aws_sqs_queue.traces_queue.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowS3ObjectCreatedNotification"
        Effect    = "Allow"
        Principal = {
          Service = "s3.amazonaws.com"
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.traces_queue.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_s3_bucket.traces.arn
          }
        }
      }
    ]
  })
}
