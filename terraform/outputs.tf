output "raw_traces_bucket_name" {
  description = "Name of the S3 bucket receiving raw agent execution traces"
  value       = aws_s3_bucket.traces.bucket
}

output "raw_traces_bucket_arn" {
  description = "ARN of the S3 bucket receiving raw agent execution traces"
  value       = aws_s3_bucket.traces.arn
}

output "analytics_results_bucket_name" {
  description = "Name of the S3 bucket storing processed audit analytics results"
  value       = aws_s3_bucket.analytics_results.bucket
}

output "analytics_results_bucket_arn" {
  description = "ARN of the S3 bucket storing processed audit analytics results"
  value       = aws_s3_bucket.analytics_results.arn
}

output "sqs_traces_queue_url" {
  description = "URL of the primary SQS queue receiving S3 trace upload notifications"
  value       = aws_sqs_queue.traces_queue.id
}

output "sqs_traces_queue_arn" {
  description = "ARN of the primary SQS queue"
  value       = aws_sqs_queue.traces_queue.arn
}

output "sqs_traces_dlq_url" {
  description = "URL of the Dead Letter Queue for failed trace audit processing"
  value       = aws_sqs_queue.traces_dlq.id
}

output "dynamodb_audit_results_table_name" {
  description = "Name of the DynamoDB table storing operational audit results"
  value       = aws_dynamodb_table.audit_results.name
}

output "dynamodb_audit_results_table_arn" {
  description = "ARN of the DynamoDB table"
  value       = aws_dynamodb_table.audit_results.arn
}

output "sns_high_risk_topic_arn" {
  description = "ARN of the SNS topic for high and critical risk alerts"
  value       = aws_sns_topic.high_risk_alerts.arn
}

output "audit_lambda_function_arn" {
  description = "ARN of the Audit Lambda worker function"
  value       = aws_lambda_function.audit_handler.arn
}

output "api_gateway_url" {
  description = "Invoke URL for the Agent Governance REST API"
  value       = "${aws_api_gateway_stage.audit_stage.invoke_url}/traces"
}

output "glue_database_name" {
  description = "Name of the AWS Glue catalog database for analytics"
  value       = aws_glue_catalog_database.governance_db.name
}

output "glue_table_name" {
  description = "Name of the AWS Glue catalog table for audit results"
  value       = aws_glue_catalog_table.audit_analytics.name
}

output "athena_workgroup_name" {
  description = "Name of the Athena workgroup for analytics queries"
  value       = aws_athena_workgroup.governance_workgroup.name
}

