# Infrastructure Definitions

The authoritative cloud infrastructure definitions for this project are centralized in the root [`terraform/`](../terraform/) directory.

Components:
- S3 Buckets (`TRACE_BUCKET`, `RESULT_BUCKET`)
- SQS Queue (`SQS_QUEUE_URL`) & Dead Letter Queue (DLQ)
- DynamoDB Table (`DYNAMODB_TABLE`)
- Lambda Function (`AuditTrailWorker`)
- Athena Workgroup & Glue Data Catalog

