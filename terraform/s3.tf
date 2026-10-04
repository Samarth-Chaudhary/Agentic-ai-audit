# Raw Trace Bucket with WORM Immutability (SOC 2 Type II / SEC 17a-4 / EU AI Act)
resource "aws_s3_bucket" "traces" {
  bucket              = "${var.project_name}-${var.trace_bucket_name}-${var.environment}"
  force_destroy       = var.environment == "dev"
  object_lock_enabled = true
}

# S3 Versioning (Prerequisite for Object Lock and Tamper Prevention)
resource "aws_s3_bucket_versioning" "traces" {
  bucket = aws_s3_bucket.traces.id
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 Object Lock Configuration (7-Year Compliance Mode WORM Retention)
resource "aws_s3_bucket_object_lock_configuration" "traces" {
  bucket = aws_s3_bucket.traces.id
  rule {
    default_retention {
      mode  = "COMPLIANCE"
      years = 7
    }
  }
}

# Block Public Access for Traces Bucket
resource "aws_s3_bucket_public_access_block" "traces" {
  bucket = aws_s3_bucket.traces.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Server-side encryption with AWS managed AES256 for Traces Bucket
resource "aws_s3_bucket_server_side_encryption_configuration" "traces" {
  bucket = aws_s3_bucket.traces.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Bucket ownership controls
resource "aws_s3_bucket_ownership_controls" "traces" {
  bucket = aws_s3_bucket.traces.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Analytics Results Bucket (Destination for processed AuditResults)
resource "aws_s3_bucket" "analytics_results" {
  bucket        = "${var.project_name}-${var.result_bucket_name}-${var.environment}"
  force_destroy = var.environment == "dev"
}

resource "aws_s3_bucket_public_access_block" "analytics_results" {
  bucket = aws_s3_bucket.analytics_results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "analytics_results" {
  bucket = aws_s3_bucket.analytics_results.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "analytics_results" {
  bucket = aws_s3_bucket.analytics_results.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# S3 -> SQS ObjectCreated Notification
# Scoped appropriately to traces/ prefix and .json suffix
resource "aws_s3_bucket_notification" "trace_upload_notification" {
  bucket = aws_s3_bucket.traces.id

  queue {
    queue_arn     = aws_sqs_queue.traces_queue.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "traces/"
    filter_suffix = ".json"
  }

  depends_on = [aws_sqs_queue_policy.allow_s3_to_send_messages]
}
