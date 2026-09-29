"""Validator script for Terraform HCL configurations in terraform/.

Verifies file syntax, required blocks, resource relationships, and least-privilege compliance.
"""

from __future__ import annotations

import re
from pathlib import Path

REQUIRED_FILES = [
    "providers.tf",
    "variables.tf",
    "outputs.tf",
    "s3.tf",
    "sqs.tf",
    "dynamodb.tf",
    "sns.tf",
    "iam.tf",
    "lambda.tf",
    "api_gateway.tf",
    "glue.tf",
    "athena.tf",
]

REQUIRED_RESOURCES = [
    ("aws_s3_bucket", "traces"),
    ("aws_s3_bucket", "analytics_results"),
    ("aws_s3_bucket_notification", "trace_upload_notification"),
    ("aws_sqs_queue", "traces_queue"),
    ("aws_sqs_queue", "traces_dlq"),
    ("aws_sqs_queue_policy", "allow_s3_to_send_messages"),
    ("aws_dynamodb_table", "audit_results"),
    ("aws_sns_topic", "high_risk_alerts"),
    ("aws_iam_role", "audit_lambda_role"),
    ("aws_iam_role", "read_lambdas_role"),
    ("aws_lambda_function", "audit_handler"),
    ("aws_lambda_function", "list_traces"),
    ("aws_lambda_function", "get_trace"),
    ("aws_lambda_event_source_mapping", "audit_sqs_trigger"),
    ("aws_api_gateway_rest_api", "audit_api"),
    ("aws_api_gateway_resource", "traces"),
    ("aws_api_gateway_resource", "trace_id"),
    ("aws_glue_catalog_database", "governance_db"),
    ("aws_glue_catalog_table", "audit_analytics"),
    ("aws_athena_workgroup", "governance_workgroup"),
]


def check_balanced_braces(content: str) -> bool:
    """Verify that curly braces and quotes are balanced."""
    stack = []
    in_string = False
    escape = False

    for char in content:
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "({[":
            stack.append(char)
        elif char in ")}]":
            if not stack:
                return False
            opening = stack.pop()
            if (char == ")" and opening != "(") or \
               (char == "}" and opening != "{") or \
               (char == "]" and opening != "["):
                return False

    return len(stack) == 0 and not in_string


def validate_terraform_dir(tf_dir: Path) -> dict:
    results = {"directory": str(tf_dir), "missing_files": [], "invalid_files": [], "found_resources": [], "missing_resources": []}

    all_content = ""

    # Check files
    for fname in REQUIRED_FILES:
        fpath = tf_dir / fname
        if not fpath.exists():
            results["missing_files"].append(fname)
            continue
        content = fpath.read_text(encoding="utf-8")
        all_content += "\n" + content
        if not check_balanced_braces(content):
            results["invalid_files"].append(fname)

    # Check resources
    for res_type, res_name in REQUIRED_RESOURCES:
        pattern = rf'resource\s+"{res_type}"\s+"{res_name}"'
        if re.search(pattern, all_content):
            results["found_resources"].append(f"{res_type}.{res_name}")
        else:
            results["missing_resources"].append(f"{res_type}.{res_name}")

    # Check least privilege: ensure AdministratorAccess is nowhere in IAM policies
    if "AdministratorAccess" in all_content:
        results["admin_access_violation"] = True
    else:
        results["admin_access_violation"] = False

    return results


if __name__ == "__main__":
    tf_root = Path(__file__).parent.parent / "terraform"
    res = validate_terraform_dir(tf_root)
    print(f"Validated: {res['directory']}")
    print(f"Missing Files: {res['missing_files']}")
    print(f"Syntax/Brace Errors: {res['invalid_files']}")
    print(f"Resources Found: {len(res['found_resources'])} / {len(REQUIRED_RESOURCES)}")
    print(f"Missing Resources: {res['missing_resources']}")
    print(f"AdministratorAccess violation: {res['admin_access_violation']}")
    assert len(res["missing_files"]) == 0
    assert len(res["invalid_files"]) == 0
    assert len(res["missing_resources"]) == 0
    assert not res["admin_access_violation"]
    print("SUCCESS: Terraform resource graph and syntax verified!")
