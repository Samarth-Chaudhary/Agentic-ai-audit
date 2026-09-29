# SNS Topic for High and Critical Risk Governance Alerts
resource "aws_sns_topic" "high_risk_alerts" {
  name = "${var.project_name}-${var.sns_topic_name}-${var.environment}"

  # Encryption using AWS managed SNS key
  kms_master_key_id = "alias/aws/sns"

  tags = {
    Name = "${var.project_name}-high-risk-alerts-${var.environment}"
  }
}

# Topic Policy allowing account Lambda services to publish
resource "aws_sns_topic_policy" "high_risk_alerts_policy" {
  arn = aws_sns_topic.high_risk_alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowAuditLambdaPublish"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.audit_lambda_role.arn
        }
        Action   = "sns:Publish"
        Resource = aws_sns_topic.high_risk_alerts.arn
      }
    ]
  })
}
