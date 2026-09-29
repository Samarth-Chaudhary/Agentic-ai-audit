variable "aws_region" {
  type        = string
  description = "AWS region for deploying infrastructure"
  default     = "us-east-1"
}

variable "environment" {
  type        = string
  description = "Deployment environment name (dev, staging, prod)"
  default     = "dev"
}

variable "project_name" {
  type        = string
  description = "Project identifier prefix"
  default     = "agent-audit"
}

variable "trace_bucket_name" {
  type        = string
  description = "Name for the raw trace S3 bucket"
  default     = "agent-audit-raw-traces"
}

variable "result_bucket_name" {
  type        = string
  description = "Name for the analytics results S3 bucket"
  default     = "agent-audit-analytics-results"
}

variable "dynamodb_table_name" {
  type        = string
  description = "Name for the DynamoDB audit results table"
  default     = "agent-audit-results"
}

variable "sns_topic_name" {
  type        = string
  description = "Name for the SNS high-risk alerts topic"
  default     = "audit-high-risk-alerts"
}

variable "audit_lambda_image_uri" {
  type        = string
  description = "ECR Image URI for the Audit Lambda container"
  default     = ""
}
