# -----------------------------------------------------------------------------
# Amazon Athena Workgroup and Query Configuration
# -----------------------------------------------------------------------------

resource "aws_athena_workgroup" "governance_workgroup" {
  name        = "${var.project_name}-governance-workgroup-${var.environment}"
  description = "Dedicated Athena workgroup for AI Agent Governance SQL Analytics"
  state       = "ENABLED"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.analytics_results.bucket}/athena-query-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }

  tags = {
    Name = "${var.project_name}-athena-workgroup-${var.environment}"
  }
}
