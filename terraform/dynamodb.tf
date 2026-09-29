# DynamoDB Table for Storing Operational Audit Results
resource "aws_dynamodb_table" "audit_results" {
  name         = "${var.project_name}-${var.dynamodb_table_name}-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "trace_id"

  attribute {
    name = "trace_id"
    type = "S"
  }

  attribute {
    name = "task_type"
    type = "S"
  }

  attribute {
    name = "processed_at"
    type = "S"
  }

  # Global Secondary Index to query traces by task_type chronologically
  global_secondary_index {
    name            = "TaskTypeIndex"
    hash_key        = "task_type"
    range_key       = "processed_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Name = "${var.project_name}-audit-results-${var.environment}"
  }
}
