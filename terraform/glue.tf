# -----------------------------------------------------------------------------
# AWS Glue Catalog Database and External Table for Audit Analytics
# -----------------------------------------------------------------------------

resource "aws_glue_catalog_database" "governance_db" {
  name        = "${var.project_name}_governance_db_${var.environment}"
  description = "Glue data catalog database for AI Agent Governance and Audit analytics"
}

resource "aws_glue_catalog_table" "audit_analytics" {
  name          = "audit_analytics"
  database_name = aws_glue_catalog_database.governance_db.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"         = "json"
    "EXTERNAL"               = "TRUE"
    "typeOfData"             = "file"
    "has_encrypted_data"     = "false"
  }

  # Partitioning keys for analytics query optimization: date and task_type
  partition_keys {
    name = "date"
    type = "string"
  }

  partition_keys {
    name = "task_type"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.analytics_results.bucket}/results/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.IgnoreKeyTextOutputFormat"

    ser_de_info {
      name                  = "JsonSerDe"
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
      parameters = {
        "serialization.format"   = "1"
        "ignore.malformed.json"  = "TRUE"
        "dots.in.keys"           = "FALSE"
        "case.insensitive"       = "TRUE"
      }
    }

    # Columns match actual stored analytics JSON records
    columns {
      name = "trace_id"
      type = "string"
    }

    columns {
      name = "risk_score"
      type = "double"
    }

    columns {
      name = "risk_tier"
      type = "string"
    }

    columns {
      name = "pii_count"
      type = "int"
    }

    columns {
      name = "scope_violations"
      type = "int"
    }

    columns {
      name = "groundedness_failures"
      type = "int"
    }

    columns {
      name = "unsupported_claims"
      type = "int"
    }

    columns {
      name = "contradicted_claims"
      type = "int"
    }

    columns {
      name = "violated_tools"
      type = "array<string>"
    }

    columns {
      name = "summary"
      type = "string"
    }

    columns {
      name = "status"
      type = "string"
    }

    columns {
      name = "processed_at"
      type = "string"
    }
  }
}
